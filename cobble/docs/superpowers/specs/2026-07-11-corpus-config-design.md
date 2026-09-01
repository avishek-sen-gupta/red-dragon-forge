# Config-driven corpus extraction

## Context

`build_port.py` (the driver that runs cobble's four extractors — JCL, CALL/COPY,
CICS flow, batch FILE-CONTROL — over a COBOL/CICS/JCL corpus) hardcodes the
CardDemo corpus location and layout as module-level constants: `_CARDDEMO_HOME =
vendor/carddemo/app`, fixed subdirectory names (`cbl/`, `jcl/`, `proc/`, `csd/`,
`cpy/`, `cpy-bms/`), a fixed CSD filename (`CARDDEMO.CSD`), and a repo-root
`cics-copybooks/` directory. `generate_sym.py` (BMS symbolic-copybook generation)
similarly hardcodes `vendor/carddemo/app/bms/*.bms`.

The extractors themselves (`extract_jcl_graph`, `extract_cobol_imports`,
`extract_transaction_flow_graph`, `extract_cobol_file_graph`, `GraphWriter`,
`merge_graph`) are already corpus-agnostic — only the driver scripts' path
constants are CardDemo-specific. This makes it impossible to point cobble at a
different COBOL/CICS/JCL codebase without editing Python source. This design
externalizes the corpus location/layout into a YAML config file, so a user can
run cobble against their own codebase by writing a config file and passing it on
the command line — no repo edits required.

## Goals

- Run `build_graph.py` (renamed from `build_port.py`) and `generate_sym.py`
  against any COBOL/CICS/JCL corpus by pointing at a YAML config file, with zero
  Python source changes.
- Preserve today's CardDemo behavior exactly, via a tracked
  `config/carddemo.yaml` that the `Makefile`'s `build`/`sym` targets pass.
- No hidden defaults: every path/glob the pipeline needs comes from the config
  file explicitly. A missing or malformed config fails loudly.
- Support corpora with no CICS at all (`csd_files: []` skips the CICS-flow
  stage) since not every COBOL/JCL codebase uses CICS.

## Non-goals

- `compare.py`'s golden-file diff stays CardDemo-specific (its `reference/`
  golden is inherently tied to the CardDemo corpus) — not part of this change.
- The two bridge JAR locations (`PROLEAP_BRIDGE_JAR`, `JCL_BRIDGE_JAR`) stay as
  env vars — they're a fact about cobble's own build output, not the corpus
  being analyzed.
- Output directories (`out/`, `sym/`) are configurable in the YAML (see below)
  but the *default* CardDemo config keeps them at today's paths.

## Design

### New file: `corpus_config.py` (repo root)

A driver-script-level module (like `build_port.py`/`compare.py` today) — not
under `cobble/**`, since it's tooling for this repo's own scripts, not ported
production code.

Split into a pure core and an imperative shell (functional core / imperative
shell, per project convention):

```python
@dataclass(frozen=True)
class CorpusConfig:
    cobol_dir: Path
    cobol_globs: tuple[str, ...]
    jcl_dir: Path
    jcl_globs: tuple[str, ...]
    proclib_dirs: tuple[Path, ...]
    csd_files: tuple[Path, ...]          # () means "no CICS in this corpus"
    copybook_dirs: tuple[Path, ...]
    out_dir: Path

@dataclass(frozen=True)
class BmsConfig:
    bms_dir: Path
    macros_dir: Path
    sym_dir: Path

def _corpus_config_from_dict(data: Mapping) -> CorpusConfig: ...  # pure
def _bms_config_from_dict(data: Mapping) -> BmsConfig: ...        # pure

def load_corpus_config(path: Path) -> CorpusConfig: ...  # reads YAML, resolves paths, delegates
def load_bms_config(path: Path) -> BmsConfig: ...         # same
```

- All list-shaped fields are `tuple[str, ...]` / `tuple[Path, ...]`, never
  `None` — an absent/empty key means `()`, per the "no `None` as a default
  parameter" convention.
- Relative paths in the YAML resolve against the current working directory
  (matching today's implicit behavior — scripts are always run from repo
  root), not against the config file's own location.
- Every required key is read without a fallback default; a missing key raises
  (`KeyError` or an explicit, clearly-worded check) rather than silently
  guessing a CardDemo path.
- The pure `_*_from_dict` functions take a plain `Mapping` and do no file I/O —
  directly unit-testable with hand-built dicts, no `tmp_path` needed. Only
  `load_corpus_config`/`load_bms_config` touch the filesystem.

### YAML schema

One file, two top-level sections — `build_graph.py` reads only `corpus:`,
`generate_sym.py` reads only `bms:`:

```yaml
corpus:
  cobol_dir: vendor/carddemo/app/cbl
  cobol_globs: ["*.cbl"]
  jcl_dir: vendor/carddemo/app/jcl
  jcl_globs: ["*.jcl", "*.JCL"]
  proclib_dirs:
    - vendor/carddemo/app/proc
  csd_files:
    - vendor/carddemo/app/csd/CARDDEMO.CSD
  copybook_dirs:
    - sym
    - vendor/carddemo/app/cpy
    - vendor/carddemo/app/cpy-bms
    - cics-copybooks
  out_dir: out

bms:
  bms_dir: vendor/carddemo/app/bms
  macros_dir: bms-macros
  sym_dir: sym
```

### `build_graph.py` (renamed from `build_port.py`)

- `argparse` with a required `--config <path>` flag (no default value — omitting
  it is a usage error, matching "no hidden defaults").
- Replaces `_CARDDEMO_HOME`/`_CICS_COPYBOOKS`/`_COPYBOOK_DIRS`/`_OUT_DIR` with
  fields read off the loaded `CorpusConfig`.
- `_build_jcl_graph`, `_build_call_copy_graph`, `_build_batch_file_graph` read
  `cobol_dir`/`cobol_globs`/`jcl_dir`/`jcl_globs`/`proclib_dirs` from the
  config instead of hardcoded dirs and a single fixed glob.
- `_build_cics_flow_graph` reads `csd_files` (plural — merges the
  transid→program map from every listed CSD) and becomes conditional: if
  `csd_files` is empty, the stage is skipped with a printed note instead of
  attempting to parse a nonexistent file.
- `_make_parser`'s `copybook_dirs=` comes from `CorpusConfig.copybook_dirs`.

### `generate_sym.py`

- Same `--config <path>` treatment, loads `BmsConfig`, reads `bms_dir`,
  `macros_dir`, `sym_dir` from it instead of the hardcoded CardDemo paths.

### `config/carddemo.yaml` (new, tracked)

Captures today's CardDemo layout exactly, so existing behavior (449/803 golden
graph) is unchanged — this file is the config the `Makefile`'s `build`/`sym`
targets pass by default.

### `Makefile`

`build` and `sym` targets updated to pass `--config config/carddemo.yaml`. No
other targets change.

### New dependency

`PyYAML`, added via `uv add pyyaml`. cobble's dependency list stays otherwise
unchanged (`lark`, `networkx`, `antlr4-python3-runtime`).

## Testing

Test-first, per project convention: `tests/test_corpus_config.py` (root-level,
mirroring where `build_graph.py`/`corpus_config.py` live) is written before
`corpus_config.py`'s implementation, covering:

- `_corpus_config_from_dict`/`_bms_config_from_dict` against hand-built dicts —
  full field population, tuple typing, the `csd_files: []` / omitted-key ⇒
  empty-tuple case.
- `load_corpus_config`/`load_bms_config` against a `tmp_path`-written YAML
  file — end-to-end read + parse + path resolution against CWD.
- Error cases: missing required key raises with a clear message; malformed
  YAML raises.

This slots alongside the existing Phase 1-2 pytest suite (`tests/`,
`make test`).

## Verification

- `make test` passes, including the new `test_corpus_config.py`.
- `make build` (using the new `config/carddemo.yaml` by default via the
  Makefile) still produces the same `out/{nodes,edges}.jsonl`.
- `make verify` (build + compare) still reports the empty diff (449 nodes / 803
  edges) — confirms the refactor is behavior-preserving.
- `make sym` still regenerates the same `sym/*.cpy` copybooks via the new
  `--config` flag.
- Manually confirm `python build_graph.py --config <missing-file>` and
  `python build_graph.py` (no `--config`) both fail with a clear error rather
  than silently doing something CardDemo-specific.
