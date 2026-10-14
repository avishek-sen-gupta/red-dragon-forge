# File Definitions as IR Data — Design

**Date:** 2026-10-15
**Issue:** red-dragon-forge-96h (blocks red-dragon-forge-jr5, the prebuilt-program runner)

## Problem

jackal needs each program's file definitions: what FILE-CONTROL and the FDs say. It uses
them to label the datasets a step creates and to check an FD against a cataloged label
(status 39). A linked program does not contain them, so after every compile jackal re-reads
the `.ast.json` files named in `LinkedProgram.ast_paths` (`jackal/jackal/program_compiler.py`).

So a linked program is not enough on its own. jr5 runs programs from a package that holds
linked programs and no AST files, and a batch step run from a package would have no file
definitions.

COBOL lowering reads FILE-CONTROL and the FDs, lays out the FILE SECTION, bakes each OPEN's
organisation, record length and key position into the IR as constants, and discards the
rest. `LinkedProgram.data_layout` carries the WORKING-STORAGE layout only.

## Goal

The linked program carries every program's file definitions, and jackal reads them from it
and from nothing else. Scope is parity: exactly the facts jackal reads from the ASTs today.

## Decisions

**D1. A `Data` instruction in red-dragon's IR.** `Data` declares a named value. The VM
steps over it, the CFG treats it as an ordinary non-branching instruction, and no runtime
reads it. It is a data directive, not code. The IR does not know any frontend's or VM's
types, so the value is a generic nested literal:

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

**D2. COBOL lowering emits one `Data` per program.** It is the program's first IR
instruction. Its value is a record with one field, `files`: a list with one record per
SELECT, in FILE-CONTROL order. Later kinds of declaration become sibling fields. The linker
namespaces the `Data` name per module like any other variable, so a CALLed subprogram's
files stay attached to it.

Each file record holds, for one SELECT:

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
| `record_lengths` | a list of each 01 record's length, from the FILE SECTION layout |
| `depending` | whether any 01 record contains OCCURS DEPENDING ON |

These are the inputs of jackal's `program_files` today: `FileControlEntry`, the
`FileDescription`, and `FdRecords(lengths, depending)`.

**D3. jackal reads `Data` and nothing else.** `ProgramCompiler` builds its `ProgramFile`s
from every `Data` in the linked program's IR: a `FileControlEntry` per file record, and a
`program_format(FileDescription, FdRecords)` per FD record, or `FormatFromDataset` where
the SELECT has no FD. The conversion from `DataValue` to these types is jackal's one
boundary for this data. jackal stops reading `ast_paths` and parsing ASTs.

**D4. `ast_paths` leaves `LinkedProgram`.** Once jackal no longer reads it, nothing does.
red-dragon removes the field, its `LinkedCodec` handling, and its population in
`cobol_compile.py`. The linked-file format number goes up.

**D5. Everything that walks IR accepts `Data`.** Any exhaustive match over instruction
types — the VM's dispatch, the CFG builder, type inference, the interprocedural and
dataflow passes, and cobble's IR analyses — handles `Data` as a no-op that reads and
writes no registers.

## Out of scope

- Runtimes reading `Data`. The file provider keeps taking FILE-CONTROL entries from its
  caller; jackal builds them from `Data`.
- Any file fact jackal does not read today (for example ALTERNATE RECORD KEY, bead
  red-dragon-forge-cdvk).
- The package and runner (jr5).

## Testing

- **red-dragon:** `IrCodec` round-trips a `Data` with nested records and lists. COBOL
  lowering of a program with an indexed and a sequential SELECT, one with an FD carrying
  RECORDING MODE V and RECORD VARYING, emits exactly the expected `Data`. The VM runs a
  program containing `Data` with unchanged results. A linked file written without
  `ast_paths` reads back.
- **jackal:** the existing status-39, DCB-labelling and concatenation tests pass with
  `ProgramFile`s built from `Data`; a test asserts that a linked program read back from its
  `.linked.json`, with its work directory deleted, yields the same `ProgramFile`s.
- **cobble:** its IR analyses pass over programs containing `Data`.

## Units

1. **red-dragon:** the `Data` instruction, `DataValue`, codec, and no-op handling (D1, D5).
2. **red-dragon:** COBOL lowering emits `Data` (D2). Push; bump the forge.
3. **forge:** jackal reads `Data` (D3); cobble accepts `Data` (D5).
4. **red-dragon:** `ast_paths` removed (D4). Push; bump the forge.
