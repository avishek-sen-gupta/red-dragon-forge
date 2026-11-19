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

/** A data name, and the storage it may touch only part of. */
private class Operand extends Generated::RefModOperand {
  Field getACell() { names_cell(this, result) }

  predicate isPartial() { names_clamped(this) or names_slice(this, _, _, _) }
}

/** A node of `s` itself: its operands and expressions, not the statements nested in its clauses. */
Generated::AstNode ownNode(Stmt s) {
  Generated::childOf(s, _, _, result) and not result instanceof Generated::Statement
  or
  Generated::childOf(ownNode(s), _, _, result) and not result instanceof Generated::Statement
}

/** `s` reaches `f` through a name located only approximately: a computed subscript or bound. */
predicate clampedAccess(Stmt s, Field f) {
  exists(Generated::AstNode o | o = ownNode(s) | names_cell(o, f) and names_clamped(o))
}

/** `s` reaches only bytes `lo` up to `hi` of `f`'s record through a constant slice of it. */
predicate slicedAccess(Stmt s, Field f, int lo, int hi) {
  exists(Generated::AstNode o, int offset, int length |
    o = ownNode(s) and names_slice(o, f, offset, length)
  |
    lo = f.getStart() + offset and hi = lo + length
  )
}

class Stmt extends Generated::Statement {
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

  /** `f` is reached through a slice of it or through a name located only approximately. */
  predicate isPartial(Field f) { clampedAccess(this, f) or slicedAccess(this, f, _, _) }

  /**
   * A verb cobble's fixpoint has no transfer for: its writes are weak, keeping what the
   * target held before as a possible definition.
   */
  predicate isWeak() {
    this instanceof Generated::InspectStatement or
    this instanceof Generated::UnstringStatement or
    this instanceof Generated::SetStatement and not condition_set_cell(this, _) or
    this instanceof Generated::SearchStatement or
    this instanceof Generated::MoveCorrespondingStatement or
    this instanceof Generated::ArithmeticCorrespondingStatement or
    this instanceof Generated::XmlGenerateStatement or
    this instanceof Generated::AcceptStatement
  }

  /** A MOVE, or the move a WRITE, REWRITE or RELEASE FROM makes: byte k lands at byte k. */
  predicate copies() {
    this instanceof Generated::MoveStatement or
    exists(this.(Generated::WriteStatement).getFromField()) or
    exists(this.(Generated::RewriteStatement).getFromField()) or
    exists(this.(Generated::ReleaseStatement).getFromField())
  }
}

/** cobble's id for a statement. */
string stmtPath(Stmt s) { statement_ids(s, result) }

/** `n`, and every node below it. */
Generated::AstNode within(Generated::AstNode n) {
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

/** An operand the program writes as a literal or a figurative constant. */
private predicate isLiteral(Generated::RefModOperand o) {
  o.getKind() in ["lit", "figurative", "all_literal"]
}

/** A verb that builds its target from every source reads a literal among them. */
private predicate readsLiteral(Stmt s) {
  exists(Generated::ArithmeticStatement a | a = s |
    isLiteral(a.getOperands(_)) or isLiteral(a.getTargets(_))
  )
  or
  exists(within(s.(Generated::ComputeStatement).getExpression()).(Generated::LiteralNode))
  or
  isLiteral(s.(Generated::StringStatement).getSendings(_).getValue())
}

private Field unionTarget(Stmt s) {
  result = cellsOf(s.(Generated::ArithmeticStatement).getTargets(_)) or
  result = cellsOf(s.(Generated::ArithmeticStatement).getGiving(_)) or
  result = cellsOf(s.(Generated::ArithmeticStatement).getRemainder()) or
  result = cellsOf(s.(Generated::ComputeStatement).getTargets(_)) or
  result = cellsOf(s.(Generated::StringStatement).getInto())
}

/** The CICS option `name` of `s`. */
private Generated::CicsOperand option(Generated::ExecCicsStatement s, string name) {
  exists(int i | s.getOptionsKey(i) = name and result = s.getOptions(i))
}

private predicate cicsCall(Generated::ExecCicsStatement s, string origin) {
  s.getVerb() in ["LINK", "XCTL"] and
  if option(s, "PROGRAM").getIsLiteral() = true then origin = "CALL" else origin = "DYNAMIC_CALL"
}

/** The cells an EXEC CICS command receives into, and the origin it credits them to. */
private predicate cicsReceived(Generated::ExecCicsStatement s, string origin, Field dst) {
  cicsCall(s, origin) and dst = cellsOf(option(s, "COMMAREA"))
  or
  s.getVerb() in ["ASKTIME", "ASSIGN"] and origin = "CICS_STATE" and dst = cellsOf(s.getOptions(_))
  or
  not s.getVerb() in ["LINK", "XCTL", "ASKTIME", "ASSIGN"] and
  (
    if s.getVerb() in ["READ", "READNEXT", "READPREV"]
    then origin = "FILE"
    else
      if s.getVerb() = "RECEIVE MAP" then origin = "MAP" else origin = "CICS_STATE"
  ) and
  (
    dst = cellsOf(option(s, "INTO"))
    or
    not exists(option(s, "INTO")) and dst = cellsOf(option(s, "SET"))
    or
    not exists(option(s, "INTO")) and
    not exists(option(s, "SET")) and
    field_names_cell(s, "map_input", dst)
  )
}

/** A CALL's argument the callee can write back through: BY REFERENCE, not omitted, not a literal. */
private Generated::CallUsingParam byReference(Generated::CallStatement c) {
  result = c.getUsing(_) and
  result.getParamType().toUpperCase() = "REFERENCE" and
  result.getOmitted() = false and
  result.getIsLiteral() = false
}

/**
 * `s` writes `dst` from outside the program's storage: `origin` is the kind cobble's
 * fixpoint credits it to (LITERAL, UNKNOWN_FIELD, FUNCTION, FILE, MAP, CICS_STATE, CALL,
 * DYNAMIC_CALL, UNMODELLED). LENGTH OF is a constant, so a LITERAL.
 */
predicate originWrite(Stmt s, string origin, Field dst) {
  exists(Generated::MoveStatement m | m = s and dst = cellsOf(m.getTargets(_)) |
    (isLiteral(m.getSource()) or m.getSource().(Generated::RefModOperand).getKind() = "length_of") and
    origin = "LITERAL"
    or
    m.getSource().(Generated::RefModOperand).getKind() = "ref" and
    not exists(cellsOf(m.getSource())) and
    origin = "UNKNOWN_FIELD"
    or
    m.getSource() instanceof Generated::FunctionCallOperand and
    not exists(moveSource(m)) and
    origin = "FUNCTION"
  )
  or
  readsLiteral(s) and origin = "LITERAL" and dst = unionTarget(s)
  or
  origin = "LITERAL" and initialized_cell(s, dst)
  or
  origin = "LITERAL" and condition_set_cell(s, dst)
  or
  origin = "FILE" and (dst = cellsOf(s.(Generated::ReadStatement).getInto()) or file_record_cell(s, dst))
  or
  exists(Generated::CallStatement c | c = s |
    (dst = cellsOf(byReference(c)) or dst = cellsOf(c.getGiving())) and
    if exists(c.getTarget().getIdentifier()) then origin = "DYNAMIC_CALL" else origin = "CALL"
  )
  or
  cicsReceived(s, origin, dst)
  or
  origin = "CICS_STATE" and
  (dst = cellsOf(option(s, "RESP")) or dst = cellsOf(option(s, "RESP2")))
  or
  origin = "UNMODELLED" and dst = cellsOf(s.(Generated::AcceptStatement).getTarget())
}

/** The origin writes of a PERFORM VARYING's own sites: a literal FROM or BY. */
predicate loopOriginWrite(Stmt s, string site, string origin, Field dst) {
  exists(Generated::PerformVaryingSpec spec, string at |
    varying(s, spec, at) and dst = cellsOf(spec.getVaryingVar()) and origin = "LITERAL"
  |
    site = at + "#init" and not spec.getVaryingFrom() instanceof Generated::FieldRefNode
    or
    site = at + "#step" and not spec.getVaryingBy() instanceof Generated::FieldRefNode
  )
}

/** A CICS command names `option`. */
private predicate hasOption(Generated::ExecCicsStatement s, string option) { s.getOptionsKey(_) = option }

/** The cells a CICS command sends from: its FROM, or for a SEND MAP without one the map's output record. */
private Field cicsSent(Generated::ExecCicsStatement s) {
  result = cellsOf(option(s, "FROM"))
  or
  s.getVerb() = "SEND MAP" and not hasOption(s, "FROM") and field_names_cell(s, "map_output", result)
}

/**
 * `s` sends the bytes of `f` out of the program, to a sink of `kind`: a file (WRITE,
 * REWRITE), a map (SEND MAP, unless MAPONLY), a queue (WRITEQ TS or TD) or a
 * transaction (START), as cobble's fixpoint reads each verb.
 */
predicate sink(Stmt s, string kind, Field f) {
  (s instanceof Generated::WriteStatement or s instanceof Generated::RewriteStatement) and
  kind = "FILE" and
  field_names_cell(s, "record_name", f)
  or
  exists(Generated::ExecCicsStatement c, string verb | c = s and verb = c.getVerb() |
    verb in ["WRITE", "REWRITE"] and kind = "FILE" and f = cellsOf(option(c, "FROM"))
    or
    verb = "SEND MAP" and not hasOption(c, "MAPONLY") and kind = "MAP" and f = cicsSent(c)
    or
    verb = "WRITEQ TS" and kind = "TS_QUEUE" and f = cellsOf(option(c, "FROM"))
    or
    verb = "WRITEQ TD" and kind = "TD_QUEUE" and f = cellsOf(option(c, "FROM"))
    or
    verb = "START" and kind = "TRANSID" and f = cellsOf(option(c, "FROM"))
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

/**
 * `s` moves control or data to another program, as cobble's jumps read it: `kind` is
 * CALL, LINK, XCTL, RETURN_TRANSID, START, RETRIEVE or EXIT, and `returns` says whether
 * control comes back.
 */
predicate jump(Stmt s, string kind, boolean returns) {
  s instanceof Generated::CallStatement and kind = "CALL" and returns = true
  or
  exists(Generated::ExecCicsStatement c, string verb | c = s and verb = c.getVerb() |
    verb = "LINK" and exists(option(c, "PROGRAM")) and kind = verb and returns = true
    or
    verb = "XCTL" and exists(option(c, "PROGRAM")) and kind = verb and returns = false
    or
    verb = "RETURN" and
    returns = false and
    if hasOption(c, "TRANSID") then kind = "RETURN_TRANSID" else kind = "EXIT"
    or
    verb = ["START", "RETRIEVE"] and kind = verb and returns = false
  )
  or
  (
    s instanceof Generated::GobackStatement or
    s instanceof Generated::ExitProgramStatement or
    s instanceof Generated::StopRunStatement
  ) and
  kind = "EXIT" and
  returns = false
}

/** The program `s` goes to, named by a literal. */
predicate jumpTargetName(Stmt s, string name) {
  name = s.(Generated::CallStatement).getTarget().getLiteral()
  or
  exists(Generated::CicsOperand o | jump(s, ["LINK", "XCTL"], _) and o = option(s, "PROGRAM") |
    o.getIsLiteral() = true and name = o.getText().regexpReplaceAll("^['\"]+|['\"]+$", "")
  )
}

/** Bytes `lo` up to `hi` of `f` hold the name of the program `s` goes to. */
predicate jumpTarget(Stmt s, Field f, int lo, int hi) {
  exists(Generated::AstNode o |
    o = s.(Generated::CallStatement).getTarget().getIdentifier()
    or
    jump(s, ["LINK", "XCTL"], _) and o = option(s, "PROGRAM")
  |
    names_cell(o, f) and
    if names_slice(o, f, _, _)
    then
      exists(int offset, int length | names_slice(o, f, offset, length) |
        lo = f.getStart() + offset and hi = lo + length
      )
    else (
      lo = f.getStart() and hi = f.getEnd()
    )
  )
}

/** The transaction `s` starts, named by a literal, quotes and all. */
predicate jumpTransidText(Stmt s, string text) {
  exists(Generated::CicsOperand o |
    jump(s, ["RETURN_TRANSID", "START"], _) and o = option(s, "TRANSID")
  |
    o.getIsLiteral() = true and text = o.getText()
  )
}

/** `f` holds the name of the transaction `s` starts. */
predicate jumpTransid(Stmt s, Field f) {
  jump(s, ["RETURN_TRANSID", "START"], _) and names_area(option(s, "TRANSID"), f)
}

private string areaOption(string kind) {
  kind = ["LINK", "XCTL", "RETURN_TRANSID"] and result = "COMMAREA"
  or
  kind = "START" and result = "FROM"
  or
  kind = "RETRIEVE" and result = "INTO"
}

/** `s` hands `area` to another program as its parameter `param`. */
predicate jumpArea(Stmt s, int param, Field area) {
  names_area(s.(Generated::CallStatement).getUsing(param), area)
  or
  exists(string kind | jump(s, kind, _) | param = 0 and names_area(option(s, areaOption(kind)), area))
}

private predicate inside(Field area, Field f) {
  f.getProgram() = area.getProgram() and
  f.getRecord() = area.getRecord() and
  area.getStart() <= f.getStart() and
  f.getEnd() <= area.getEnd()
}

/** `f` is one of the cells an area is handed over as: each elementary cell inside it, or the area itself when it is elementary. */
bindingset[area]
predicate areaField(Field area, Field f) {
  inside(area, f) and not group_field(f)
  or
  f = area and not exists(Field e | inside(area, e) and not group_field(e))
}

