/** The extracted COBOL facts as classes. */

class File extends @file {
  string getAbsolutePath() { files(this, result) }

  string toString() { result = this.getAbsolutePath() }
}

class Location extends @location_default {
  File getFile() { locations_default(this, result, _, _, _, _) }

  int getStartLine() { locations_default(this, _, result, _, _, _) }

  int getStartColumn() { locations_default(this, _, _, result, _, _) }

  int getEndLine() { locations_default(this, _, _, _, result, _) }

  int getEndColumn() { locations_default(this, _, _, _, _, result) }

  string toString() { result = "line " + this.getStartLine() }

  predicate hasLocationInfo(string fp, int sl, int sc, int el, int ec) {
    fp = this.getFile().getAbsolutePath() and
    sl = this.getStartLine() and
    sc = this.getStartColumn() and
    el = this.getEndLine() and
    ec = this.getEndColumn()
  }
}

class Program extends @program {
  string getName() { programs(this, result, _) }

  Location getLocation() { programs(this, _, result) }

  string toString() { result = this.getName() }
}

class Paragraph extends @paragraph {
  Program getProgram() { paragraphs(this, result, _, _, _, _) }

  string getName() { paragraphs(this, _, result, _, _, _) }

  int getIndex() { paragraphs(this, _, _, _, result, _) }

  Location getLocation() { paragraphs(this, _, _, _, _, result) }

  string toString() { result = this.getName() }

  Paragraph getNext() {
    result.getProgram() = this.getProgram() and result.getIndex() = this.getIndex() + 1
  }

  Stmt getStmt(int i) { stmts(result, _, this, 0, i, _) }
}

class Stmt extends @stmt {
  int getKind() { stmts(this, result, _, _, _, _) }

  predicate hasParent(@stmt_parent p, int slot, int i) { stmts(this, _, p, slot, i, _) }

  Stmt getChild(int slot, int i) { result.hasParent(this, slot, i) }

  Location getLocation() { stmts(this, _, _, _, _, result) }

  Field getARead() { stmt_reads(this, result) }

  Field getAWrite() { stmt_writes(this, result) }

  predicate isPartial(Field f) { partial_accesses(this, f) }

  string getKindName() {
    exists(int k | k = this.getKind() |
      k = 0 and result = "stmt"
      or
      k = 1 and result = "MOVE"
      or
      k = 2 and result = "ACCEPT"
      or
      k = 3 and result = "DISPLAY"
      or
      k = 4 and result = "PERFORM"
      or
      k = 5 and result = "GO TO"
      or
      k = 6 and result = "IF"
      or
      k = 7 and result = "STOP RUN"
      or
      k = 8 and result = "GOBACK"
      or
      k = 9 and result = "PERFORM (inline)"
    )
  }

  string toString() { result = this.getKindName() + " (" + this.getLocation() + ")" }
}

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
