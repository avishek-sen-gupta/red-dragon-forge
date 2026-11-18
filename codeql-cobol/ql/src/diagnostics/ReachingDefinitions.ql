/**
 * @name Reaching definitions
 * @description For each node's copy from a cell or consultation of one, the nodes whose
 *              writes it can see, by cobble's node ids, for comparison with cobble's
 *              fixpoint. A write reaches a read along SSA and through PERFORMs, never
 *              into another node's write: what a MOVE copies is a new definition.
 * @kind table
 * @id cobol/reaching-definitions
 */

import cobol.DataFlow

private predicate atNode(DataFlow::Node n) {
  exists(n.getCfgNode().getGraphNode()) and not n.getCfgNode() instanceof PerformCall
}

module Config implements DataFlow::ConfigSig {
  predicate isSource(DataFlow::Node n) { n.isWrite() and atNode(n) }

  predicate isSink(DataFlow::Node n) { n.isRead() and atNode(n) }

  predicate isBarrierIn(DataFlow::Node n) { n.isWrite() and atNode(n) }
}

module Flow = DataFlow::Global<Config>;

from DataFlow::Node write, DataFlow::Node read, GraphNode at, Field f, string kind
where
  Flow::flow(write, read) and
  at = read.getCfgNode().getGraphNode() and
  fieldAtom(f, read.getAtom()) and
  (
    graphCopies(at, f) and kind = "copied"
    or
    cfg_consults(at, f) and kind = "consulted"
  )
select f.getProgram().getName(), at.getId(), kind, f.getName(), f.getRecord(), f.getStart(),
  f.getLength(), write.getCfgNode().getGraphNode().getId()
