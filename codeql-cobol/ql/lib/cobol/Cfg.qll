/**
 * The control-flow graph cobble's fixpoint walks, as cobble writes it, split into
 * scopes.
 *
 * Every PERFORM range is a scope of its own, holding a copy of each node it can reach
 * from its first node along every edge but PERFORM and RETURN. The range's last node is
 * that scope's exit; reaching the end of any other range falls through, as the edges
 * say. The main scope starts at the program's entry. A PERFORM is a call into its
 * range's scope, and control in the caller continues where the call resumes, once some
 * path through the range reaches its end: a range that only ever leaves the program,
 * through CICS RETURN or XCTL, does not come back.
 * Ranges are assumed well nested: only a scope's own range end returns.
 */

private import codeql.controlflow.SuccessorType
private import codeql.controlflow.BasicBlock as BB
import cobol.Ast

/** A node of cobble's graph. */
class GraphNode extends @cfg_node {
  Program getProgram() { cfg_nodes(this, result, _, _, _) }

  /** cobble's id for the node. */
  string getId() { cfg_nodes(this, _, result, _, _) }

  string getKind() { cfg_nodes(this, _, _, result, _) }

  Location getLocation() { cfg_nodes(this, _, _, _, result) }

  string toString() { result = this.getId() }

  GraphNode getASuccessor(string kind) { cfg_edges(this, result, kind) }

  /** The statement this node lowers. */
  Stmt getStmt() { cfg_statement(this, result) }

  /** The statement this node is a further node of, as `#init` or `#test` is, and the suffix naming it. */
  Stmt getSiteOf(string suffix) { cfg_site(this, result, suffix) }

  /** A node control goes to next along an edge within one scope, PERFORM and RETURN aside. */
  GraphNode getAPlainSuccessor() {
    exists(string kind | result = this.getASuccessor(kind) | not kind in ["PERFORM", "RETURN"])
  }
}

private newtype TScope =
  TMain(Program p) or
  TRange(GraphNode first, GraphNode last) { cfg_call(_, first, last) }

/** The main line of a program, or one PERFORM range. */
class Scope extends TScope {
  Program getProgram() {
    this = TMain(result) or this = TRange(any(GraphNode f | f.getProgram() = result), _)
  }

  GraphNode getFirst() {
    exists(Program p | this = TMain(p) | cfg_entry(p, result))
    or
    this = TRange(result, _)
  }

  predicate exitsAt(GraphNode n) { this = TRange(_, n) }

  predicate isMain() { this = TMain(_) }

  string toString() {
    exists(Program p | this = TMain(p) and result = p.getName())
    or
    exists(GraphNode f, GraphNode l | this = TRange(f, l) |
      result = f.getId() + " THRU " + l.getId()
    )
  }

  Location getLocation() { result = this.getFirst().getLocation() }
}

/** A range some path through reaches its end, so a PERFORM of it comes back. */
private predicate returns(Scope sc) { exists(GraphNode last | sc.exitsAt(last) and reach(sc, last)) }

/** The range a PERFORM at `call` runs. */
private Scope callee(GraphNode call) {
  exists(GraphNode f, GraphNode l | cfg_call(call, f, l) | result = TRange(f, l))
}

/** Where control goes next from `m` within one scope: a PERFORM resumes once a range it runs comes back. */
private GraphNode localSuccessor(GraphNode m) {
  result = m.getAPlainSuccessor()
  or
  cfg_resume(m, result) and returns(callee(m))
}

private predicate reach(Scope sc, GraphNode n) {
  n = sc.getFirst()
  or
  exists(GraphNode m | reach(sc, m) and not sc.exitsAt(m) and n = localSuccessor(m))
}

private newtype TNode =
  TEntryNode(Scope sc) or
  TExitNode(Scope sc) { sc = TRange(_, _) } or
  TGraphNode(Scope sc, GraphNode g) { reach(sc, g) }

class CfgNode extends TNode {
  Scope getScope() {
    this = TEntryNode(result) or this = TExitNode(result) or this = TGraphNode(result, _)
  }

  GraphNode getGraphNode() { this = TGraphNode(_, result) }

  Stmt getStmt() { result = this.getGraphNode().getStmt() }

  predicate isEntry() { this = TEntryNode(_) }

  predicate isExit() { this = TExitNode(_) }

  string toString() {
    this = TEntryNode(_) and result = "entry of " + this.getScope()
    or
    this = TExitNode(_) and result = "exit of " + this.getScope()
    or
    result = this.getGraphNode().toString() + " in " + this.getScope()
  }

  Location getLocation() {
    result = this.getGraphNode().getLocation()
    or
    not exists(this.getGraphNode()) and result = this.getScope().getLocation()
  }

  CfgNode getASuccessor() {
    exists(Scope sc |
      this = TEntryNode(sc) and result = TGraphNode(sc, sc.getFirst())
      or
      exists(GraphNode g | this = TGraphNode(sc, g) |
        sc.exitsAt(g) and result = TExitNode(sc)
        or
        not sc.exitsAt(g) and result = TGraphNode(sc, localSuccessor(g))
      )
    )
  }
}

/** A PERFORM, in one scope's copy of the node. */
class PerformCall extends CfgNode {
  PerformCall() { cfg_call(this.getGraphNode(), _, _) }

  Scope getCallee() { result = callee(this.getGraphNode()) }

  /** Some path through the range reaches its end, so what it leaves comes back here. */
  predicate returns() { returns(this.getCallee()) }
}

private module BbInput implements BB::InputSig<Location> {
  class CfgScope = Scope;

  class Node = CfgNode;

  CfgScope nodeGetCfgScope(Node node) { result = node.getScope() }

  Node nodeGetASuccessor(Node node, SuccessorType t) {
    result = node.getASuccessor() and t instanceof DirectSuccessor
  }

  predicate nodeIsDominanceEntry(Node node) { node.isEntry() }

  predicate nodeIsPostDominanceExit(Node node) { node.isExit() }
}

module Cfg = BB::Make<Location, BbInput>;
