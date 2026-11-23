/**
 * The writes each read can see, along SSA and through PERFORMs, never into another
 * statement's write, since what a MOVE copies is a new definition. A range's exit is read
 * once for every PERFORM of it, so what the range passes through comes back only to the
 * PERFORM that brought it in. And which reads can see storage as it was before any
 * statement ran: along SSA from the start, and past each PERFORM whose range has a path
 * that leaves the bytes alone, which holds of the range wherever it is called from.
 */

import cobol.DataFlow

private predicate atNode(DataFlow::Node n) {
  exists(n.getCfgNode().getGraphNode()) and not n.getCfgNode() instanceof PerformCall
}

/** The SSA definition that the read of `a` at `r` sees. */
private Ssa::Definition seen(CfgNode r, Atom a) {
  exists(Cfg::BasicBlock bb, int i |
    Ssa::ssaDefReachesRead(a, result, bb, i) and r = bb.getNode(i) and nodeReads(r, a)
  )
}

/** The write of `a` at `n`, in its own scope, can be the write at `w`. */
private predicate writeIn(CfgNode n, Atom a, GraphNode w) {
  nodeWrites(n, a, _) and
  not n instanceof PerformCall and
  w = n.getGraphNode()
  or
  exists(PerformCall c | c = n |
    readIn(any(CfgNode x | x.isExit() and x.getScope() = c.getCallee()), a, w)
    or
    through(c.getCallee(), a) and readIn(c, a, w)
  )
}

/** The write of `a` at `n` can leave `a` as it was where its scope began. */
private predicate writeFromEntry(CfgNode n, Atom a) {
  n.isEntry() and nodeWrites(n, a, _)
  or
  exists(PerformCall c | c = n | through(c.getCallee(), a) and readFromEntry(c, a))
}

/** The SSA definition `d` can hold the write at `w`, made in its own scope or a range it performs. */
private predicate defIn(Ssa::Definition d, GraphNode w) {
  defIn(any(Ssa::Definition i | Ssa::phiHasInputFromBlock(d, i, _)), w)
  or
  defIn(any(Ssa::Definition i | Ssa::uncertainWriteDefinitionInput(d, i)), w)
  or
  not d instanceof Ssa::PhiNode and
  exists(Cfg::BasicBlock bb, int i, Atom a | d.definesAt(a, bb, i) | writeIn(bb.getNode(i), a, w))
}

/** The SSA definition `d` can hold what its atom held where its scope began. */
private predicate defFromEntry(Ssa::Definition d) {
  defFromEntry(any(Ssa::Definition i | Ssa::phiHasInputFromBlock(d, i, _)))
  or
  defFromEntry(any(Ssa::Definition i | Ssa::uncertainWriteDefinitionInput(d, i)))
  or
  not d instanceof Ssa::PhiNode and
  exists(Cfg::BasicBlock bb, int i, Atom a | d.definesAt(a, bb, i) |
    writeFromEntry(bb.getNode(i), a)
  )
}

/** The read of `a` at `r` can see the write at `w`, made in its own scope or a range it performs. */
private predicate readIn(CfgNode r, Atom a, GraphNode w) { defIn(seen(r, a), w) }

/** The read of `a` at `r` can see `a` as it was where its scope began. */
private predicate readFromEntry(CfgNode r, Atom a) { defFromEntry(seen(r, a)) }

/** Some path through the range `sc` leaves `a` as it was when the range was performed. */
private predicate through(Scope sc, Atom a) {
  readFromEntry(any(CfgNode x | x.isExit() and x.getScope() = sc), a)
}

/** The read of `a` at `r` can see the write at `w`, made anywhere a PERFORM of its scope comes from. */
private predicate reads(CfgNode r, Atom a, GraphNode w) {
  readIn(r, a, w)
  or
  readFromEntry(r, a) and
  exists(PerformCall c | c.getCallee() = r.getScope() and reads(c, a, w))
}

/** The write at `writer` can be what the read of `a` at `at` sees. */
predicate definer(GraphNode at, Atom a, GraphNode writer) {
  exists(CfgNode r | at = r.getGraphNode() and not r instanceof PerformCall | reads(r, a, writer))
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
