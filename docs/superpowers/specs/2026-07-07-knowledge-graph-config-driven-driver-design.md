# Config-Driven Knowledge Graph Driver Design

## Problem

`knowledge_graph/build_carddemo_graph.py` (an ad hoc follow-up to the
COBOL/CICS/JCL knowledge-graph feature — see
`docs/superpowers/plans/2026-07-07-cobol-knowledge-graph.md`) runs the three
graph extractors over the full CardDemo corpus and renders one HTML
visualization. Every part of that pipeline that's specific to *this
codebase* — directory layout, file extensions, whether CICS/JCL exist at
all, program-name-to-file mapping — is hardcoded as module-level constants
(`_CARDDEMO_HOME`, `_CICS_COPYBOOKS`, `_HLASM_EXPORT_BIN`, ...). Pointing
this at a different COBOL/CICS/JCL codebase means editing the script, not
reusing it.

The three underlying extractors (`extract_cobol_connections`,
`extract_transaction_flow_graph`, `extract_jcl_graph`) and the
merge/query/export/render layer are already fully generic — nothing in
them is CardDemo-specific. Only the driver needs to change.

## Goal

Replace `build_carddemo_graph.py` with a generic, config-driven driver that
runs against any COBOL/CICS/JCL codebase by supplying a YAML config file
describing that codebase's layout, rather than editing Python. CardDemo
becomes the first real, checked-in example config, not a special case in
the code.

## Non-goals

- Does not address node-identity collisions across unrelated applications
  sharing one graph (a program named `VALIDATE` in two different apps
  would still merge into one node) — a schema-level concern, separate from
  directory layout.
- Does not address the reliability of `extract_cobol_connections`'s
  underlying COPY/CALL text-scan (`interpreter/project/imports.py`) against
  COBOL written in a different house style than CardDemo's — an extractor-
  level concern, not something a layout config can fix.
- Does not add schema validation beyond straightforward dataclass field
  construction — no JSON-Schema/pydantic-style validation layer. The
  codebase this config lives in doesn't currently use one, and the config
  shape is small enough not to need it.

## Design

### Two-tier config split

Toolchain locations (JAR paths, the bms-tools `hlasm_export` binary,
RedDragon's own bundled CICS system copybooks dir) are fixed per machine/
installation, not per target codebase — they stay exactly where they
already are: environment variables (`PROLEAP_BRIDGE_JAR`, `JCL_BRIDGE_JAR`),
matching the convention every other test/tool in this codebase already
uses. No new toolchain-config mechanism.

The per-codebase config — directory layout, file extensions, which passes
apply — is the new piece: a YAML-loadable, frozen dataclass.

### Config schema

```python
# knowledge_graph/config.py

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CobolCallCopyConfig:
    cbl_dir: Path
    copybook_dirs: list[Path]  # in precedence order — first match wins
    file_globs: list[str] = field(default_factory=lambda: ["*.cbl"])


@dataclass(frozen=True)
class JclConfig:
    jcl_dir: Path
    file_globs: list[str] = field(default_factory=lambda: ["*.jcl", "*.JCL"])


@dataclass(frozen=True)
class CicsConfig:
    csd_path: Path
    bms_dir: Path | None = None
    program_overrides: dict[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class CodebaseConfig:
    name: str
    home: Path
    call_copy: CobolCallCopyConfig
    jcl: JclConfig | None = None
    cics: CicsConfig | None = None
    output_path: Path = Path("knowledge_graph.html")

    @staticmethod
    def from_yaml(path: Path) -> "CodebaseConfig":
        ...
```

- `jcl: None` or `cics: None` means "this codebase has no JCL" / "no CICS"
  — the driver skips that extraction pass entirely, rather than requiring
  an empty/dummy section.
- `CicsConfig.bms_dir: None` means no program in this codebase does
  `SEND`/`RECEIVE MAP`, so the bms-tools symbolic-copybook generation step
  is skipped — distinct from "this codebase has no CICS at all"
  (`cics: None`), since a CICS codebase without BMS screens is possible.
- `copybook_dirs` is an explicit ordered list — replaces the current
  script's hardcoded `[sym_dir, cpy_dir, cpy_bms_dir, _CICS_COPYBOOKS]`
  precedence chain; a generated symbolic-copybook dir (produced by the
  driver itself when `bms_dir` is set, not user-supplied) is prepended to
  whatever list the config provides, so it still wins over any shipped
  copybook sharing the same basename.
- `program_overrides` is the escape hatch for the naming-convention
  default: a CSD program name resolves to `program_overrides[name]` if
  present, else falls back to `cbl_dir / f"{name}.cbl"` — most COBOL shops
  (CardDemo included) really do name files after `PROGRAM-ID`, so the
  convention is the zero-config default and the override table only needs
  entries for the exceptions.
- `CodebaseConfig.from_yaml` raises a clear, field-naming error (not a bare
  `KeyError`/`TypeError`) on a malformed or incomplete YAML file.

### Driver control flow

`knowledge_graph/build_graph.py --config <path.yaml>` replaces
`build_carddemo_graph.py`.

```python
def build_call_copy_graph(
    config: CobolCallCopyConfig, cics_program_names: set[str], failures: list[str]
) -> tuple[list, list]: ...

def build_jcl_graph(config: JclConfig, failures: list[str]) -> tuple[list, list]: ...

def build_cics_flow_graph(
    config: CicsConfig, cbl_dir: Path, failures: list[str]
) -> tuple[list, list]: ...


def main(config_path: Path) -> int:
    config = CodebaseConfig.from_yaml(config_path)
    failures: list[str] = []
    all_nodes, all_edges = [], []

    if config.jcl is not None:
        nodes, edges = build_jcl_graph(config.jcl, failures)
        all_nodes += nodes
        all_edges += edges

    cics_program_names: set[str] = set()
    if config.cics is not None:
        transid_to_program = parse_csd(config.cics.csd_path)
        cics_program_names = set(transid_to_program.values())

    call_nodes, call_edges = build_call_copy_graph(
        config.call_copy, cics_program_names, failures
    )
    all_nodes += call_nodes
    all_edges += call_edges

    if config.cics is not None:
        nodes, edges = build_cics_flow_graph(
            config.cics, config.call_copy.cbl_dir, failures
        )
        all_nodes += nodes
        all_edges += edges

    graph = merge_graph(all_nodes, _dedupe_edges(all_edges))
    render_html(graph, config.output_path, title=f"{config.name} Knowledge Graph")

    if failures:
        print(f"{len(failures)} failure(s) (skipped, did not abort the run):")
        for f in failures:
            print(f"  - {f}")
    return 0
```

Everything here is a direct parameterization of `build_carddemo_graph.py`'s
existing, working logic — no new behavior:

- **Per-file failure tolerance** (a bad `.cbl`/JCL job is logged and
  skipped, never aborts the run) — unchanged.
- **CICS-vs-batch routing** (a program named in the CSD's program set gets
  the full `build_cics_spec` lowering strategy — required for
  `DFHRESP(...)` condition handling to lower correctly, per the earlier
  full-corpus debugging; everything else compiles as plain batch COBOL) —
  unchanged, just driven by `cics_program_names` computed from config.
- **Symbolic-copybook precedence** (generated map copybooks win over
  shipped ones sharing a basename) — unchanged, generated dir still
  prepended ahead of `config.call_copy.copybook_dirs`.
- **Edge dedup** (`_dedupe_edges`, from the prior fix — a subprogram's
  COPY/CALL edges get emitted once per caller that transitively reaches it
  plus once as its own top-level entry, when compiling every file in a
  directory) — unchanged, still applied once before `merge_graph`.

`program_overrides` resolves before the naming convention: for a CSD
program name, check `config.cics.program_overrides` first, fall back to
`config.call_copy.cbl_dir / f"{name}.cbl"`.

### Testing

- Unit tests for `CodebaseConfig.from_yaml`: a full config (every section
  present), a minimal config (`jcl`/`cics` omitted), the
  `program_overrides`-before-convention fallback, and a clear error on
  malformed/incomplete YAML.
- Unit test for the program-name-resolution logic in isolation (no real
  compilation needed).
- One integration test: a YAML fixture pointing at the same real,
  already-verified CardDemo slice Task 9 used
  (`READACCT.jcl`/`CBACT01C.cbl`/the synthetic CICS program), run through
  the new generic driver, asserting the same cross-source connectivity
  Task 9 already proved — confirms the generic path produces the same
  result the hardcoded one did, not just that YAML loading works in
  isolation.
- No new test fixtures needed beyond what the original plan already
  established (`carddemo_home`, `bridge_jar`, `jcl_bridge_jar`).

### CardDemo migration

`build_carddemo_graph.py` is deleted.
`knowledge_graph/configs/carddemo.yaml` becomes the first real, checked-in
example config, exercising every section (JCL + CALL/COPY + CICS,
`program_overrides` empty since CardDemo's naming convention holds
cleanly). Running the full-corpus build becomes:

```bash
uv run --no-sync python knowledge_graph/build_graph.py \
    --config knowledge_graph/configs/carddemo.yaml
```

## Open risks

- **`program_overrides` completeness is unverified for codebases beyond
  CardDemo** — the escape hatch exists, but its real-world sufficiency
  (does every plausible naming-convention exception fit a flat
  `{name: path}` table, or do some shops need something richer, e.g. a
  glob/regex rule) is untested until a second real codebase is configured
  against this.
- **`copybook_dirs` precedence is still a flat ordered list** — sufficient
  for CardDemo's four-directory case; a codebase with a much larger or
  more dynamically-structured copybook search path might need something
  more expressive than a static list in YAML. Deferred until it's a real
  problem.
- The two Non-goals (node-identity collisions, extractor text-scan
  reliability) remain open, tracked separately from this config work.
