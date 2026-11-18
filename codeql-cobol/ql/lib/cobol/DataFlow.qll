/**
 * Storage atoms, SSA over them, and the input to CodeQL's shared dataflow library.
 *
 * An atom is a maximal byte range of a record that no field boundary splits, so every
 * field is a union of atoms and a whole-field write is a certain write to each of them.
 * A partial access (reference modification, subscript) is an uncertain one. A PERFORM
 * passes every atom of the program in as a parameter and gets every atom back, so the
 * dataflow library can match each range's return to its own call.
 */

private import codeql.ssa.Ssa as SsaImpl
private import codeql.dataflow.DataFlow as SharedDataFlow
private import codeql.util.Unit
import cobol.Cfg

private predicate boundary(Program p, string rec, int b) {
  exists(Field f | f.getProgram() = p and f.getRecord() = rec |
    b = f.getStart() or b = f.getEnd() or slicedAccess(_, f, b, _) or slicedAccess(_, f, _, b)
  )
}

private int boundaryRank(Program p, string rec, int b) {
  b = rank[result](int x | boundary(p, rec, x) | x)
}

private newtype TAtom =
  TAtomC(Program p, string rec, int i) {
    exists(boundaryRank(p, rec, _)) and
    i = [1 .. max(boundaryRank(p, rec, _)) - 1]
  }

class Atom extends TAtom {
  Program getProgram() { this = TAtomC(result, _, _) }

  string getRecord() { this = TAtomC(_, result, _) }

  int getLo() {
    exists(Program p, string rec, int i |
      this = TAtomC(p, rec, i) and i = boundaryRank(p, rec, result)
    )
  }

  int getHi() {
    exists(Program p, string rec, int i |
      this = TAtomC(p, rec, i) and i + 1 = boundaryRank(p, rec, result)
    )
  }

  string toString() { result = this.getRecord() + "[" + this.getLo() + ":" + this.getHi() + ")" }

  Location getLocation() { result = this.getProgram().getLocation() }
}

/** An atom of `f` that `s` reaches: all of them, or those inside a constant slice of it. */
predicate stmtAtom(Stmt s, Field f, Atom a) {
  (f = s.getARead() or f = s.getAWrite() or originWrite(s, _, f) or sink(s, _, f)) and
  fieldAtom(f, a) and
  if slicedAccess(s, f, _, _)
  then exists(int lo, int hi | slicedAccess(s, f, lo, hi) | lo <= a.getLo() and a.getHi() <= hi)
  else any()
}

predicate fieldAtom(Field f, Atom a) {
  exists(Program p, string rec |
    p = f.getProgram() and
    rec = f.getRecord() and
    a = TAtomC(p, rec, [boundaryRank(p, rec, f.getStart()) .. boundaryRank(p, rec, f.getEnd()) - 1])
  )
}

private predicate directAccess(Scope sc, Atom a) {
  exists(CfgNode n, Field f |
    n.getScope() = sc and
    (graphReads(n.getGraphNode(), f) or graphWrites(n.getGraphNode(), f, _)) and
    fieldAtom(f, a)
  )
}

/** The atoms a scope, or any range it performs, reads or writes. */
predicate modRef(Scope sc, Atom a) {
  directAccess(sc, a)
  or
  exists(PerformCall c | c.getScope() = sc and modRef(c.getCallee(), a))
}

/**
 * The cells the node `g` writes, and whether the write is weak: it may leave some of
 * their bytes, or all of them, as they were.
 */
predicate graphWrites(GraphNode g, Field f, boolean weak) {
  exists(Stmt s | s = g.getStmt() |
    (f = s.getAWrite() or originWrite(s, _, f)) and
    if clampedAccess(s, f) or s.isWeak() then weak = true else weak = false
  )
  or
  exists(Stmt s, string site | s = g.getSiteOf(site) |
    (loopTransfer(s, site, _, f) or loopOriginWrite(s, site, _, f)) and weak = false
  )
}

/** The cells the node `g` copies from: the sources of the writes it makes. */
predicate graphCopies(GraphNode g, Field f) {
  transfer(g.getStmt(), f, _)
  or
  exists(Stmt s, string site | s = g.getSiteOf(site) | loopTransfer(s, site, f, _))
}

/** The cells the node `g` reads: what it copies, consults or sends. */
predicate graphReads(GraphNode g, Field f) {
  f = g.getStmt().getARead()
  or
  cfg_consults(g, f)
  or
  sink(g.getStmt(), _, f)
  or
  exists(Stmt s, string site | s = g.getSiteOf(site) | loopTransfer(s, site, f, _))
}

/** An atom of `f` the node `g` reaches. */
private predicate graphAtom(GraphNode g, Field f, Atom a) {
  stmtAtom(g.getStmt(), f, a)
  or
  exists(Stmt s, string site | s = g.getSiteOf(site) |
    (loopTransfer(s, site, f, _) or loopTransfer(s, site, _, f) or loopOriginWrite(s, site, _, f)) and
    fieldAtom(f, a)
  )
  or
  cfg_consults(g, f) and fieldAtom(f, a)
}

predicate nodeWrites(CfgNode n, Atom a, boolean certain) {
  exists(Field f, boolean weak, GraphNode g |
    g = n.getGraphNode() and graphWrites(g, f, weak) and graphAtom(g, f, a)
  |
    certain = weak.booleanNot()
  )
  or
  (
    exists(PerformCall c | c = n and c.returns() | modRef(c.getCallee(), a))
    or
    n.isEntry() and modRef(n.getScope(), a)
  ) and
  certain = true
}

predicate nodeReads(CfgNode n, Atom a) {
  exists(Field f, GraphNode g | g = n.getGraphNode() and graphReads(g, f) and graphAtom(g, f, a))
  or
  (
    modRef(n.(PerformCall).getCallee(), a)
    or
    n.isExit() and modRef(n.getScope(), a)
  )
}

private module SsaInput implements SsaImpl::InputSig<Location, Cfg::BasicBlock> {
  class SourceVariable = Atom;

  predicate variableWrite(Cfg::BasicBlock bb, int i, SourceVariable v, boolean certain) {
    nodeWrites(bb.getNode(i), v, certain)
  }

  predicate variableRead(Cfg::BasicBlock bb, int i, SourceVariable v, boolean certain) {
    nodeReads(bb.getNode(i), v) and certain = true
  }
}

module Ssa = SsaImpl::Make<Location, Cfg, SsaInput>;

/** Bytes `a` of the sending field land in bytes `b` of the receiving field: at the same offset for a copy, anywhere for a target a verb builds. */
private predicate moved(Stmt s, Atom a, Atom b) {
  exists(Field src, Field dst | transfer(s, src, dst) and stmtAtom(s, src, a) and stmtAtom(s, dst, b) |
    not s.copies()
    or
    src.isNumeric()
    or
    dst.isNumeric()
    or
    s.isPartial(src)
    or
    s.isPartial(dst)
    or
    a.getLo() - src.getStart() < b.getHi() - dst.getStart() and
    b.getLo() - dst.getStart() < a.getHi() - src.getStart()
  )
}

private newtype TNode =
  TReadNode(CfgNode n, Atom a) { nodeReads(n, a) } or
  TWriteNode(CfgNode n, Atom a) { nodeWrites(n, a, _) } or
  TSsaNode(Ssa::Definition d) {
    d instanceof Ssa::PhiNode or d instanceof Ssa::UncertainWriteDefinition
  }

module CobolDataFlow implements SharedDataFlow::InputSig<Location> {
  class Node extends TNode {
    CfgNode getCfgNode() { this = TReadNode(result, _) or this = TWriteNode(result, _) }

    predicate isRead() { this = TReadNode(_, _) }

    predicate isWrite() { this = TWriteNode(_, _) }

    Atom getAtom() {
      this = TReadNode(_, result)
      or
      this = TWriteNode(_, result)
      or
      exists(Ssa::Definition d | this = TSsaNode(d) and result = d.getSourceVariable())
    }

    string toString() {
      exists(CfgNode n, Atom a | this = TReadNode(n, a) and result = "read " + a + " at " + n)
      or
      exists(CfgNode n, Atom a | this = TWriteNode(n, a) and result = "write " + a + " at " + n)
      or
      exists(Ssa::Definition d | this = TSsaNode(d) and result = d.toString())
    }

    Location getLocation() {
      result = this.getCfgNode().getLocation()
      or
      exists(Ssa::Definition d | this = TSsaNode(d) and result = d.getBasicBlock().getLocation())
    }
  }

  class ParameterNode extends Node {
    ParameterNode() { this = TWriteNode(any(CfgNode n | n.isEntry()), _) }
  }

  class ArgumentNode extends Node {
    ArgumentNode() { this = TReadNode(any(PerformCall c), _) }
  }

  class ReturnNode extends Node {
    ReturnNode() { this = TReadNode(any(CfgNode n | n.isExit()), _) }

    ReturnKind getKind() { result = this.getAtom() }
  }

  class OutNode extends Node {
    OutNode() { this = TWriteNode(any(PerformCall c), _) }
  }

  class PostUpdateNode extends Node {
    PostUpdateNode() { none() }

    Node getPreUpdateNode() { none() }
  }

  class CastNode extends Node {
    CastNode() { none() }
  }

  predicate isParameterNode(ParameterNode p, DataFlowCallable c, ParameterPosition pos) {
    p = TWriteNode(any(CfgNode n | n.isEntry() and n.getScope() = c), pos)
  }

  predicate isArgumentNode(ArgumentNode n, DataFlowCall call, ArgumentPosition pos) {
    n = TReadNode(call, pos)
  }

  DataFlowCallable nodeGetEnclosingCallable(Node node) {
    result = node.getCfgNode().getScope()
    or
    exists(Ssa::Definition d | node = TSsaNode(d) and result = d.getBasicBlock().getScope())
  }

  DataFlowType getNodeType(Node node) { exists(node) and exists(result) }

  predicate nodeIsHidden(Node node) { node instanceof TSsaNode }

  class DataFlowExpr = Stmt;

  Node exprNode(DataFlowExpr e) { none() }

  class DataFlowCall extends PerformCall {
    DataFlowCallable getEnclosingCallable() { result = this.getScope() }
  }

  class DataFlowCallable = Scope;

  class ReturnKind = Atom;

  DataFlowCallable viableCallable(DataFlowCall c) { result = c.getCallee() }

  OutNode getAnOutNode(DataFlowCall call, ReturnKind kind) { result = TWriteNode(call, kind) }

  class DataFlowType = Unit;

  predicate compatibleTypes(DataFlowType t1, DataFlowType t2) { any() }

  predicate typeStrongerThan(DataFlowType t1, DataFlowType t2) { none() }

  class Content extends Unit {
    Content() { none() }
  }

  predicate forceHighPrecision(Content c) { none() }

  class ContentSet extends Content {
    Content getAStoreContent() { result = this }

    Content getAReadContent() { result = this }
  }

  class ContentApprox = Unit;

  ContentApprox getContentApprox(Content c) { any() }

  class ParameterPosition = Atom;

  class ArgumentPosition = Atom;

  predicate parameterMatch(ParameterPosition ppos, ArgumentPosition apos) { ppos = apos }

  private Node defNode(Ssa::Definition d) {
    result = TSsaNode(d)
    or
    not d instanceof Ssa::PhiNode and
    not d instanceof Ssa::UncertainWriteDefinition and
    exists(Cfg::BasicBlock bb, int i, Atom a |
      d.definesAt(a, bb, i) and result = TWriteNode(bb.getNode(i), a)
    )
  }

  predicate simpleLocalFlowStep(Node node1, Node node2, string model) {
    model = "" and
    (
      exists(Ssa::Definition d, Atom a, Cfg::BasicBlock bb, int i |
        Ssa::ssaDefReachesRead(a, d, bb, i) and
        nodeReads(bb.getNode(i), a) and
        node1 = defNode(d) and
        node2 = TReadNode(bb.getNode(i), a)
      )
      or
      exists(Ssa::PhiNode phi, Ssa::Definition inp |
        Ssa::phiHasInputFromBlock(phi, inp, _) and
        node1 = defNode(inp) and
        node2 = TSsaNode(phi)
      )
      or
      exists(Ssa::UncertainWriteDefinition d |
        node2 = TSsaNode(d) and
        (
          Ssa::uncertainWriteDefinitionInput(d, any(Ssa::Definition p | node1 = defNode(p)))
          or
          exists(Cfg::BasicBlock bb, int i, Atom a |
            d.definesAt(a, bb, i) and node1 = TWriteNode(bb.getNode(i), a)
          )
        )
      )
      or
      exists(CfgNode n, Atom a, Atom b |
        moved(n.getStmt(), a, b) and node1 = TReadNode(n, a) and node2 = TWriteNode(n, b)
      )
    )
  }

  predicate jumpStep(Node node1, Node node2) { none() }

  predicate readStep(Node node1, ContentSet c, Node node2) { none() }

  predicate storeStep(Node node1, ContentSet c, Node node2) { none() }

  predicate clearsContent(Node n, ContentSet c) { none() }

  predicate expectsContent(Node n, ContentSet c) { none() }

  class NodeRegion extends Unit {
    NodeRegion() { none() }

    predicate contains(Node n) { none() }
  }

  predicate isUnreachableInCall(NodeRegion nr, DataFlowCall call) { none() }

  predicate allowParameterReturnInSelf(ParameterNode p) { none() }

  predicate localMustFlowStep(Node node1, Node node2) { none() }

  class LambdaCallKind = Unit;

  predicate lambdaCreation(Node creation, LambdaCallKind kind, DataFlowCallable c) { none() }

  predicate lambdaCall(DataFlowCall call, LambdaCallKind kind, Node receiver) { none() }

  predicate additionalLambdaFlowStep(Node nodeFrom, Node nodeTo, boolean preservesValue) { none() }

  predicate knownSourceModel(Node source, string model) { none() }

  predicate knownSinkModel(Node sink, string model) { none() }

  class DataFlowSecondLevelScope extends Unit {
    DataFlowSecondLevelScope() { none() }
  }
}

module DataFlow {
  import SharedDataFlow::DataFlowMake<Location, CobolDataFlow>
  import CobolDataFlow
}

