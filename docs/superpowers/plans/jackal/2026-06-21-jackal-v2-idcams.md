# jackal v2 (IDCAMS + real CardDemo job) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the real `ACCTFILE.jcl` (IDCAMS: delete → DEFINE keyed file → REPRO load) then `READACCT.jcl` (`CBACT01C`) end-to-end against the external CardDemo checkout, on real EBCDIC data.

**Architecture:** Extend jackal v1 — the JCL grammar gains in-stream data; the dataset catalog gains a data-dir search path + a KSDS dataset type; a new `idcams` package (Lark grammar + executor) runs IDCAMS control statements; the utility registry gains `IDCAMS`. REPRO loads a PS file into a KSDS using red-dragon's `IndexedDriver` (the same on-disk format `CBACT01C` reads back).

**Tech Stack:** Python 3.13+, uv, pytest, Black, Lark; red-dragon (vendored, editable) for the COBOL VM + file drivers.

## Global Constraints
- **No regex** — JCL in-stream parsing and the IDCAMS control language are Lark grammars (no `import re`).
- TDD (failing test first); FP (`frozen=True` dataclasses, functional core / imperative shell, comprehensions over mutating loops); no defensive programming (no `None` checks/defaults, no swallowed exceptions); small composable functions.
- CardDemo public-sample names (`CBACT01C`, `ACCTFILE.jcl`, `AWS.M2.CARDDEMO.*`, `CARDDEMO_HOME`) are allowed in tracked artifacts; **confidential codebases are not**.
- uv (`uv run pytest`, `uv run black .`); commit through real hooks; `.talismanrc` ignores for any false-positive flags (append before the `version:` line). The COBOL/e2e tests need `PROLEAP_BRIDGE_JAR` (set in the same shell command as any commit, and in the test env).

---

## File Structure
```
jackal/
  model.py                 # + DatasetOrg enum; DD gains in_stream + sysout
  jcl/grammar.lark         # + in-stream data (DD * ... /*), DD SYSOUT=*
  jcl/parser.py            # transformer attaches in_stream/sysout to DD
  catalog.py               # + data_dir search path; Dataset gains org/key/recsize; allocate_ksds
  idcams/__init__.py       # new package
  idcams/grammar.lark      # new — IDCAMS control language
  idcams/parser.py         # new — parse_idcams(text) -> tuple[Command, ...]
  idcams/commands.py       # new — Delete/DefineCluster/Repro/IfMaxcc frozen dataclasses
  idcams/executor.py       # new — run_idcams(commands, step_dds, catalog) -> int (MAXCC)
  utilities.py             # + IDCAMS handler
  cobol_step.py            # + copybook_dirs passed to run()
  runner.py                # + data_dir + copybook_dir threaded into catalog/cobol_step
  cli.py                   # + --data-dir, --source-dir defaults from CARDDEMO_HOME
  tests/
    unit/test_model.py, test_jcl_parser.py, test_catalog.py     # extend
    unit/test_idcams_parser.py, test_idcams_executor.py          # new
    integration/test_carddemo_acctfile_e2e.py                    # new (gated)
```

---

### Task 1: Model — in-stream data, SYSOUT, dataset organization

**Files:** Modify `jackal/model.py`; Test `tests/unit/test_model.py`

**Interfaces — Produces:** `DatasetOrg(PS|KSDS)` enum; `DD` gains `in_stream: tuple[str, ...] = ()` and `sysout: bool = False`.

- [ ] **Step 1: Failing test** (append to `tests/unit/test_model.py`):
```python
def test_dd_instream_and_sysout_and_org():
    from jackal.model import DatasetOrg
    dd = DD(ddname="SYSIN", dsn="", disp=Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP),
            in_stream=("  DELETE X CLUSTER",), sysout=False)
    assert dd.in_stream == ("  DELETE X CLUSTER",)
    assert DatasetOrg.KSDS.value == "KSDS"
```
- [ ] **Step 2: Run → fail** `uv run pytest tests/unit/test_model.py -v` (ImportError / unexpected kwarg).
- [ ] **Step 3: Implement** — add to `model.py`:
```python
class DatasetOrg(Enum):
    PS = "PS"
    KSDS = "KSDS"
```
and extend `DD`:
```python
@dataclass(frozen=True)
class DD:
    ddname: str
    dsn: str
    disp: Disp
    in_stream: tuple[str, ...] = ()
    sysout: bool = False
```
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** `git add jackal/model.py tests/unit/test_model.py && git commit -m "feat: DD in-stream/sysout + DatasetOrg (jackal v2 Task 1)"`

---

### Task 2: JCL parser — in-stream data + SYSOUT DD

**Files:** Modify `jackal/jcl/grammar.lark`, `jackal/jcl/parser.py`; Test `tests/unit/test_jcl_parser.py`

**Interfaces — Consumes:** Task 1's `DD.in_stream`/`sysout`. **Produces:** `parse_jcl` populates `DD.in_stream` (the lines between `//DDN DD *` and the `/*` delimiter) and `DD.sysout=True` for `DD SYSOUT=*`.

**Note:** v1's parser uses Lark `parser="earley"` (see `jcl/parser.py`). In-stream data is free-form text terminated by a line that is exactly `/*`; capture it in the grammar (no regex prepass). If pure-grammar capture of arbitrary in-stream lines fights the card grammar, model the in-stream block as a dedicated terminal matched by a Lark regex *terminal* (allowed — that's grammar, not `import re`) that consumes from `DD *\n` up to `\n/*`.

- [ ] **Step 1: Failing tests** (append):
```python
def test_dd_star_instream_captured():
    jcl = ("//J JOB 1\n//S EXEC PGM=IDCAMS\n//SYSIN DD *\n"
           "   DELETE A.B CLUSTER\n   DEFINE CLUSTER (NAME(A.B))\n/*\n")
    dd = parse_jcl(jcl).steps[0].dds[0]
    assert dd.ddname == "SYSIN"
    assert dd.in_stream == ("   DELETE A.B CLUSTER", "   DEFINE CLUSTER (NAME(A.B))")

def test_dd_sysout():
    jcl = "//J JOB 1\n//S EXEC PGM=IDCAMS\n//SYSPRINT DD SYSOUT=*\n"
    dd = parse_jcl(jcl).steps[0].dds[0]
    assert dd.sysout is True

def test_dsn_disp_still_parses():  # regression: v1 forms unaffected
    jcl = "//J JOB 1\n//S EXEC PGM=P\n//D DD DSN=A.B,DISP=SHR\n"
    assert parse_jcl(jcl).steps[0].dds[0].dsn == "A.B"
```
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — add grammar productions for `dd_card` variants: a `SYSOUT=*` form (sets `sysout=True`) and an in-stream form. Suggested terminal for the in-stream block:
```lark
dd_instream: "//" NAME "DD" "*" NEWLINE INSTREAM
INSTREAM: /(?:(?!\/\*)[^\n]*\n)*/    // lines until a line starting with /*
dd_sysout: "//" NAME "DD" "SYSOUT" "=" "*" NEWLINE
```
Add both to `_statement`. In the transformer, split `INSTREAM` on newlines (drop the trailing empty), strip the closing `/*` handling, and build `DD(ddname=NAME, dsn="", disp=<default SHR/KEEP/KEEP>, in_stream=tuple(lines), sysout=False)`; the `dd_sysout` case builds `DD(..., sysout=True)`. (Iterate the grammar until the three tests pass; keep all card-format logic in the grammar — no Python string scanning, no `import re`.)
- [ ] **Step 4: Run → pass** (all three).
- [ ] **Step 5: Commit** `git add jackal/jcl/grammar.lark jackal/jcl/parser.py tests/unit/test_jcl_parser.py && git commit -m "feat: JCL in-stream data + SYSOUT DD (jackal v2 Task 2)"`

---

### Task 3: Catalog — data-dir search path + KSDS datasets

**Files:** Modify `jackal/catalog.py`; Test `tests/unit/test_catalog.py`

**Interfaces — Consumes:** Task 1 `DatasetOrg`, `DD`. **Produces:** `DatasetCatalog(workdir, data_dir=None)`; `Dataset` gains `org: DatasetOrg = DatasetOrg.PS`, `key_offset: int = 0`, `key_length: int = 0`, `record_size: int = 0`; `allocate_ksds(dsn, key_offset, key_length, record_size) -> Dataset`; `resolve`/`allocate` for `SHR/OLD` fall back to `<data_dir>/<DSN>` when the DSN isn't cataloged.

- [ ] **Step 1: Failing tests** (append):
```python
def test_shr_resolves_from_data_dir(tmp_path):
    from jackal.model import DD, Disp, DispNormal, DispStatus
    data = tmp_path / "data"; data.mkdir()
    (data / "A.B.PS").write_bytes(b"REC1")
    cat = DatasetCatalog(workdir=tmp_path / "wd", data_dir=data)
    (tmp_path / "wd").mkdir()
    dd = DD("D", "A.B.PS", Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP))
    assert cat.allocate(dd).path == data / "A.B.PS"

def test_allocate_ksds(tmp_path):
    from jackal.model import DatasetOrg
    cat = DatasetCatalog(workdir=tmp_path)
    ds = cat.allocate_ksds("A.B.KSDS", key_offset=0, key_length=11, record_size=300)
    assert ds.org is DatasetOrg.KSDS and ds.key_length == 11 and ds.record_size == 300
    assert ds.path.exists()
    assert cat.resolve("A.B.KSDS").org is DatasetOrg.KSDS
```
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — extend `Dataset` with the new fields (defaults keep v1 callers working); add `data_dir: Path | None = None` param to `__init__` (kept as the imperative shell). In `allocate`, the `SHR/OLD/MOD` branch: return the cataloged dataset if present, else (data_dir set and `<data_dir>/<dsn>` exists) seed+return a `Dataset(dsn, <data_dir>/<dsn>)`, else `KeyError`. Add:
```python
def allocate_ksds(self, dsn, key_offset, key_length, record_size):
    path = self._workdir / dsn.replace(".", "_")
    path.write_bytes(b"")
    ds = Dataset(dsn=dsn, path=path, org=DatasetOrg.KSDS,
                 key_offset=key_offset, key_length=key_length, record_size=record_size)
    self._datasets[dsn] = ds
    return ds
```
(`data_dir=None` default means no `None`-in-signature violation — it's a genuine "no search path" null object; if the no-defensive rule is read strictly, accept an explicit empty sentinel instead. Prefer `data_dir: Path | None = None` here as the documented optional-search-path boundary.)
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** `git add jackal/catalog.py tests/unit/test_catalog.py && git commit -m "feat: catalog data-dir search path + KSDS datasets (jackal v2 Task 3)"`

---

### Task 4: IDCAMS control-language parser

**Files:** Create `jackal/idcams/__init__.py`, `jackal/idcams/commands.py`, `jackal/idcams/grammar.lark`, `jackal/idcams/parser.py`; Test `tests/unit/test_idcams_parser.py`

**Interfaces — Produces:** in `commands.py` (all `frozen=True`): `Delete(dsn: str)`, `DefineCluster(name: str, key_length: int, key_offset: int, record_size: int)`, `Repro(infile_dd: str, outfile_dd: str)`, `IfMaxcc(op: str, value: int, set_value: int)`. `parse_idcams(text: str) -> tuple[Command, ...]`.

- [ ] **Step 1: Failing tests** (the real ACCTFILE.jcl control statements):
```python
from jackal.idcams.parser import parse_idcams
from jackal.idcams.commands import Delete, DefineCluster, Repro, IfMaxcc

def test_parse_delete_and_if():
    cmds = parse_idcams("   DELETE A.B.KSDS -\n          CLUSTER\n"
                        "   IF MAXCC LE 08 THEN SET MAXCC = 0\n")
    assert cmds[0] == Delete(dsn="A.B.KSDS")
    assert cmds[1] == IfMaxcc(op="LE", value=8, set_value=0)

def test_parse_define_cluster():
    text = ("   DEFINE CLUSTER (NAME(A.B.KSDS) -\n          KEYS(11 0) -\n"
            "          RECORDSIZE(300 300) -\n          INDEXED -\n          ) -\n"
            "          DATA (NAME(A.B.KSDS.DATA)) -\n          INDEX (NAME(A.B.KSDS.INDEX))\n")
    d = parse_idcams(text)[0]
    assert d == DefineCluster(name="A.B.KSDS", key_length=11, key_offset=0, record_size=300)

def test_parse_repro():
    assert parse_idcams("   REPRO INFILE(ACCTDATA) OUTFILE(ACCTVSAM)\n")[0] == \
        Repro(infile_dd="ACCTDATA", outfile_dd="ACCTVSAM")
```
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** the commands dataclasses, a Lark grammar (starting point below — iterate; `-` is the continuation char, stripped in the grammar; ignore unmodelled DEFINE params like CYLINDERS/VOLUMES/SHAREOPTIONS/ERASE/DATA/INDEX by consuming them without emitting), and a transformer building the command tuple. Grammar starting point:
```lark
start: command+
command: delete_cmd | define_cmd | repro_cmd | if_cmd
delete_cmd: "DELETE" DSNAME _cont? "CLUSTER"
define_cmd: "DEFINE" "CLUSTER" "(" _param+ ")" _trailer*
_param: "NAME" "(" DSNAME ")" | "KEYS" "(" INT INT ")" | "RECORDSIZE" "(" INT INT ")" | OTHERWORD ("(" /[^)]*/ ")")? 
repro_cmd: "REPRO" "INFILE" "(" NAME ")" "OUTFILE" "(" NAME ")"
if_cmd: "IF" "MAXCC" OP INT "THEN" "SET" "MAXCC" "=" INT
_trailer: "DATA" "(" /[^)]*/ ")" | "INDEX" "(" /[^)]*/ ")"
_cont: "-" /\r?\n/
OP: "LE" | "LT" | "GE" | "GT" | "EQ" | "NE"
... (NAME, DSNAME, INT terminals; %ignore whitespace/newlines/`-`)
```
KEYS is `(length offset)` → `key_length, key_offset`. (Iterate until the three tests pass. No `import re`; Lark regex *terminals* are fine.)
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** `git add jackal/idcams tests/unit/test_idcams_parser.py && git commit -m "feat: IDCAMS control-language parser (jackal v2 Task 4)"`

---

### Task 5: IDCAMS executor (incl. REPRO PS→KSDS load)

**Files:** Create `jackal/idcams/executor.py`; Test `tests/unit/test_idcams_executor.py`

**Interfaces — Consumes:** Task 3 catalog (`allocate_ksds`, `resolve`, `dispose`-by-DSN), Task 4 commands, red-dragon `interpreter.cobol.file_drivers.SequentialDriver`/`IndexedDriver`, `interpreter.cobol.file_enums.OpenMode`. **Produces:** `run_idcams(commands, step_dds, catalog) -> int` (final MAXCC). `step_dds: tuple[DD, ...]` maps REPRO's DDnames → DSNs.

**REPRO load:** open the INFILE dataset's file with `SequentialDriver` (`OpenMode.INPUT`, `record_length=<record_size>`), loop `read_seq()` until status `"10"`; open the OUTFILE (KSDS) file with `IndexedDriver` (`OpenMode.OUTPUT`, `record_length`, `key_offset`, `key_length`) and `write(record.encode("latin-1"))` each record (the driver derives the key from the record's key slot). Record size comes from the OUTFILE KSDS dataset (set by a prior `DEFINE`). Read `file_drivers.py` for exact `write`/key semantics.

- [ ] **Step 1: Failing test** (synthetic PS→KSDS round-trip; no bridge needed):
```python
def test_repro_loads_ps_into_ksds(tmp_path):
    from jackal.catalog import DatasetCatalog
    from jackal.idcams.commands import DefineCluster, Repro
    from jackal.idcams.executor import run_idcams
    from jackal.model import DD, Disp, DispNormal, DispStatus
    data = tmp_path / "data"; data.mkdir()
    (data / "IN.PS").write_bytes(b"AAArec1xxBBBrec2xx")  # two 9-byte records, key=3@0
    cat = DatasetCatalog(workdir=tmp_path / "wd", data_dir=data); (tmp_path/"wd").mkdir()
    dds = (DD("INF", "IN.PS", Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)),
           DD("OUT", "OUT.KSDS", Disp(DispStatus.OLD, DispNormal.KEEP, DispNormal.KEEP)))
    cmds = (DefineCluster(name="OUT.KSDS", key_length=3, key_offset=0, record_size=9),
            Repro(infile_dd="INF", outfile_dd="OUT"))
    rc = run_idcams(cmds, dds, cat)
    assert rc == 0
    # read OUT.KSDS back via the IndexedDriver and confirm BBB record present
    from interpreter.cobol.file_drivers import IndexedDriver
    from interpreter.cobol.file_enums import OpenMode
    drv = IndexedDriver(); drv.open(cat.resolve("OUT.KSDS").path, OpenMode.INPUT, 9, 0, 3)
    assert drv.read_key(b"BBB").data[:3] == "BBB"
```
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** `run_idcams`: maintain `maxcc=0`; dispatch each command. `Delete` → remove DSN from catalog (missing → `maxcc=8`). `DefineCluster` → `catalog.allocate_ksds(name, key_offset, key_length, record_size)`. `Repro` → resolve infile/outfile DDs to datasets (infile via `data_dir` search, outfile is the just-DEFINEd KSDS), run the load above. `IfMaxcc` → if `maxcc <op> value` then `maxcc = set_value`. Return `maxcc`. Functional dispatch (a per-command-type function), no defensive guards.
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** `git add jackal/idcams/executor.py tests/unit/test_idcams_executor.py && git commit -m "feat: IDCAMS executor with REPRO PS->KSDS load (jackal v2 Task 5)"`

---

### Task 6: Wire IDCAMS into the runner; copybook + data-dir threading; CLI

**Files:** Modify `jackal/utilities.py`, `jackal/cobol_step.py`, `jackal/runner.py`, `jackal/cli.py`; Test `tests/unit/test_runner.py`

**Interfaces — Produces:** `UTILITIES["IDCAMS"]`; `run_cobol_step(step, source, catalog, bridge_jar, copybook_dirs)`; `JobRunner(source_dir, bridge_jar, data_dir, copybook_dir)`; `run(job, workdir, seeds)` passes `data_dir` into the catalog.

- [ ] **Step 1: Failing test** — an IDCAMS-only job (in-stream DELETE+DEFINE, no bridge) run through `JobRunner`, asserting the KSDS is created. (Append to `tests/unit/test_runner.py`; build a `Job` with one `IDCAMS` step whose `SYSIN` DD carries `in_stream` DELETE+DEFINE, plus the KSDS DD.)
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement:**
  - `utilities.py`: `def idcams(step, catalog): sysin = next(d for d in step.dds if d.ddname == "SYSIN"); rc = run_idcams(parse_idcams("\n".join(sysin.in_stream) + "\n"), step.dds, catalog); return StepResult(step.name, rc, True)`. Register `"IDCAMS": idcams`.
  - `cobol_step.py`: add `copybook_dirs: list[Path]` param; pass `copybook_dirs=copybook_dirs` to `run(...)` (real `CBACT01C` has `COPY CVACT01Y`/`CODATECN`).
  - `runner.py`: `__init__(self, source_dir, bridge_jar, data_dir, copybook_dir)`; `run` builds `DatasetCatalog(workdir, data_dir=data_dir)`; COBOL branch calls `run_cobol_step(step, source, catalog, bridge_jar, [copybook_dir])`.
  - `cli.py`: `--data-dir` (default `$CARDDEMO_HOME/app/data/EBCDIC`), `--source-dir` (default `$CARDDEMO_HOME/app/cbl`), `--copybook-dir` (default `$CARDDEMO_HOME/app/cpy`); thread into `JobRunner`.
- [ ] **Step 4: Run → pass** the runner unit test.
- [ ] **Step 5: Commit** `git add jackal/utilities.py jackal/cobol_step.py jackal/runner.py jackal/cli.py tests/unit/test_runner.py && git commit -m "feat: wire IDCAMS + copybook/data-dir threading + CLI (jackal v2 Task 6)"`

---

### Task 7: Headline e2e — real ACCTFILE.jcl then READACCT.jcl

**Files:** Create `tests/integration/test_carddemo_acctfile_e2e.py`; Modify `pyproject.toml` (register `carddemo_e2e` marker if not present), `tests/conftest.py` (a `carddemo_home` fixture that skips when `CARDDEMO_HOME` unset)

**Interfaces — Consumes:** everything above.

- [ ] **Step 1: Add the gating fixture** in `tests/conftest.py`:
```python
@pytest.fixture
def carddemo_home():
    home = os.environ.get("CARDDEMO_HOME")
    if not home:
        pytest.skip("CARDDEMO_HOME not set")
    return Path(home)
```
Register the marker in `pyproject.toml` `[tool.pytest.ini_options] markers = ["carddemo_e2e: real CardDemo end-to-end; skipped without CARDDEMO_HOME"]`.
- [ ] **Step 2: Write the e2e test** (`@pytest.mark.carddemo_e2e`): parse `<CARDDEMO_HOME>/app/jcl/ACCTFILE.jcl`, run it via `JobRunner` (data-dir `<CARDDEMO_HOME>/app/data/EBCDIC`, source `<.../app/cbl>`, copybook `<.../app/cpy>`) in a tmp workdir → assert all steps RC 0 and the KSDS dataset exists+nonempty. Then parse+run `READACCT.jcl` in the **same catalog/workdir** (so the KSDS persists), assert `CBACT01C`'s `OUTFILE` exists and its first 11 bytes decode (EBCDIC) to the first account id `00000000001`. Use `EbcdicTable.ascii_to_ebcdic`/`ebcdic_to_ascii` for the assertion. (COBDATFT/CEE3ABD resolve symbolically and don't crash — assert non-date fields only.)
- [ ] **Step 3: Run** `export PROLEAP_BRIDGE_JAR="$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"; export CARDDEMO_HOME="$HOME/code/aws-mainframe-carddemo/app"; uv run pytest tests/integration/test_carddemo_acctfile_e2e.py -v` → PASS. (If `READACCT.jcl` needs the KSDS carried across jobs, share one `DatasetCatalog` across both `JobRunner.run` calls — extend `run` to accept an optional pre-built catalog, or expose the catalog on `JobResult`.)
- [ ] **Step 4: Full suite + format + commit**
```bash
uv run black .
export PROLEAP_BRIDGE_JAR="$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
export CARDDEMO_HOME="$HOME/code/aws-mainframe-carddemo/app"
uv run pytest -q
git add tests/integration/test_carddemo_acctfile_e2e.py tests/conftest.py pyproject.toml
git commit -m "test: real CardDemo ACCTFILE+READACCT e2e (jackal v2 Task 7)"
```

---

## Self-Review
**Spec coverage:** in-stream data + SYSOUT (Task 2) ✓; DD model (Task 1) ✓; IDCAMS DELETE/DEFINE/REPRO/IF-SET (Tasks 4–5) ✓; data-dir resolution + KSDS (Task 3) ✓; REPRO via red-dragon IndexedDriver (Task 5) ✓; IDCAMS utility + copybook/data-dir/CLI (Task 6) ✓; real ACCTFILE→READACCT e2e gated (Task 7) ✓; no-regex/Lark, TDD, FP (all tasks) ✓.

**Cross-task type consistency:** `DD.in_stream: tuple[str,...]`/`sysout: bool`; `DatasetOrg{PS,KSDS}`; `Dataset.org/key_offset/key_length/record_size`; `allocate_ksds(dsn,key_offset,key_length,record_size)`; commands `Delete/DefineCluster/Repro/IfMaxcc`; `parse_idcams(str)->tuple`; `run_idcams(commands, step_dds, catalog)->int`; `JobRunner(source_dir,bridge_jar,data_dir,copybook_dir)`; `run_cobol_step(...,copybook_dirs)`. Consistent.

**Known follow-ups (file after v2):** SYSOUT capture is parsed but not surfaced (messages discarded) — fine for the milestone; carry the KSDS across the two jobs via a shared catalog (Task 7 Step 3 handles it); COBDATFT/CEE3ABD remain symbolic (correctness ticket, not a blocker).
```
