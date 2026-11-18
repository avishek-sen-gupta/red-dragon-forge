/**
 * The control-flow graph, derived from the paragraph and statement facts.
 *
 * Every PERFORM range is a scope of its own, holding a copy of each statement it can
 * reach. The end of the range's last paragraph is that scope's exit; the end of any
 * other paragraph falls through to the next one. The main scope starts at the first
 * paragraph and has no exit but the end of the program. So a paragraph that is both
 * performed and reached by GO TO or fall-through returns in the first case and falls
 * through in the second. Ranges are assumed well nested: only a scope's own range end
 * returns.
 */

private import codeql.controlflow.SuccessorType
private import codeql.controlflow.BasicBlock as BB
import cobol.Ast

private newtype TPoint =
  TStmtPoint(Stmt s) or
  TEndPoint(Paragraph p)

/** A statement, or the end of a paragraph. */
class Point extends TPoint {
  Stmt asStmt() { this = TStmtPoint(result) }

  Paragraph asEnd() { this = TEndPoint(result) }

  string toString() {
    result = this.asStmt().toString()
    or
    result = "end of " + this.asEnd().getName()
  }

  Location getLocation() {
    result = this.asStmt().getLocation() or result = this.asEnd().getLocation()
  }
}

Point entryOf(Paragraph p) {
  result = TStmtPoint(p.getStmt(0))
  or
  not exists(p.getStmt(0)) and result = TEndPoint(p)
}

/** Where control goes when `s` completes normally. */
Point after(Stmt s) {
  exists(@stmt_parent p, int slot, int i | s.hasParent(p, slot, i) |
    exists(Stmt n | n.hasParent(p, slot, i + 1) and result = TStmtPoint(n))
    or
    not exists(Stmt n | n.hasParent(p, slot, i + 1)) and
    (
      result = TEndPoint(p.(Paragraph))
      or
      p.(Stmt).getKind() = 6 and result = after(p)
      or
      p.(Stmt).getKind() = 9 and result = TStmtPoint(p)
    )
  )
}

private Point bodyEntry(Stmt s, int slot) {
  result = TStmtPoint(s.getChild(slot, 0))
  or
  slot in [1, 2] and not exists(s.getChild(slot, 0)) and result = after(s)
}

/** Successors of a statement that do not depend on the scope. */
private predicate stmtSucc(Stmt s, Point q) {
  s.getKind() = 6 and (q = bodyEntry(s, 1) or q = bodyEntry(s, 2))
  or
  s.getKind() = 9 and (q = bodyEntry(s, 1) or q = after(s))
  or
  s.getKind() = 5 and exists(Paragraph t | goto_targets(s, t) and q = entryOf(t))
  or
  s.getKind() = 4 and (q = after(s) or perform_repeats(s) and q = TStmtPoint(s))
  or
  not s.getKind() in [4, 5, 6, 7, 8, 9] and q = after(s)
}

private newtype TScope =
  TMain(Program p) or
  TRange(Paragraph first, Paragraph last) { perform_ranges(_, first, last) }

/** The main line of a program, or one PERFORM range. */
class Scope extends TScope {
  Program getProgram() {
    this = TMain(result) or this = TRange(any(Paragraph f | f.getProgram() = result), _)
  }

  Paragraph getFirst() {
    this = TMain(result.getProgram()) and result.getIndex() = 0
    or
    this = TRange(result, _)
  }

  predicate exitsAt(Paragraph p) { this = TRange(_, p) }

  string toString() {
    exists(Program p | this = TMain(p) and result = p.getName())
    or
    exists(Paragraph f, Paragraph l | this = TRange(f, l) |
      if f = l then result = f.getName() else result = f.getName() + " THRU " + l.getName()
    )
  }

  Location getLocation() { result = this.getFirst().getLocation() }
}

private predicate reach(Scope sc, Point p) {
  p = entryOf(sc.getFirst())
  or
  exists(Stmt s | reach(sc, TStmtPoint(s)) and stmtSucc(s, p))
  or
  exists(Paragraph para |
    reach(sc, TEndPoint(para)) and not sc.exitsAt(para) and p = entryOf(para.getNext())
  )
}

private newtype TNode =
  TEntryNode(Scope sc) or
  TExitNode(Scope sc) or
  TPointNode(Scope sc, Point p) { reach(sc, p) }

class CfgNode extends TNode {
  Scope getScope() {
    this = TEntryNode(result) or this = TExitNode(result) or this = TPointNode(result, _)
  }

  Point getPoint() { this = TPointNode(_, result) }

  Stmt getStmt() { result = this.getPoint().asStmt() }

  predicate isEntry() { this = TEntryNode(_) }

  predicate isExit() { this = TExitNode(_) }

  string toString() {
    this = TEntryNode(_) and result = "entry of " + this.getScope()
    or
    this = TExitNode(_) and result = "exit of " + this.getScope()
    or
    result = this.getPoint().toString() + " in " + this.getScope()
  }

  Location getLocation() {
    result = this.getPoint().getLocation()
    or
    not exists(this.getPoint()) and result = this.getScope().getLocation()
  }

  CfgNode getASuccessor() {
    exists(Scope sc |
      this = TEntryNode(sc) and result = TPointNode(sc, entryOf(sc.getFirst()))
      or
      exists(Stmt s, Point p |
        this = TPointNode(sc, TStmtPoint(s)) and stmtSucc(s, p) and result = TPointNode(sc, p)
      )
      or
      exists(Paragraph para | this = TPointNode(sc, TEndPoint(para)) |
        sc.exitsAt(para) and result = TExitNode(sc)
        or
        not sc.exitsAt(para) and result = TPointNode(sc, entryOf(para.getNext()))
        or
        not sc.exitsAt(para) and not exists(para.getNext()) and result = TExitNode(sc)
      )
    )
  }
}

/** A PERFORM of a range, in one scope's copy of the statement. */
class PerformCall extends CfgNode {
  Scope callee;

  PerformCall() {
    exists(Paragraph f, Paragraph l |
      perform_ranges(this.getStmt(), f, l) and callee = TRange(f, l)
    )
  }

  Scope getCallee() { result = callee }
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
