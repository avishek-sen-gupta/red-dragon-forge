# CodeQL COBOL: the AST generated from the parser's types

## Intent

COBOL is a CodeQL language whose algorithms (basic blocks, SSA, dataflow) are CodeQL's. The
facts cobble writes are the parser's typed ASG, one table per type, generated from the type
hints, so no extractor code is written or maintained per statement. What a statement means
(where control goes, which operand's bytes reach which) is written in QL over that AST.

Decided by the user: a full syntax tree rather than per-statement access sets; generated, with the
generated schema and QL committed and a test that fails when they are stale; conditions typed in
red-dragon's ASG rather than in cobble (done: red-dragon ADR-200).

## Non-goals

- Generating semantics. Control flow and flow steps stay hand-written QL.
- A second model of the parser: the generator reads red-dragon's, cicada's and squall's types and
  invents none.
- Changing cobble's own analyses: they keep reading the ASG directly.

## The mapping

The roots are every member of `CobolStatementType`, cicada's `ExecCicsStatement`, squall's
`ExecSqlStatement`, and the procedure containers `CobolSection` and `CobolParagraph`. Every
dataclass reachable from them gets a node type `@cobol_<snake name>` and a table
`cobol_<snake name>_def(unique int id, <scalar and single-node columns>)`.

| field type | schema |
|---|---|
| `str`, `int`, `bool`, enum | a column on `_def` (`string`, `int`, `boolean`; an enum as its value string) |
| a dataclass, or a union of them | a column `int f: @<type> ref` |
| `X \| None` | a table `cobol_<t>_<f>(unique int parent, <X>)`: a row when present |
| `list`/`tuple` of anything | a table `cobol_<t>_<f>(int parent, int index, <element>)` |
| a fixed tuple `tuple[A, B]` | a synthetic node with columns `_0`, `_1` |
| `dict[str, X \| None]` | a table `cobol_<t>_<f>(int parent, int index, string entry_key)` and one for present values |
| `SourceSpan` | `@location_default`, in the program's file |

A union gets the name of the module-level alias whose members it is (`CobolStatementType` is
`@cobol_statement`, `ExprNode` `@cobol_expr_node`, `Condition` `@cobol_condition`); one with no
alias is `@cobol_<t>_<f>_type`.

The dbscheme keeps its hand-written part (files, locations, programs, in
`cobble/experimental/codeql/schema/preamble.py`) and the layout facts cobble derives rather than
parses: `fields` (one cell per occurrence and its bytes), `numeric_fields`, and
each cell's qualification path, so QL resolves names the way COBOL does.

## The parts

- `cobble/experimental/codeql/schema/`: the type walk, shared by the generator and the emitter.
- `cobble-experimental-codeql-schema` writes `extractors/cobol/cobol.dbscheme` and
  `ql/lib/cobol/ast/internal/Generated.qll` (classes with a getter per field), each headed as
  generated.
- The facts command walks each program's ASG with the same rules and writes the rows.
- A test regenerates both files and compares them with the committed ones.

## Units

1. Generator, emitter, committed schema and QL classes, staleness test. The current statement
   tables keep feeding `Cfg.qll` and `DataFlow.qll`.
2. `Cfg.qll` and `DataFlow.qll` rewritten over the generated AST; the hand-written statement
   tables and their Python go. Which cells an operand names, and which paragraphs a PERFORM or
   GO TO reaches, stay cobble's answers, written as facts that link the generated nodes to the
   layout cells and paragraphs (decided by the user: one copy of COBOL's naming rules).
3. Statement by statement, the flow and control-flow semantics in QL (EVALUATE, arithmetic,
   STRING, INITIALIZE, file I/O, EXEC CICS, EXEC SQL, conditions as reads), each checked against
   cobble's fixpoint on CardDemo.

## Calls made without the user

- Labels are positions (parent label, field position, element index), not counters, so a
  label is stable across runs and readable in a TRAP file.
- A map always gets a key table and a value table, whether or not its values are optional, so
  the generator has one path for maps.
- A field named after a dbscheme keyword gets a trailing underscore.
