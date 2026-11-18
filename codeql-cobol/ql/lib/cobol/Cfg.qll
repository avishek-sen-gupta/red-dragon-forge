/**
 * The control-flow graph over the generated syntax tree.
 *
 * Every PERFORM range is a scope of its own, holding a copy of each statement it can
 * reach. The end of the range's last unit is that scope's exit; the end of any other
 * unit falls through to the next one. The main scope starts at the first unit and has
 * no exit but the end of the program. So a paragraph that is both performed and
 * reached by GO TO or fall-through returns in the first case and falls through in the
 * second. Ranges are assumed well nested: only a scope's own range end returns.
 */

private import codeql.controlflow.SuccessorType
private import codeql.controlflow.BasicBlock as BB
import cobol.Ast

private newtype TPoint =
  TStmtPoint(Stmt s) or
  TEndPoint(ProcedureUnit p)

/** A statement, or the end of a paragraph. */
class Point extends TPoint {
  Stmt asStmt() { this = TStmtPoint(result) }

  ProcedureUnit asEnd() { this = TEndPoint(result) }

  string toString() {
    result = this.asStmt().toString()
    or
    result = "end of " + this.asEnd().getName()
  }

  Location getLocation() {
    result = this.asStmt().getLocation() or result = this.asEnd().getLocation()
  }
}

Point entryOf(ProcedureUnit p) {
  result = TStmtPoint(p.getStmt(0))
  or
  not exists(p.getStmt(0)) and result = TEndPoint(p)
}

/** Where control goes when `s` completes normally. */
Point after(Stmt s) {
  exists(@cobol_body p, int slot, int i | inBody(s, p, slot, i) |
    exists(Stmt n | inBody(n, p, slot, i + 1) and result = TStmtPoint(n))
    or
    not inBody(_, p, slot, i + 1) and
    (
      result = TEndPoint(p.(ProcedureUnit))
      or
      p instanceof Generated::IfStatement and result = after(p)
      or
      isInlinePerform(p) and result = TStmtPoint(p)
    )
  )
}

predicate isInlinePerform(Stmt s) { exists(s.(Generated::PerformStatement).getChildren(0)) }

private predicate isOutOfLinePerform(Stmt s) {
  s instanceof Generated::PerformStatement and not isInlinePerform(s)
}

/** A unit a GO TO can jump to: its target, or any of a DEPENDING ON's. */
ProcedureUnit gotoTarget(Stmt s) {
  exists(Generated::GotoStatementFormType form, Generated::ProcedureRef r |
    form = s.(Generated::GotoStatement).getForm() and
    (r = form.(Generated::SimpleGoto).getTarget() or r = form.(Generated::ComputedGoto).getTargets(_)) and
    procedure_unit(r, result)
  )
}

private Point bodyEntry(Stmt s, int slot) {
  result = TStmtPoint(s.getChild(slot, 0))
  or
  slot in [1, 2] and not exists(s.getChild(slot, 0)) and result = after(s)
}

/** Successors of a statement that do not depend on the scope. */
private predicate stmtSucc(Stmt s, Point q) {
  s instanceof Generated::IfStatement and (q = bodyEntry(s, 1) or q = bodyEntry(s, 2))
  or
  isInlinePerform(s) and (q = bodyEntry(s, 1) or q = after(s))
  or
  q = entryOf(gotoTarget(s))
  or
  isOutOfLinePerform(s) and
  (q = after(s) or exists(s.(Generated::PerformStatement).getSpec()) and q = TStmtPoint(s))
  or
  not s instanceof Generated::PerformStatement and
  not s instanceof Generated::GotoStatement and
  not s instanceof Generated::IfStatement and
  not s instanceof Generated::StopRunStatement and
  not s instanceof Generated::GobackStatement and
  q = after(s)
}

private newtype TScope =
  TMain(Program p) or
  TRange(ProcedureUnit first, ProcedureUnit last) { perform_range(_, first, last) }

/** The main line of a program, or one PERFORM range. */
class Scope extends TScope {
  Program getProgram() {
    this = TMain(result) or this = TRange(any(ProcedureUnit f | f.getProgram() = result), _)
  }

  ProcedureUnit getFirst() {
    this = TMain(result.getProgram()) and result.getIndex() = 0
    or
    this = TRange(result, _)
  }

  predicate exitsAt(ProcedureUnit p) { this = TRange(_, p) }

  string toString() {
    exists(Program p | this = TMain(p) and result = p.getName())
    or
    exists(ProcedureUnit f, ProcedureUnit l | this = TRange(f, l) |
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
  exists(ProcedureUnit para |
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
      exists(ProcedureUnit para | this = TPointNode(sc, TEndPoint(para)) |
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
    exists(ProcedureUnit f, ProcedureUnit l |
      perform_range(this.getStmt(), f, l) and callee = TRange(f, l)
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
