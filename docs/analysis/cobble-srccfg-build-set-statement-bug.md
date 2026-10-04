# Findings: `cobble-srccfg-build` crash on malformed `SET` statement operands

**Status:** diagnosed, not fixed. Findings only.

## Symptom

`cobble-srccfg-build` crashes while building a program's CFG:

```
File ".../cobol_asg/set_operand.py", line 41, in set_operand_from_dict
    kind=OperandKind(str(data["kind"])),
TypeError: string indices must be integers, not 'str'
```

followed by a second, cascading failure in the next stage (`cobble-srccfg-webgl`),
because the first crash never produced a fresh output file — the stale pre-existing
`cfg-<PROGRAM>.json` (predating a prior JSONL row-format change) is still on disk, and
`cobble-srccfg-webgl`'s loader correctly rejects it as not matching the current row
schema:

```
pydantic_core._pydantic_core.ValidationError: 61 validation errors for union[CfgProgramRow,...]
...
cobble.dataflow.srccfg.bundle.CfgDocumentError: cfg-<PROGRAM>.json:1: not a CFG row -- rebuild it with cobble-srccfg-build
```

The second error is a symptom of the first crash, not an independent bug: once the
first stage can run to completion, the second resolves on its own.

## Root cause

`cobble-srccfg-build` reads the ASG (ProLeap-parsed COBOL AST JSON) and deserializes it
via `CobolASG.from_dict()`. For one `SET` statement in the affected program, the ASG
JSON's `targets`/`values` arrays contain **bare strings** instead of operand objects:

```json
{"type": "SET", "set_type": "TO", "targets": ["WS-COUNTER"], "values": ["1"],
 "line_start": 0, "col_start": 0, "line_end": 0, "col_end": 0}
```

(line/col values above are illustrative placeholders, not the real source coordinates.)

Every other `SET` statement observed in the same ASG file has `targets`/`values`
entries that are full operand objects — `{"kind": "REF", "name": ..., "qualifiers":
[...], "subscripts": [...]}` or `{"kind": "LITERAL", "value": ...}` — which is the
shape `cobol_asg/set_operand.py::set_operand_from_dict` expects:

```python
def set_operand_from_dict(data: JsonExpr) -> SetOperand:
    return SetOperand(
        kind=OperandKind(str(data["kind"])),   # <- data is a bare string here, not a dict
        ...
```

`data["kind"]` on a plain string is a string-indexed-by-string access, which Python
rejects with exactly `TypeError: string indices must be integers, not 'str'` — matching
the traceback precisely. Confirmed by scanning every `SET` statement in the affected
program's ASG JSON (recursing into `children`/`else_children`) for a non-dict
`targets[]` entry: exactly one such statement was found, of the form
`SET <field> TO <literal>`.

**Not yet determined** (needs further investigation in the ProLeap bridge itself):
whether the bridge emits bare strings for a specific `SET` grammar variant it doesn't
fully model — e.g. `SET index-name TO literal` (the table-indexing form of `SET`,
distinct from an ordinary `SET identifier TO identifier/literal`) being serialized
differently when the target is declared `USAGE INDEX` — versus a one-off
serialization defect unrelated to the statement's grammatical form. Confirming which
requires checking the target field's own declaration and the bridge's SET-statement
serializer in `vendor/red-dragon/proleap-bridge/`, neither of which was reached before
this investigation was redirected to write-up only.

## Blast radius

- Blocks `cobble-srccfg-build`/`cobble-srccfg-webgl` for the affected program, and
  therefore every downstream stage that needs that program's CFG (narration, claims
  synthesis, sequence diagrams, any flow-model/FSD pipeline whose scope includes it).
- Corpus-wide scope of the underlying defect is **not yet checked** — this
  investigation only confirmed one occurrence in one program's ASG. Other programs may
  contain the same bare-string `SET` operand shape and would fail identically the
  first time their CFG is (re)built.

## Candidate fix locations (not implemented, for discussion)

1. **ProLeap bridge (`vendor/red-dragon/proleap-bridge/`):** fix the SET-statement
   serializer to always emit full operand objects, matching every other `SET`
   statement. Correct at the source, but requires rebuilding the bridge JAR
   (`make setup` at the forge root) and re-running the parse stage to regenerate every
   affected program's ASG JSON — the highest-cost, most correct option.
2. **`cobol_asg/set_operand.py::set_operand_from_dict`:** accept a bare string
   defensively — treat it as `SetOperand(kind=OperandKind.REF, name=data)` (or
   `LITERAL` if it looks numeric) rather than assuming a `Mapping`. Matches the
   dual-tolerance pattern already used elsewhere for format drift in this codebase, but
   papers over an ASG shape inconsistency rather than fixing its source, and risks
   guessing wrong between a reference name and a literal for an ambiguous bare string.
3. **`cobol_statements.py::SetStatement.from_dict`:** same defensive tolerance, scoped
   one level higher (wrap each raw `targets`/`values` entry before calling
   `set_operand_from_dict`), keeping `set_operand_from_dict` itself strict.

No fix applied. Confirming the affected field's declaration and the bridge's own
serializer code is the next step before choosing between option 1 and options 2/3.
