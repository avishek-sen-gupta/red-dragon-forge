/**
 * Programs, their storage cells and the units they run, over the generated syntax tree,
 * with the storage each statement reads and writes.
 */

import cobol.Locations
import cobol.ast.internal.Generated

class Program extends @program {
  string getName() { programs(this, result, _) }

  Location getLocation() { programs(this, _, result) }

  string toString() { result = this.getName() }
}

/**
 * A run of statements executed in declaration order: a paragraph, the statements at the
 * head of a section, or those before any section or paragraph (the program itself).
 */
class ProcedureUnit extends @cobol_unit {
  Program getProgram() { units(result, _, this, _, _) }

  int getIndex() { units(_, result, this, _, _) }

  string getName() { units(_, _, this, result, _) }

  /** The unit declared next, which the end of this one falls through to. */
  ProcedureUnit getNext() {
    result.getProgram() = this.getProgram() and result.getIndex() = this.getIndex() + 1
  }

  Stmt getStmt(int i) {
    result = this.(Generated::CobolParagraph).getStatements(i)
    or
    result = this.(Generated::CobolSection).getStatements(i)
    or
    program_statements(this, i, result)
  }

  string toString() { result = this.getName() }

  Location getLocation() {
    result = this.(Generated::AstNode).getLocation()
    or
    result = this.(Program).getLocation()
  }
}

/** One storage cell: an occurrence of a declared item, at its bytes in its record. */
class Field extends @field {
  Program getProgram() { fields(this, result, _, _, _, _, _) }

  string getName() { fields(this, _, result, _, _, _, _) }

  string getRecord() { fields(this, _, _, result, _, _, _) }

  int getStart() { fields(this, _, _, _, result, _, _) }

  int getLength() { fields(this, _, _, _, _, result, _) }

  int getEnd() { result = this.getStart() + this.getLength() }

  predicate isNumeric() { numeric_fields(this) }

  string toString() { result = this.getName() }
}

/** `s` is statement `i` of the list `slot` of `owner`: 0 a unit's body, 1 a THEN or an inline PERFORM's body, 2 an ELSE. */
predicate inBody(Stmt s, @cobol_body owner, int slot, int i) {
  s = owner.(ProcedureUnit).getStmt(i) and slot = 0
  or
  s = owner.(Generated::IfStatement).getChildren(i) and slot = 1
  or
  s = owner.(Generated::IfStatement).getElseChildren(i) and slot = 2
  or
  s = owner.(Generated::PerformStatement).getChildren(i) and slot = 1
}

/** A data name, and the storage it may touch only part of. */
private class Operand extends Generated::RefModOperand {
  Field getACell() { names_cell(this, result) }

  predicate isPartial() { exists(this.getRefModStart()) or exists(this.getSubscripts(_)) }
}

class Stmt extends Generated::Statement {
  Stmt getChild(int slot, int i) { inBody(result, this, slot, i) }

  private Operand aRead() {
    result = this.(Generated::MoveStatement).getSource()
    or
    result = this.(Generated::DisplayStatement).getOperands(_)
  }

  private Operand aWrite() {
    result = this.(Generated::MoveStatement).getTargets(_)
    or
    result = this.(Generated::AcceptStatement).getTarget()
  }

  Field getARead() { result = this.aRead().getACell() }

  Field getAWrite() { result = this.aWrite().getACell() }

  /** `f` is read or written through a reference modification or a subscript. */
  predicate isPartial(Field f) {
    exists(Operand o | o = this.aRead() or o = this.aWrite() |
      o.isPartial() and f = o.getACell()
    )
  }
}
