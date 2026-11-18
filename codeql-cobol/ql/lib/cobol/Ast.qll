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

  Field getARead() { result = this.aRead().getACell() or transfer(this, result, _) }

  Field getAWrite() { result = this.aWrite().getACell() or transfer(this, _, result) }

  /**
   * `f` is read or written through a reference modification or a subscript, or written
   * by a verb that may leave some of its bytes as they were.
   */
  predicate isPartial(Field f) {
    exists(Operand o | o = this.aRead() or o = this.aWrite() |
      o.isPartial() and f = o.getACell()
    )
    or
    (
      this instanceof Generated::StringStatement or
      this instanceof Generated::InspectStatement or
      this instanceof Generated::UnstringStatement
    ) and
    transfer(this, _, f)
  }

  /** A MOVE, or the move a WRITE, REWRITE or RELEASE FROM makes: byte k lands at byte k. */
  predicate copies() {
    this instanceof Generated::MoveStatement or
    exists(this.(Generated::WriteStatement).getFromField()) or
    exists(this.(Generated::RewriteStatement).getFromField()) or
    exists(this.(Generated::ReleaseStatement).getFromField())
  }
}

/** How cobble's node ids name a statement list: IF's as THEN and ELSE, an inline PERFORM's as its body, any other by its field. */
private string clause(Stmt parent, string field) {
  Generated::childOf(parent, field, _, _) and
  if parent instanceof Generated::IfStatement and field = "children"
  then result = "then"
  else
    if parent instanceof Generated::IfStatement and field = "else_children"
    then result = "else"
    else
      if parent instanceof Generated::PerformStatement and field = "children"
      then result = "body"
      else result = field
}

/** A branch of an EVALUATE or a SEARCH: its statements are numbered within `.when.<position>`. */
private predicate branch(Stmt owner, int position, Generated::AstNode branch) {
  Generated::childOf(owner.(Generated::EvaluateStatement), "children", position, branch)
  or
  Generated::childOf(owner.(Generated::SearchStatement), "whens", position, branch)
}

/** cobble's id for a statement: its unit's name, then its position in each list holding it. */
string stmtPath(Stmt s) {
  exists(ProcedureUnit u, int i | s = u.getStmt(i) | result = u.getName() + "/" + i)
  or
  exists(Stmt owner, int position, Generated::AstNode b, int i |
    branch(owner, position, b) and Generated::childOf(b, "children", i, s)
  |
    result = stmtPath(owner) + ".when." + position + "." + i
  )
  or
  exists(Stmt owner, string field, int i |
    Generated::childOf(owner, field, i, s) and
    not owner instanceof Generated::EvaluateStatement and
    not branch(_, _, owner)
  |
    result = stmtPath(owner) + "." + clause(owner, field) + "." + i
  )
}

/** `n`, and every node below it. */
private Generated::AstNode within(Generated::AstNode n) {
  result = n
  or
  Generated::childOf(within(n), _, _, result)
}

/** The cells an operand node names. */
Field cellsOf(Generated::AstNode operand) { names_cell(operand, result) }

/**
 * The cells an expression reads: every data name anywhere in it, subscripts and
 * reference-modification bounds included, as cobble's dataflow reads an expression.
 */
Field expressionReads(Generated::AstNode expression) {
  exists(Generated::AstNode r |
    r = within(expression) and
    (r instanceof Generated::FieldRefNode or r instanceof Generated::RefModNode) and
    names_cell(r, result)
  )
}

private Field moveSource(Generated::MoveStatement m) {
  result = cellsOf(m.getSource())
  or
  result = expressionReads(m.getSource().(Generated::FunctionCallOperand))
}

private Field stringSending(Generated::StringSending sending) {
  if exists(sending.getFunction())
  then result = expressionReads(sending.getFunction())
  else result = cellsOf(sending.getValue())
}

private Field inspectPattern(Generated::InspectStatement i) {
  result = cellsOf(i.getTallyingGroups(_).getPatterns(_).getPattern())
  or
  result = cellsOf(i.getReplacings(_).getFromPattern())
  or
  result = cellsOf(i.getReplacings(_).getToPattern())
  or
  result = cellsOf(i.getConvertingFrom())
  or
  result = cellsOf(i.getConvertingTo())
}

private Field inspectWrite(Generated::InspectStatement i) {
  result = cellsOf(i.getTallyingGroups(_).getTarget())
  or
  (exists(i.getReplacings(_)) or i.getInspectType() = "CONVERTING") and
  result = cellsOf(i.getSource())
}

private Field unstringWrite(Generated::UnstringStatement u) {
  result = cellsOf(u.getInto(_).getTarget())
  or
  result = cellsOf(u.getInto(_).getDelimiterIn())
  or
  result = cellsOf(u.getInto(_).getCountIn())
  or
  result = cellsOf(u.getTallyingTarget())
  or
  result = cellsOf(u.getPointer())
}

/** A record a WRITE, REWRITE or RELEASE moves its FROM field into first. */
private predicate recordFrom(Stmt s, Field src, Field dst) {
  exists(Generated::RefModOperand sending |
    sending = s.(Generated::WriteStatement).getFromField() or
    sending = s.(Generated::RewriteStatement).getFromField() or
    sending = s.(Generated::ReleaseStatement).getFromField()
  |
    src = cellsOf(sending) and field_names_cell(s, "record_name", dst)
  )
}

/**
 * `s` builds bytes of `dst` from `src`: a MOVE copies them, the other verbs build the
 * target from every source. The sources and targets are those cobble's fixpoint reads
 * each verb as.
 */
predicate transfer(Stmt s, Field src, Field dst) {
  src = moveSource(s) and dst = cellsOf(s.(Generated::MoveStatement).getTargets(_))
  or
  exists(Generated::ArithmeticStatement a | a = s |
    (src = cellsOf(a.getOperands(_)) or src = cellsOf(a.getTargets(_))) and
    (
      dst = cellsOf(a.getTargets(_)) or
      dst = cellsOf(a.getGiving(_)) or
      dst = cellsOf(a.getRemainder())
    )
  )
  or
  src = expressionReads(s.(Generated::ComputeStatement).getExpression()) and
  dst = cellsOf(s.(Generated::ComputeStatement).getTargets(_))
  or
  src = stringSending(s.(Generated::StringStatement).getSendings(_)) and
  dst = cellsOf(s.(Generated::StringStatement).getInto())
  or
  recordFrom(s, src, dst)
  or
  exists(Generated::InspectStatement i | i = s |
    (src = cellsOf(i.getSource()) or src = inspectPattern(i)) and dst = inspectWrite(i)
  )
  or
  src = cellsOf(s.(Generated::UnstringStatement).getSource()) and dst = unstringWrite(s)
  or
  exists(Generated::SetStatement set, Generated::SetOperand value | set = s |
    value = set.getValues(_) and
    value.getKind() in ["ref", "address_of"] and
    src = cellsOf(value) and
    dst = cellsOf(set.getTargets(_))
  )
  or
  src = cellsOf(s.(Generated::SearchStatement).getTable()) and
  dst = cellsOf(s.(Generated::SearchStatement).getVarying())
  or
  src = cellsOf(s.(Generated::MoveCorrespondingStatement).getSource()) and
  dst = cellsOf(s.(Generated::MoveCorrespondingStatement).getTargets(_))
  or
  src = cellsOf(s.(Generated::ArithmeticCorrespondingStatement).getSource()) and
  dst = cellsOf(s.(Generated::ArithmeticCorrespondingStatement).getTarget())
  or
  field_names_cell(s.(Generated::XmlGenerateStatement), "from_record", src) and
  (field_names_cell(s, "xml_document", dst) or field_names_cell(s, "count_in", dst))
}

/** A PERFORM VARYING's loop counter and its spec, with the suffix cobble names the spec's sites by: none for the outer loop, `.after.<i>` for an AFTER. */
private predicate varying(Generated::PerformStatement p, Generated::PerformVaryingSpec spec, string at) {
  spec = p.getSpec() and at = ""
  or
  exists(int i | spec = p.getSpec().(Generated::PerformVaryingSpec).getAfterSpecs(i) |
    at = ".after." + i
  )
}

/**
 * The transfers of a PERFORM VARYING's own sites: `#init` moves FROM into the counter,
 * `#step` adds BY to it.
 */
predicate loopTransfer(Stmt s, string site, Field src, Field dst) {
  exists(Generated::PerformVaryingSpec spec, string at, Field counter |
    varying(s, spec, at) and counter = cellsOf(spec.getVaryingVar()) and dst = counter
  |
    site = at + "#init" and src = cellsOf(spec.getVaryingFrom().(Generated::FieldRefNode))
    or
    site = at + "#step" and
    (src = cellsOf(spec.getVaryingBy().(Generated::FieldRefNode)) or src = counter)
  )
}

/** The unit a statement is written in, however deeply it is nested. */
ProcedureUnit unitOf(Stmt s) {
  s = result.getStmt(_)
  or
  exists(Generated::AstNode owner | Generated::childOf(owner, _, _, s) |
    result = unitOf(owner) or result = unitOf(any(Stmt o | Generated::childOf(o, _, _, owner)))
  )
}
