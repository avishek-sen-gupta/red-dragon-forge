# Program Declarations as IR Data — Design

**Date:** 2026-10-15
**Issue:** red-dragon-forge-96h (blocks red-dragon-forge-jr5, the prebuilt-program runner)

## Problem

Two facts about a COBOL program travel outside its IR.

- **File definitions.** jackal needs what FILE-CONTROL and the FDs say, to label the
  datasets a step creates and to check an FD against a cataloged label (status 39). A
  linked program does not contain them, so after every compile jackal re-reads the
  `.ast.json` files named in `LinkedProgram.ast_paths` (`jackal/jackal/program_compiler.py`).
  A package of linked programs (jr5) has no AST files, so a batch step run from one would
  have no file definitions.
- **The data layout.** `ModuleUnit.data_layout` and `LinkedProgram.data_layout` are an
  untyped `dict[str, dict]`: WORKING-STORAGE field name → offset, length, category, digits,
  sign. red-dragon's runtime never interprets it; `run.py` copies it into
  `VMState.data_layout`, where the coprocessor builtins read it to find fields by name —
  squall's host-variable binding, `SQLCODE` and `SQLERRM` (`squall/binding.py`), and
  cicada's field writes, screen I/O and LINK/XCTL (`cics/builtins/cells.py`, `system.py`,
  `screen.py`, `flow.py`).

## Goal

A linked program carries both as declarations in its own IR, and nothing outside the IR
holds them. Scope is parity: the file facts jackal reads from the ASTs today, and the
layout entries the dictionary holds today.

## Decisions

**D1. A `Data` instruction in red-dragon's IR.** `Data` declares a named value. The VM
steps over it, the CFG treats it as an ordinary non-branching instruction, and the core
runtime never interprets it. It is a data directive, not code. The IR does not know any
frontend's or VM's types, so the value is a generic nested literal:

```
Data(name: VarName, value: DataValue)

DataValue  = DataScalar | DataRecord | DataList
DataScalar(value: bool | int | str, type_expr: TypeExpr)
DataRecord(fields: tuple[DataField, ...])
DataField(name: FieldName, value: DataValue)
DataList(items: tuple[DataValue, ...])
```

`DataScalar` is typed the way `Const` is. A record has no type name: what a record means
is given by the name of the `Data` and the field names it sits under. `IrCodec` encodes all
five classes; `Data` joins the `Instruction` union, so it is encoded wherever instructions
are.

**D2. COBOL lowering emits two `Data` per program**, immediately after the module's entry
label, each under a fixed name declared once as a constant in red-dragon's COBOL package.
The linker namespaces code labels only, never variable names, so every module's `Data`
keeps its exact name; each sits in its own module's IR.

**D3. `__cobol_file_definitions`** is a record with one field, `files`: a list with one
record per SELECT, in FILE-CONTROL order. Each file record holds, for one SELECT:

| field | value |
|---|---|
| `file_name` | the SELECT name |
| `assign_to` | the ASSIGN name |
| `organization` | `SEQUENTIAL`, `INDEXED` or `RELATIVE` |
| `access_mode` | `SEQUENTIAL`, `RANDOM` or `DYNAMIC` |
| `record_key` | the RECORD KEY field name, or `""` |
| `relative_key` | the RELATIVE KEY field name, or `""` |
| `file_status` | the FILE STATUS field name, or `""` |
| `fd` | a list: empty when the SELECT has no FD, else one record (below) |

An FD record holds:

| field | value |
|---|---|
| `recording_mode` | `F`, `V`, `U`, `S`, or `""` when not coded |
| `record_clause` | a record with `kind` (`none`, `contains`, `range`, `varying`) and the clause's own fields (`size`; `minimum`, `maximum`; `depending_on`) |
| `record_lengths` | a list of each 01 record's length (`record_length`, as jackal computes it today) |
| `depending` | whether any 01 record contains OCCURS DEPENDING ON |

**D4. `__cobol_data_layout`** is a record with one field, `fields`: a list with one record
per WORKING-STORAGE entry the dictionary holds today, in the same order, each with `name`,
`offset`, `length`, `category`, `total_digits`, `decimal_digits` and `signed`.

**D5. The external structures go.** `ModuleUnit.data_layout`, `LinkedProgram.data_layout`,
`Frontend.data_layout` (and its decorator pass-through), `VMState.data_layout` and
`LinkedProgram.ast_paths` are removed, with their handling in `LinkedCodec`, the linker and
`cobol_compile.py`. The linked-file format number goes up.

**D6. The loader hands the running program its declarations, uninterpreted.** `VMState`
gains `declarations: tuple[Data, ...]`. Wherever `run.py` sets `vm.data_layout` today, it
instead sets `vm.declarations` to the `Data` instructions of the main module — the
`ModuleUnit` in `linked.modules` whose namespaced entry label is
`linked.entry_func_label` — exactly the program whose layout the dictionary held. The core
never looks inside them.

**D7. red-dragon's COBOL package reads what it wrote.** It provides typed readers next to
the writers: `field_positions(declarations) -> Mapping[str, FieldPosition]` (a frozen
`FieldPosition` with the seven D4 fields) from `__cobol_data_layout`. squall and cicada
replace every `vm.data_layout` lookup with `field_positions(vm.declarations)`; cicada's
LINK/XCTL sets the inner VM's declarations from the callee's linked program, as it copies
the layout today.

**D8. jackal reads file definitions from `Data` and nothing else.** `ProgramCompiler`
builds its `ProgramFile`s from every `__cobol_file_definitions` in the linked program's
IR: a `FileControlEntry` per file record, and `program_format(FileDescription, FdRecords)`
per FD record, or `FormatFromDataset` where the SELECT has no FD. jackal stops reading
`ast_paths` and parsing ASTs.

**D9. Everything that walks IR accepts `Data`.** Every exhaustive match over instruction
types — the run loops, type inference, the CFG builder — handles `Data` as a no-op that
reads and writes no registers.

## Out of scope

- The core runtime interpreting `Data`. Only the COBOL package's readers and their callers
  look inside.
- Any file or field fact not carried today (for example ALTERNATE RECORD KEY, bead
  red-dragon-forge-cdvk; LINKAGE or FILE SECTION entries in the layout).
- The package and runner (jr5).

## Testing

- **red-dragon:** `IrCodec` round-trips a `Data` with nested records and lists. The VM runs
  a program containing `Data` with no LLM fallback and unchanged results. COBOL lowering of
  a program with an indexed SELECT, a sequential SELECT whose FD has RECORDING MODE V and
  RECORD VARYING, and a SELECT with no FD emits exactly the expected file-definitions
  `Data`; a program with no FILE-CONTROL gets an empty `files` list. `field_positions`
  over a lowered program equals the dictionary the frontend produces today, for the
  existing COBOL test programs. A format-1 linked file fails to read with `UnitFormatError`
  naming the file.
- **jackal:** `ProgramFile`s built from `Data` equal those built from the ASTs for every
  jackal COBOL fixture (a parity test, retired once the AST path is deleted); the status-39,
  DCB-labelling and concatenation tests pass; a linked program read back from its
  `.linked.json` with its work directory deleted yields the same `ProgramFile`s.
- **squall and cicada:** their suites, including the CardDemo end-to-end and Db2 tests,
  pass with field lookups through `field_positions(vm.declarations)`.

## Units

1. **red-dragon:** the `Data` instruction, `DataValue`, codec, no-op handling (D1, D9).
2. **red-dragon:** COBOL lowering emits both `Data`; the COBOL readers (D2–D4, D7's
   reader). `VMState.declarations` is set by the loader alongside `data_layout` (D6).
   Push; bump the forge.
3. **forge:** jackal reads file definitions from `Data` (D8); squall and cicada read fields
   through `field_positions(vm.declarations)` (D7).
4. **red-dragon:** the external structures are removed (D5). Push; bump the forge.
