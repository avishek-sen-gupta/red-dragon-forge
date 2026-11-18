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
reads each member's first program from the config's ASG cache. It does not parse, so
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
| `names_cell(node, cell)` | cell a data name denotes, for a `RefModOperand` naming data, a `FieldRefNode`, `RefModNode`, `AddressOfNode`, `LengthOfNode` or `RefModReference` |
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

- **Reads and writes** (`Ast.qll`). A MOVE reads its source and writes its targets, an ACCEPT
  writes its target, a DISPLAY reads its operands: each the cells `names_cell` gives. An access
  through a reference modification or a subscript may touch only part of its cell.
- **CFG** (`Cfg.qll`). Each PERFORM range is a scope with its own copy of every statement it can
  reach. Reaching the end of the range's last paragraph leaves the scope; the end of any other
  paragraph falls through to the next. The main scope starts at the first paragraph. A PERFORM
  is a call into its range's scope.
- **Atoms** (`DataFlow.qll`). The largest byte ranges of a record that no field boundary splits.
  A field is a union of atoms; each atom is one SSA variable. A whole-field write is certain, a
  partial one uncertain.
- **Dataflow.** A MOVE flows from source atoms to target atoms at the same offset within their
  fields; a numeric field, or a partial access, flows from every source atom to every target
  atom. A PERFORM passes in and out only the atoms its range, or a range it performs, reads or
  writes.

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

`ql/test/flows/` checks one invented program for flow through a PERFORM called twice, through a
REDEFINES, through a group MOVE, and for a value overwritten in full; `Ast.ql` there reads every
MOVE's source and first target from the generated tree.

## Limits

- The tree holds every statement, but QL gives meaning only to MOVE, ACCEPT, DISPLAY, PERFORM,
  GO TO, IF, STOP RUN and GOBACK. Every other statement reads and writes nothing and falls
  through, and its nested statements are not in the CFG: EVALUATE and its bodies, COMPUTE and the
  other arithmetic, STRING, INITIALIZE, file I/O, EXEC CICS and EXEC SQL. Conditions and the
  DEPENDING ON index are not reads.
- `names_cell` has no rows for a COMPUTE target, a SET operand or an EXEC CICS operand.
- Each member's first program only. No CALL, LINK or XCTL between programs.
- PERFORM ranges are assumed to nest.
- A name resolves to every cell of that name whose qualification path contains the operand's
  qualifiers, so a subscripted name resolves to every occurrence.
- Cells have no source location.
- An online CardDemo program is about 135,000 rows, most of them layout cells; all of CardDemo
  extracts in about 77 s.
- No commit hook or CI job runs the QL test: neither has the CodeQL CLI. The facts tests run in
  cobble's suite.
