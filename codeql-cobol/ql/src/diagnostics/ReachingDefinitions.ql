/**
 * @name Reaching definitions
 * @description For each node's copy from a cell, the nodes whose writes it can see,
 *              by cobble's node ids, for comparison with cobble's fixpoint. A write
 *              reaches a read along SSA and through PERFORMs, never through another
 *              node's read: what a MOVE copies is a new definition.
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

  predicate isBarrierOut(DataFlow::Node n) { isSink(n) }
}

module Flow = DataFlow::Global<Config>;

from DataFlow::Node write, DataFlow::Node read, GraphNode at, Field f
where
  Flow::flow(write, read) and
  at = read.getCfgNode().getGraphNode() and
  graphCopies(at, f) and
  fieldAtom(f, read.getAtom())
select f.getProgram().getName(), at.getId(), f.getName(), f.getRecord(), f.getStart(),
  f.getLength(), write.getCfgNode().getGraphNode().getId()
