/**
 * @name Sinks
 * @description Each node's bytes sent out of the program, with the nodes whose writes
 *              they carry: the node itself where it writes them, as a WRITE FROM does,
 *              else what reaches it. By cobble's node ids, for comparison with cobble's
 *              fixpoint.
 * @kind table
 * @id cobol/sinks
 */

import cobol.DataFlow

private predicate atNode(DataFlow::Node n) {
  exists(n.getCfgNode().getGraphNode()) and not n.getCfgNode() instanceof PerformCall
}

module Config implements DataFlow::ConfigSig {
  predicate isSource(DataFlow::Node n) { n.isWrite() and atNode(n) }

  predicate isSink(DataFlow::Node n) {
    n.isRead() and sink(n.getCfgNode().getStmt(), _, _)
  }

  predicate isBarrierIn(DataFlow::Node n) { n.isWrite() and atNode(n) }
}

module Flow = DataFlow::Global<Config>;

private predicate selfWritten(GraphNode g, Atom a) {
  exists(Field w | graphWrites(g, w, false) and fieldAtom(w, a))
}

from GraphNode at, Stmt s, string kind, Field f, Atom a, string definer
where
  s = at.getStmt() and
  sink(s, kind, f) and
  fieldAtom(f, a) and
  (
    selfWritten(at, a) and definer = at.getId()
    or
    not selfWritten(at, a) and
    exists(DataFlow::Node write, DataFlow::Node read |
      Flow::flow(write, read) and
      read.getCfgNode().getGraphNode() = at and
      read.getAtom() = a and
      definer = write.getCfgNode().getGraphNode().getId()
    )
  )
select f.getProgram().getName(), at.getId(), kind, f.getName(), f.getRecord(), f.getStart(),
  f.getLength(), definer
