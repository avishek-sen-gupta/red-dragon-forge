# CodeQL facts (experimental)

COBOL as a CodeQL language. Cobble supplies only facts: the parse, each field's byte extent, and
the paragraphs in declaration order. CodeQL's shared libraries supply basic blocks, SSA and the
dataflow solver. What stays COBOL-specific is the language model in QL: the control flow of
PERFORM, and how fields map to the bytes the solver tracks.

Two parts:

- `cobble/experimental/codeql/` is the command `cobble-experimental-codeql-facts`. The
  `.importlinter` contract `codeql-is-a-leaf` lets nothing outside the package import it.
- `codeql-cobol/` holds the extractor pack (`extractors/cobol/`), the QL library
  (`ql/lib/`, `forge/cobol-all`), the queries (`ql/src/`) and the QL tests (`ql/test/`). It has
  no Python, so nothing imports cobble.

Deleting the experiment means deleting both directories, the tests under
`cobble/tests/experimental/codeql/`, the contract and the entry point.

## The facts

`cobble-experimental-codeql-facts --config <corpus.toml> --trap-dir <dir> --archive-dir <dir>`
reads each member's first program from the config's ASG cache. It does not parse, so
`cobble-parse-corpus` must have run. For each member it writes one TRAP file in
`cobol.dbscheme` and copies the source into the archive. A member with a parse-failure marker is
skipped. `prefix.trap` holds the corpus directory.

| table | one row per |
|---|---|
| `programs`, `files`, `locations_default` | program, its source file, a statement's or paragraph's lines |
| `fields(id, program, name, record, start, length, loc)` | layout cell: an occurrence of a field and its bytes in its record |
| `numeric_fields` | cell whose PIC parses as numeric |
| `paragraphs(id, program, name, section, index, loc)` | paragraph, in declaration order |
| `stmts(id, kind, parent, slot, index, loc)` | statement; parent is a paragraph or the IF or inline PERFORM holding it; slot 0 body, 1 THEN or inline body, 2 ELSE |
| `perform_ranges(stmt, first, last)`, `perform_repeats` | out-of-line PERFORM: its first and last paragraph (a section's are its first and last paragraph); TIMES, UNTIL or VARYING |
| `goto_targets(stmt, target)` | GO TO target, every one for a DEPENDING ON |
| `stmt_reads`, `stmt_writes`, `partial_accesses` | cell a statement reads or writes, and whether it does so through a reference modification or subscript |

Labels name entities by position, so a file is readable without a counter: `#p3` is the fourth
paragraph, `#s3_0_1_2_0` is the first statement in the ELSE of the second statement of that
paragraph, `#f12` is the thirteenth cell.

## What QL derives

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
REDEFINES, through a group MOVE, and for a value overwritten in full.

## Limits

- Facts cover MOVE, ACCEPT, DISPLAY, PERFORM, GO TO, IF, STOP RUN and GOBACK. Every other
  statement is kind 0 with no reads, writes or nesting: EVALUATE and its bodies, COMPUTE and the
  other arithmetic, STRING, INITIALIZE, file I/O, EXEC CICS and EXEC SQL. Conditions and the
  DEPENDING ON index are not reads.
- Each member's first program only. No CALL, LINK or XCTL between programs.
- PERFORM ranges are assumed to nest.
- A name resolves to every cell of that name whose qualification path contains the operand's
  qualifiers, so a subscripted name resolves to every occurrence.
- Cells have no source location.
- An online CardDemo program is about 133,000 rows and 4.5 s to extract.
- No commit hook or CI job runs the QL test: neither has the CodeQL CLI. The facts tests run in
  cobble's suite.
