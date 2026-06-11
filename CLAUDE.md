# Cicada — Agent Instructions

## Project

Cicada is the **CICS runtime** for the RedDragon multi-language interpreter. It runs real,
unmodified COBOL programs end-to-end through a CICS emulation layer — pseudo-conversational
transaction dispatch, VSAM KSDS file control, BMS screen handling — without modifying
RedDragon's core VM.

RedDragon lives at `vendor/red-dragon` as an editable submodule (`pip install -e`).
The top-level package is `cics/`.

## Setup

```bash
git clone --recurse-submodules <repo>
cd cicada
uv sync
# COBOL bridge (JDK 17+ and Maven required):
cd vendor/red-dragon/proleap-bridge && ./build.sh && cd -
```

## Tests

```bash
uv run python -m pytest tests/unit/ -x -q        # unit tests (no JAR required)
uv run python -m pytest tests/integration/ -x -q # integration tests (needs ProLeap JAR)
```

## Key invariant

**No edits to RedDragon's core engine** (`interpreter/vm/**`, `ir.py`, `run.py`, `executor.py`,
`cfg.py`). Every CICS behaviour reaches the VM only through `CallFunction` IR to registered
builtins — the same mechanism any language frontend uses.

## Workflow

- Write failing test first (TDD).
- Unit tests go in `tests/unit/`, integration tests in `tests/integration/`.
- Integration tests exercise real VM execution via `run_cics` / `CicsRegion`, not just IR generation.
- Run the full test suite before committing: `uv run python -m pytest tests/ -x -q`.
- Format: `uv run python -m black .`

## Package layout

```
cics/
  strategy.py          # CicsLoweringStrategy — injected into CobolFrontend
  preprocessor.py      # apply_cics_prepass (inject_dfheiblk)
  dfhresp_prepass.py   # DFHRESP ASG pre-pass
  dispatcher.py        # CicsRegion, run_cics, _advance_routing
  bootstrap.py         # compile_cics_program, run_carddemo_region
  types.py             # CicsContext, DispatchResult, DispatchKind
  terminal.py          # ScreenChannel / InputChannel protocols
  le_stubs.py          # IBM LE service stubs (CEEDAYS, etc.)
  builtins/            # CICS service builtins: flow, screen, system, vsam
  vsam/                # VsamEngine, backends, flat-file codec, dump CLI
  bms/                 # BMS symbolic map generation (bms-tools pipeline)
```

RedDragon contributes:
- `interpreter/cobol/cics_parser.py` — Lark EXEC CICS grammar (`CicsOperand`, `parse_exec_cics_text`)
- `interpreter/cobol/exec_cics_strategy.py` — `ExecCicsStrategy` protocol + `CatchAllLoweringStrategy`
