/** The demo's two questions, and their answers: each flow from a READ to its sink, and the steps of its paths. */

import cobol.DataFlow

/** File data that reaches another file: from a READ to a WRITE. */
module ReadToWrite implements DataFlow::ConfigSig {
  predicate isSource(DataFlow::Node n) {
    n.isWrite() and n.getCfgNode().getStmt() instanceof Generated::ReadStatement
  }

  predicate isSink(DataFlow::Node n) {
    n.isRead() and n.getCfgNode().getStmt() instanceof Generated::WriteStatement
  }
}

/** File data that reaches the job log: from a READ to a DISPLAY. */
module ReadToDisplay implements DataFlow::ConfigSig {
  predicate isSource(DataFlow::Node n) {
    n.isWrite() and n.getCfgNode().getStmt() instanceof Generated::ReadStatement
  }

  predicate isSink(DataFlow::Node n) {
    n.isRead() and n.getCfgNode().getStmt() instanceof Generated::DisplayStatement
  }
}

/** Where a path node sits in cobble's graph: a range's entry at its first node, its exit at its last. */
private GraphNode graphNodeOf(DataFlow::Node n) {
  exists(CfgNode c | c = n.getCfgNode() |
    result = c.getGraphNode()
    or
    c.isEntry() and result = c.getScope().getFirst()
    or
    c.isExit() and c.getScope().exitsAt(result)
  )
}

module Answers<DataFlow::ConfigSig Config> {
  private module Flow = DataFlow::Global<Config>;

  /** Some byte the READ `read` puts in storage reaches the statement `sink`. */
  predicate flow(Stmt read, Stmt sink) {
    exists(DataFlow::Node a, DataFlow::Node b |
      Flow::flow(a, b) and read = a.getCfgNode().getStmt() and sink = b.getCfgNode().getStmt()
    )
  }

  predicate step(string program, string source, string target) {
    exists(Flow::PathNode a, Flow::PathNode b, GraphNode x, GraphNode y |
      Flow::PathGraph::edges(a, b, _, _) and
      x = graphNodeOf(a.getNode()) and
      y = graphNodeOf(b.getNode()) and
      x != y and
      program = x.getProgram().getName() and
      source = x.getId() and
      target = y.getId()
    )
  }
}
