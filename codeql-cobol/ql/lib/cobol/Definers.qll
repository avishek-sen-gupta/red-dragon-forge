/**
 * The writes each read can see, by CodeQL's dataflow over cobble's graph: along SSA and
 * through PERFORMs, never into another statement's write, since what a MOVE copies is a
 * new definition. And which reads can see storage as it was before any statement ran:
 * along SSA from the start, and past each PERFORM whose range has a path that leaves the
 * bytes alone, which holds of the range wherever it is called from.
 */

import cobol.DataFlow

private predicate atNode(DataFlow::Node n) {
  exists(n.getCfgNode().getGraphNode()) and not n.getCfgNode() instanceof PerformCall
}

private module Config implements DataFlow::ConfigSig {
  predicate isSource(DataFlow::Node n) { n.isWrite() and atNode(n) }

  predicate isSink(DataFlow::Node n) { n.isRead() and atNode(n) }

  predicate isBarrierIn(DataFlow::Node n) { n.isWrite() and atNode(n) }
}

private module Flow = DataFlow::Global<Config>;

/** The write at `writer` can be what the read of `a` at `at` sees. */
predicate definer(GraphNode at, Atom a, GraphNode writer) {
  exists(DataFlow::Node write, DataFlow::Node read |
    Flow::flow(write, read) and
    at = read.getCfgNode().getGraphNode() and
    a = read.getAtom() and
    writer = write.getCfgNode().getGraphNode()
  )
}

/** `n` can hold what its atom held where its scope began. */
private predicate fromEntry(DataFlow::Node n) {
  n.isWrite() and n.getCfgNode().isEntry()
  or
  exists(DataFlow::Node m | fromEntry(m) and DataFlow::simpleLocalFlowStep(m, n, _) |
    not n.isWrite()
  )
  or
  exists(PerformCall c, DataFlow::Node arg |
    fromEntry(arg) and
    arg.isRead() and
    arg.getCfgNode() = c and
    n.isWrite() and
    n.getCfgNode() = c and
    n.getAtom() = arg.getAtom() and
    clearThrough(c.getCallee(), arg.getAtom())
  )
}

/** Some path through the range `sc` leaves `a` as it found it. */
private predicate clearThrough(Scope sc, Atom a) {
  exists(DataFlow::Node exit |
    fromEntry(exit) and
    exit.isRead() and
    exit.getCfgNode().isExit() and
    exit.getCfgNode().getScope() = sc and
    exit.getAtom() = a
  )
}

/** Control can enter `sc` with `a` as it was before any statement ran. */
private predicate enteredFromStart(Scope sc, Atom a) {
  sc.isMain() and
  exists(DataFlow::Node n |
    n.isWrite() and n.getCfgNode().isEntry() and n.getCfgNode().getScope() = sc and n.getAtom() = a
  )
  or
  exists(PerformCall c, DataFlow::Node arg |
    fromEntry(arg) and
    arg.isRead() and
    arg.getCfgNode() = c and
    arg.getAtom() = a and
    enteredFromStart(c.getScope(), a) and
    sc = c.getCallee()
  )
}

/** The read of `a` at `at` can see what `a` held before any statement ran. */
predicate startReaches(GraphNode at, Atom a) {
  exists(DataFlow::Node read |
    fromEntry(read) and
    read.isRead() and
    atNode(read) and
    at = read.getCfgNode().getGraphNode() and
    a = read.getAtom() and
    enteredFromStart(read.getCfgNode().getScope(), a)
  )
}
