# CodeQL facts (experimental)

COBOL as a CodeQL language. Cobble supplies only facts: the parse, as a syntax tree generated from
the parser's types, each field's byte extent, the units the program runs in order, and which cells
each data name and which units each procedure name denotes. CodeQL's shared libraries supply
basic blocks, SSA and the dataflow solver. What stays COBOL-specific is the language model in QL:
the control flow of PERFORM and GO TO, what each statement reads and writes, and how fields map to
the bytes the solver tracks. A statement the parser gains needs no extractor code (see
[The generated AST](#the-generated-ast)); COBOL's naming rules stay in cobble alone.

Two parts:

- `cobble/experimental/codeql/` holds the commands `cobble-experimental-codeql-facts` and
  `cobble-experimental-codeql-schema`. The `.importlinter` contract `codeql-is-a-leaf` lets
  nothing outside the package import it.
- `codeql-cobol/` holds the extractor pack (`extractors/cobol/`), the QL library
  (`ql/lib/`, `forge/cobol-all`), the queries (`ql/src/`) and the QL tests (`ql/test/`). It has
  no Python, so nothing imports cobble.

Deleting the experiment means deleting both directories, the tests under
`cobble/tests/experimental/codeql/`, the contract and the entry points.

## The facts

`cobble-experimental-codeql-facts --config <corpus.toml> --trap-dir <dir> --archive-dir <dir>`
reads each member's first program from the config's ASG cache, with a cell for every name the
program uses but never declares, as cobble's extents lay them out (`with_undeclared`). It does
not parse, so
`cobble-parse-corpus` must have run. For each member it writes one TRAP file in
`cobol.dbscheme` and copies the source into the archive. A member with a parse-failure marker is
skipped. `prefix.trap` holds the corpus directory.

| table | one row per |
|---|---|
| `programs`, `files`, `locations_default` | program, its source file, a node's lines |
| `fields(id, program, name, record, start, length, loc)` | layout cell: an occurrence of a field and its bytes in its record |
| `numeric_fields` | cell whose PIC parses as numeric |
| `program_statements`, `program_sections`, `program_paragraphs` | the procedure division's statements before any section or paragraph, its sections, its paragraphs outside any section |
| `units(program, index, unit, name, section)` | unit the program runs, in cobble's paragraph order: the program for the statements before any section or paragraph, a section for those at its head, each paragraph |
| `names_cell(node, cell)` | cell a data name denotes, as cobble's dataflow resolves it (`denoted_cells`): the occurrence constant subscripts select, else every occurrence. For a `RefModOperand` naming data, a `FieldRefNode`, `RefModNode`, `AddressOfNode`, `LengthOfNode`, `RefModReference`, `ComputeTarget`, a `SetOperand` naming data, a CALL argument or an EXEC CICS operand that is not a literal |
| `field_names_cell(node, field, cell)` | cell a name held as text denotes: a WRITE, REWRITE or RELEASE's `record_name`, an XML GENERATE's `xml_document`, `from_record` and `count_in`, a RECEIVE MAP's `map_input` (the map's symbolic input record) when it has no INTO, a SEND MAP's `map_output` (its output record) when it has no FROM |
| `names_slice(node, cell, offset, length)`, `names_clamped(node)` | how exactly a name locates its bytes, as `operand_extents` does: a constant reference modification's bytes of the cell; a computed subscript or bound, which locates them only approximately |
| `initialized_cell(initialize, cell)` | elementary cell an INITIALIZE sets: its operands' items but FILLERs and the items under a REDEFINES below an operand (`initialized_extents`) |
| `cfg_nodes(id, program, node, kind, loc)`, `cfg_edges(source, target, kind)`, `cfg_entry` | the control-flow graph cobble's fixpoint walks: `program_cfg`, with the fall-throughs no path takes pruned (`fallthroughs_pruned`), cobble's node ids and edge kinds, entered at the first unit's label |
| `cfg_call(call, first, last)`, `cfg_resume(call, resume)` | a PERFORM: the nodes its range starts and ends at, and where control goes once it returns |
| `cfg_consults(node, cell)` | cell a node consults: a test's operands, a key, a subscript, each name resolved by itself, unqualified, as cobble's fixpoint resolves it |
| `statement_ids(statement, id)`, `cfg_statement(node, statement)`, `cfg_site(node, statement, suffix)` | cobble's id for every statement; the node it lowers to when it has one of its own; the further nodes it lowers to, named by a suffix on its id (`#init`, `#step`, `#loop`, `#test`, `#goto.<n>`) |
| `file_record_cell(read, cell)` | cell a READ or RETURN fills besides INTO: each 01 record of its file |
| `condition_set_cell(set, cell)` | cell a SET ... TO TRUE moves its conditions' first values into, as cobble's fixpoint rewrites it (`with_condition_sets`): only when every condition name resolves |
| `perform_range(perform, first, last)` | out-of-line PERFORM: its first and last unit (a section's are its first and last unit) |
| `procedure_unit(target, unit)` | procedure name: the paragraph so named, else the section's first unit |

The rest of the tables are the generated tree.

## The generated AST

`cobble-experimental-codeql-schema --dbscheme <file> --ql <file>` walks the type hints of every
dataclass reachable from `CobolSection` and `CobolParagraph`, with cicada's `ExecCicsStatement`
and squall's `ExecSqlStatement` added to the statement union. It writes
`extractors/cobol/cobol.dbscheme` (the hand-written tables, then the generated ones) and
`ql/lib/cobol/ast/internal/Generated.qll` (module `Generated`: a class per dataclass with a getter
per field, a class per union, `AstNode` over all of them). Both are committed; after the parser's
types change, regenerate them from `cobble/`:

```bash
uv run cobble-experimental-codeql-schema --dbscheme ../codeql-cobol/extractors/cobol/cobol.dbscheme \
  --ql ../codeql-cobol/ql/lib/cobol/ast/internal/Generated.qll
```

A test in cobble's suite regenerates both and fails when the committed files differ.

| field type | tables |
|---|---|
| `str`, `int`, `bool`, an enum (as its value) | a column of `cobol_<type>_def` |
| a dataclass, or a union of them | a column naming the child node |
| `X \| None` | `cobol_<type>_<field>(id, value)`, a row only when present |
| a list, or a tuple of any length | `cobol_<type>_<field>(id, index, value)` |
| a fixed tuple `tuple[A, B]` | a node `<Type><Field>Item` with `element0`, `element1` |
| `dict[str, X \| None]` | `cobol_<type>_<field>(id, index, entry_key)`, and `..._value(id, index, value)` for present values |
| `SourceSpan` | a `@location_default` in the program's file |

A union gets the name of the parser's alias for it (`Statement`, `ExprNode`, `Condition`, …), or
`<Type><Field>Type` when it has none. A field named after a dbscheme keyword (`key`) gets a
trailing underscore. A node's label is its parent's and the field's position, so `#c0_1_0_1_7` is
section 0, field 1 (`paragraphs`), paragraph 0, field 1 (`statements`), statement 7; `#e`, `#c`
and `#d` start the program's statements, sections and paragraphs, `#f12` is the thirteenth cell.

## What QL derives

- **Transfers** (`Ast.qll`, `transfer`). The cells each verb builds a target from, as cobble's
  fixpoint reads the verb: MOVE (from a FUNCTION, every name in its arguments), ADD, SUBTRACT,
  MULTIPLY and DIVIDE (operands and in-place receivers into receivers, GIVING and REMAINDER),
  COMPUTE (every name in the expression, subscripts included), STRING (each sending, or its
  FUNCTION's arguments, into INTO), WRITE, REWRITE and RELEASE FROM, INSPECT (source and patterns
  into tally targets, and into the source when it is rewritten), UNSTRING, SET (a value naming
  data), SEARCH VARYING, MOVE and ADD CORRESPONDING, and XML GENERATE. `loopTransfer` gives a
  PERFORM VARYING's `#init` and `#step`. A MOVE or a FROM copies byte k to byte k; every other
  verb builds the whole target from every source.
- **Origin writes** (`Ast.qll`, `originWrite`, `loopOriginWrite`). A write whose source is no
  field, with the origin cobble's fixpoint credits it to: LITERAL (a literal, figurative or LENGTH
  OF moved or among a verb's sources, INITIALIZE, SET ... TO TRUE, a literal VARYING FROM or BY),
  UNKNOWN_FIELD, FUNCTION (a FUNCTION reading no field), FILE (READ, and EXEC CICS READ, READNEXT
  and READPREV), MAP (RECEIVE MAP), CICS_STATE (RESP, RESP2, ASKTIME, ASSIGN and every other
  receiver), CALL and DYNAMIC_CALL (CALL BY REFERENCE arguments and GIVING, a LINK or XCTL
  COMMAREA), UNMODELLED (ACCEPT).
- **Reads and writes** (`Ast.qll`). A statement reads and writes what its transfers do, an ACCEPT
  writes its target and a DISPLAY reads its operands. An access through a reference modification
  or a subscript, or a STRING, INSPECT or UNSTRING target, may touch only part of its cell.
- **CFG** (`Cfg.qll`). cobble's graph, as its fixpoint walks it (`cfg_*`, below), split into
  scopes: each PERFORM range is a scope with its own copy of every node it reaches along every
  edge but PERFORM and RETURN. The range's last node leaves the scope; the end of any other range
  falls through as the edges say. The main scope starts at the program's entry. A PERFORM is a
  call into its range's scope, and the caller resumes only when some path through the range
  reaches its end, so a range that only leaves the program (CICS RETURN, XCTL) never comes back.
- **Atoms** (`DataFlow.qll`). The largest byte ranges of a record that no field boundary or
  constant slice splits. A field is a union of atoms; each atom is one SSA variable. A write
  reaches all of a cell's atoms, or only those inside a constant slice; it is uncertain through a
  clamped name or by a verb whose writes cobble's fixpoint makes weak (INSPECT, UNSTRING, SET,
  SEARCH, the CORRESPONDING forms, XML GENERATE, ACCEPT).
- **Dataflow.** A MOVE flows from source atoms to target atoms at the same offset within their
  fields; a numeric field, or a partial access, flows from every source atom to every target
  atom. A PERFORM passes in and out only the atoms its range, or a range it performs, reads or
  writes; a range that never returns writes nothing at the PERFORM, so where cobble's graph
  goes on past it, what came in goes on unchanged, as in cobble's fixpoint.
- **Sinks** (`Ast.qll`, `sink`). Where bytes leave the program, as cobble's fixpoint reads each
  verb: a WRITE or REWRITE's record or FROM (FILE), a SEND MAP's FROM or else its output record,
  unless MAPONLY (MAP), a WRITEQ TS or TD's FROM (TS_QUEUE, TD_QUEUE), a START's FROM (TRANSID).
  A sink is a read of what it sends.

## Running it

```bash
codeql-cobol/fetch-codeql.sh        # CLI 2.27.4 and the QL libraries at that tag, into codeql-cobol/tools/
cd codeql-cobol
./tools/codeql/codeql test run ql/test --search-path=extractors --additional-packs=tools/ql:ql
COBOL_CORPUS_CONFIG=$PWD/../cobble/config/carddemo.toml ./tools/codeql/codeql database create db-carddemo \
  --language=cobol --search-path=extractors --source-root=../vendor/carddemo/app/cbl --build-mode=none
./tools/codeql/codeql query run ql/src/Flows.ql --database=db-carddemo --additional-packs=tools/ql:ql
```

The extractor's `autobuild.sh` runs `cobble-parse-corpus` and then this command. Both need
`bridge-env.sh`. The config is `COBOL_CORPUS_CONFIG`, an absolute path, or else
`cobol-corpus.toml` in the source root. Its paths are relative to `cobble/`, as every corpus
config's are. A QL test directory carries its own config; `ql/test/flows/` caches its ASG in
`cobble/out-codeql-test/`.

`ql/src/diagnostics/` holds five tables for comparing with cobble's fixpoint: `Transfers.ql`
(each transfer at cobble's node id, with both cells' records and bytes), `OriginWrites.ql` (each
origin write, with its origin and target cell), `ReachingDefinitions.ql` (for each node's copy
from a cell or consultation of one, the nodes whose writes reach it, through CodeQL's dataflow
with no flow into another statement's write), `Sinks.ql` (each sink's cells, with the nodes whose
writes they carry: the sink's own where it writes them, else what reaches it) and
`StatementPaths.ql` (every statement's node id and class).

`ql/test/flows/` checks one invented program for flow through a PERFORM called twice, through a
REDEFINES, through a group MOVE, and for a value overwritten in full; `Ast.ql` there reads every
MOVE's source and first target from the generated tree.

## Limits

- A computed subscript names every occurrence. cobble's fixpoint writes it as one span from the
  first occurrence to the last, which also covers the other fields between them, so it finds
  definers CodeQL does not (COCRDLIC's screen rows).
- Each member's first program only. No CALL, LINK or XCTL between programs.
- PERFORM ranges are assumed to nest.
- Cells have no source location.
- An online CardDemo program is about 135,000 rows, most of them layout cells; all of CardDemo
  extracts in about 77 s.
- No commit hook or CI job runs the QL test: neither has the CodeQL CLI. The facts tests run in
  cobble's suite.
