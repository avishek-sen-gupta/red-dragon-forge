/**
 * @name ACCEPT to DISPLAY flows
 * @kind table
 * @id cobol/accept-to-display
 */

import cobol.DataFlow

module Config implements DataFlow::ConfigSig {
  predicate isSource(DataFlow::Node n) { n.isWrite() and n.getCfgNode().getStmt().getKind() = 2 }

  predicate isSink(DataFlow::Node n) { n.isRead() and n.getCfgNode().getStmt().getKind() = 3 }
}

module Flow = DataFlow::Global<Config>;

from DataFlow::Node src, DataFlow::Node sink, Stmt accept, Stmt display
where
  Flow::flow(src, sink) and
  accept = src.getCfgNode().getStmt() and
  display = sink.getCfgNode().getStmt()
select accept.getAWrite().getName(), accept.getLocation().getStartLine() as from_line,
  display.getLocation().getStartLine() as to_line
