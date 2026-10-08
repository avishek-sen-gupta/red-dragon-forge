# JCL PROC Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve and inline JCL `EXEC PROC=` calls — symbol substitution, DD-qualified overriding, recursive nesting — as one shared pass consumed by both the JCL execution engine (`runner.py`) and the knowledge-graph extractor (`jcl_graph.py`), proven against the real CardDemo corpus (`TRANREPT.jcl` → `REPROC.prc` / `TRANREPT.prc`), not just synthetic fixtures.

**Architecture:** Parse everything (the outer job, and each referenced `.prc` file) through the existing, unmodified `jcl-bridge` grammar — never a bespoke text scanner. `.prc` files parse via the grammar's existing (but currently Java-side-unhandled) `procJCL` top-level alternative. `expand_procs(job, proclib_dirs) -> Job` then works entirely on the resulting structured `Job`/`Step`/`ProcDef` dataclasses: symbol substitution walks `Literal`/`Symbol` parts (the typed value from the prior JCL-symbolic-value-type plan — see Global Constraints), DD-qualified overriding is a dataclass merge keyed by dotted `stepname.ddname` splitting (a plain, non-regex `str.split` on a delimiter the grammar itself already treats as structurally significant), and nesting is ordinary recursion. `SET` statements are explicitly deferred (forge-6qr) — verified absent from both real CardDemo PROCs.

**Tech Stack:** Python 3.13, Java 17 (ANTLR4, Gson), pytest.

## Global Constraints

- TDD throughout: write the failing test, run it, watch it fail, implement, run it again, watch it pass, commit.
- No regex, no string-pattern inference for symbol detection — classification comes only from the `SYMBOLIC` ANTLR token type, exactly as established by the prior plan (`jackal/docs/superpowers/plans/2026-07-08-jcl-symbolic-value-type.md`, already merged: `jackal/jackal/value_parts.py`'s `Literal`/`Symbol`/`Value`/`resolve`/`literal` and `DirectDSN.name`/`Step.parm`'s `Value` typing already exist — this plan builds on them, does not reintroduce them).
- `SET` statement support is explicitly out of scope (filed as forge-6qr) — do not implement step/SET interleaving in this plan.
- Every task in this plan is additive to the existing JSON contract and Python model (new fields with safe defaults, new optional parameters) — no existing consumer's behavior changes unless it explicitly opts in by passing `proclib_dirs`. This means, unlike the prior plan, no task here should need combining to keep the pre-commit hook's full-suite gate green — if a task's own change breaks an existing test, stop and reconsider the task boundary rather than proceeding.
- Run tests from the repo root: `cd ~/code/red-dragon-forge`.
- `JCL_BRIDGE_JAR` must be set for every task that runs a real-bridge test — rebuild if stale: `cd jackal/jcl-bridge && mvn -DskipTests package -q`.
- `PROLEAP_BRIDGE_JAR` is needed only for the final full-suite/CardDemo-graph verification task (Task 9), not for any PROC-expansion-specific test.
- `CARDDEMO_HOME` must be set to `jackal/third-party/carddemo/app` for the real-corpus integration test (Task 5) — the existing `carddemo_home` pytest fixture (`jackal/tests/conftest.py`) already skips cleanly if unset; do not add a new fixture.

---

## File Structure

| File | Responsibility |
|---|---|
| `jackal/jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java` | Serializes `procJCL` (name/defaults/steps) and `proc_parms` (caller overrides on `EXEC PROC=` steps) |
| `jackal/jackal/model.py` | `ProcDef` dataclass; `Step.proc_parms: dict[str, Value]` |
| `jackal/jackal/jcl/bridge_parser.py` | Deserializes the new JSON shapes into `ProcDef`/`Step.proc_parms` |
| `jackal/jackal/jcl/parser.py` | `parse_proc(text: str) -> ProcDef` — mirrors the existing `parse_jcl` |
| `jackal/jackal/jcl/proc_expand.py` (new) | `expand_procs(job, proclib_dirs) -> Job` — the core resolve/substitute/merge/recurse algorithm |
| `jackal/jackal/jcl_graph.py` | `extract_jcl_graph` gains an optional `proclib_dirs` parameter; qualified step ids + `attrs={"proc": ...}` for expanded steps |
| `jackal/jackal/runner.py` | `JobRunner` gains an optional `proclib_dirs` parameter |
| `knowledge_graph/build_carddemo_graph.py` | Passes the real CardDemo `app/proc` directory as `proclib_dirs` |

---

## Task 1: `JclSerializer.java` — `procJCL` + `proc_parms`

**Files:**
- Modify: `jackal/jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java`

**Interfaces:**
- Produces new JSON shapes: a `.prc` document (parsed via the grammar's `procJCL` alternative) now returns `{"name": "REPROC", "defaults": {"CNTLLIB": [...]}, "steps": [...]}` instead of the current `{"name": "", "steps": []}` fallback. A step's JSON gains `"proc_parms": {"CNTLLIB": [...]}`(empty object `{}` if the step has no `EXEC PROC=...,SYM=value` overrides — including every ordinary `EXEC PGM=` step). Both use the same `{"type": "Literal"|"Symbol", "name": ...}` part-array shape `buildValueParts` already produces for `dsn`/`parm`.

This task has no Python-side test — verified by direct JAR invocation, exactly as the prior plan's Task 2 was.

- [ ] **Step 1: Confirm current (pre-change) behavior**

Build the JAR if stale: `cd jackal/jcl-bridge && mvn -DskipTests package -q`

```bash
cat > /tmp/procjcl.jcl << 'EOF'
//REPROC PROC
//PRC001 EXEC PGM=IDCAMS
//FILEIN  DD DISP=SHR,DSN=NULLFILE
//SYSIN   DD DISP=SHR,DSN=&CNTLLIB(REPROCT)
// PEND
EOF
java -jar ~/code/red-dragon-forge/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar < /tmp/procjcl.jcl
```
Expected (current, pre-change): `{"name":"","steps":[]}` — the existing `execJCL`-only fallback.

```bash
cat > /tmp/execprocparm.jcl << 'EOF'
//J JOB 1
//STEP1 EXEC PROC=REPROC,CNTLLIB=AWS.M2.CARDDEMO.CNTL
EOF
java -jar ~/code/red-dragon-forge/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar < /tmp/execprocparm.jcl
```
Expected (current, pre-change): the step JSON has no `"proc_parms"` key at all — the `CNTLLIB=AWS.M2.CARDDEMO.CNTL` override is silently dropped.

- [ ] **Step 2: Add `buildProcJCL` and the `procJCL` branch in `build`**

Locate `JobBuilder.build`, the block that currently does (near the top, after locating `execJCL`):
```java
            JCLParser.ExecJCLContext execJCL = findChild(jcl, JCLParser.ExecJCLContext.class);
            if (execJCL == null) {
                job.addProperty("name", "");
                job.add("steps", new JsonArray());
                return job;
            }
```

Replace it with:
```java
            JCLParser.ExecJCLContext execJCL = findChild(jcl, JCLParser.ExecJCLContext.class);
            if (execJCL == null) {
                JCLParser.ProcJCLContext procJCL = findChild(jcl, JCLParser.ProcJCLContext.class);
                if (procJCL != null) {
                    return buildProcJCL(procJCL);
                }
                job.addProperty("name", "");
                job.add("steps", new JsonArray());
                return job;
            }
```

Add this new method to `JobBuilder` (place it directly after `build`, before `buildStep`):

```java
        /**
         * Build the JSON for a bare PROC document (a .prc file: //NAME PROC
         * ... // PEND, no JOB card) — the grammar's procJCL alternative,
         * previously unhandled (build() fell through to the empty-job
         * fallback for it). Reuses buildStep for its steps, identically to
         * execJCL's own step handling.
         */
        private JsonObject buildProcJCL(JCLParser.ProcJCLContext ctx) {
            JsonObject proc = new JsonObject();

            JCLParser.ProcStatementContext procStmt =
                    findChild(ctx, JCLParser.ProcStatementContext.class);
            String procName = "";
            JsonObject defaults = new JsonObject();
            if (procStmt != null) {
                JCLParser.ProcNameContext nameCtx =
                        findChild(procStmt, JCLParser.ProcNameContext.class);
                if (nameCtx != null) {
                    procName = nameCtx.getText();
                }
                List<JCLParser.DefineSymbolicParameterContext> defs = new ArrayList<>();
                collectAll(procStmt, JCLParser.DefineSymbolicParameterContext.class, defs);
                for (JCLParser.DefineSymbolicParameterContext d : defs) {
                    String paramName = null;
                    JCLParser.KeywordOrSymbolicContext valueCtx = null;
                    for (int i = 0; i < d.getChildCount(); i++) {
                        ParseTree child = d.getChild(i);
                        if (child instanceof TerminalNode
                                && ((TerminalNode) child).getSymbol().getType()
                                        == JCLLexer.PROC_PARM_NAME) {
                            paramName = child.getText();
                        } else if (child instanceof JCLParser.KeywordOrSymbolicContext) {
                            valueCtx = (JCLParser.KeywordOrSymbolicContext) child;
                        }
                    }
                    if (paramName != null) {
                        defaults.add(
                                paramName,
                                valueCtx != null ? buildValueParts(valueCtx) : new JsonArray());
                    }
                }
            }
            proc.addProperty("name", procName);
            proc.add("defaults", defaults);

            JsonArray steps = new JsonArray();
            for (int i = 0; i < ctx.getChildCount(); i++) {
                ParseTree child = ctx.getChild(i);
                if (child instanceof JCLParser.JclStepContext) {
                    steps.add(buildStep((JCLParser.JclStepContext) child));
                }
            }
            proc.add("steps", steps);
            return proc;
        }
```

- [ ] **Step 3: Add `proc_parms` to `buildStep`**

Locate the end of `buildStep`, just before the `// DD statements — ddStatementAmalgamation children of jclStep` comment. Insert:

```java
            // PROC parm overrides (EXEC PROC=NAME,SYM=val,...) — execProcParm
            // children of execProcStatement, empty object for an ordinary
            // EXEC PGM= step or a PROC call with no overrides.
            JsonObject procParms = new JsonObject();
            if (execStmt != null) {
                JCLParser.ExecProcStatementContext procStmtCtx =
                        findChild(execStmt, JCLParser.ExecProcStatementContext.class);
                if (procStmtCtx != null) {
                    List<JCLParser.ExecProcParmContext> overrides = new ArrayList<>();
                    collectAll(procStmtCtx, JCLParser.ExecProcParmContext.class, overrides);
                    for (JCLParser.ExecProcParmContext o : overrides) {
                        String paramName = null;
                        JCLParser.KeywordOrSymbolicContext valueCtx = null;
                        for (int i = 0; i < o.getChildCount(); i++) {
                            ParseTree child = o.getChild(i);
                            if (child instanceof TerminalNode
                                    && ((TerminalNode) child).getSymbol().getType()
                                            == JCLLexer.EXEC_PROC_PARM) {
                                paramName = child.getText();
                            } else if (child instanceof JCLParser.KeywordOrSymbolicContext) {
                                valueCtx = (JCLParser.KeywordOrSymbolicContext) child;
                            }
                        }
                        if (paramName != null) {
                            procParms.add(
                                    paramName,
                                    valueCtx != null ? buildValueParts(valueCtx) : new JsonArray());
                        }
                    }
                }
            }
            step.add("proc_parms", procParms);
```

- [ ] **Step 4: Rebuild the JAR and re-run both manual checks**

```bash
cd jackal/jcl-bridge && mvn -DskipTests package -q
java -jar ~/code/red-dragon-forge/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar < /tmp/procjcl.jcl
java -jar ~/code/red-dragon-forge/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar < /tmp/execprocparm.jcl
```
Expected first command:
```json
{"name":"REPROC","defaults":{},"steps":[{"name":"PRC001","pgm":"IDCAMS","cond":[],"parm":[],"dds":[{"ddname":"FILEIN","dsn":[{"type":"Literal","name":"NULLFILE"}],"disp_words":["SHR"],"in_stream":[],"sysout":false,"dummy":false},{"ddname":"SYSIN","dsn":[{"type":"Symbol","name":"CNTLLIB"},{"type":"Literal","name":"(REPROCT)"}],"disp_words":["SHR"],"in_stream":[],"sysout":false,"dummy":false}],"proc_parms":{}}]}
```
(field order within a JSON object is not guaranteed by Gson — compare by structure, not exact string equality, when verifying by eye.)

Expected second command: the step's JSON now includes `"proc_parms":{"CNTLLIB":[{"type":"Literal","name":"AWS.M2.CARDDEMO.CNTL"}]}`.

If either output doesn't match, do not proceed — re-examine the grammar context walk (most likely culprit: `PROC_PARM_NAME`/`EXEC_PROC_PARM` token type constants, or the child-iteration order assumption) before continuing.

- [ ] **Step 5: Commit**

```bash
git add jackal/jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java
git commit -m "feat(jcl-bridge): serialize procJCL documents and EXEC PROC= caller overrides"
```

---

## Task 2: `model.py` — `ProcDef` and `Step.proc_parms`

**Files:**
- Modify: `jackal/jackal/model.py`
- Modify: `jackal/tests/unit/test_model.py`

**Interfaces:**
- Consumes: `jackal.value_parts.Value` (already exists).
- Produces: `ProcDef(name: str, defaults: dict[str, Value], steps: tuple[Step, ...])`; `Step.proc_parms: dict[str, Value] = field(default_factory=dict)`.

- [ ] **Step 1: Write the failing test first**

Add to `jackal/tests/unit/test_model.py` (after the existing imports, add `from jackal.value_parts import literal`; then append this test function):

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_step_proc_parms_defaults_empty():
    step = Step(name="S", pgm="P", dds=())
    assert step.proc_parms == {}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_proc_def_construction():
    from jackal.model import ProcDef

    inner = Step(name="PRC001", pgm="IDCAMS", dds=())
    proc = ProcDef(name="REPROC", defaults={"CNTLLIB": literal("DEFAULT.LIB")}, steps=(inner,))
    assert proc.name == "REPROC"
    assert proc.defaults == {"CNTLLIB": literal("DEFAULT.LIB")}
    assert proc.steps == (inner,)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run --no-sync python -m pytest jackal/tests/unit/test_model.py -k "proc_parms or proc_def" -v
```
Expected: FAIL — `Step.proc_parms` doesn't exist (`TypeError`), and `ProcDef` doesn't exist (`ImportError`).

- [ ] **Step 3: Update `model.py`**

Change the import line (currently `from jackal.dsn import DSN`) to:
```python
from jackal.dsn import DSN
from jackal.value_parts import Value
```
(this exact import already exists from the prior plan — do not duplicate it if already present; this task only needs to confirm it's there.)

Change the `Step` dataclass (currently ending with `parm: Value = ()`) to add one field:
```python
@dataclass(frozen=True)
class Step:
    name: str
    pgm: str
    dds: tuple[DD, ...]
    conds: tuple[Cond, ...] = ()
    parm: Value = ()
    proc_parms: dict[str, Value] = field(default_factory=dict)
```
This requires `field` to be imported — change the dataclasses import line from `from dataclasses import dataclass` to `from dataclasses import dataclass, field`.

Add a new dataclass after `Job`:
```python
@dataclass(frozen=True)
class ProcDef:
    name: str
    defaults: dict[str, Value]
    steps: tuple[Step, ...]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run --no-sync python -m pytest jackal/tests/unit/test_model.py -v
```
Expected: all pass (existing tests + 2 new ones).

- [ ] **Step 5: Commit**

```bash
git add jackal/jackal/model.py jackal/tests/unit/test_model.py
git commit -m "feat: add ProcDef and Step.proc_parms to the JCL model"
```

---

## Task 3: `bridge_parser.py` + `parser.py` — `parse_proc`

**Files:**
- Modify: `jackal/jackal/jcl/bridge_parser.py`
- Modify: `jackal/jackal/jcl/parser.py`
- Modify: `jackal/tests/unit/test_jcl_bridge_parser.py`
- Modify: `jackal/tests/integration/test_jcl_bridge_jar.py`

**Interfaces:**
- Consumes: `ProcDef`, `Step.proc_parms` (Task 2); the `procJCL`/`proc_parms` JSON shapes (Task 1).
- Produces: `JclBridgeParser.parse_proc(text: str) -> ProcDef`; module-level `jackal.jcl.parser.parse_proc(text: str) -> ProcDef` (mirrors the existing `parse_jcl`).

- [ ] **Step 1: Write the failing tests first**

Add to `jackal/tests/unit/test_jcl_bridge_parser.py` (append; the file already imports `json`, `pytest`, `DirectDSN`, `JclBridgeParser`/`JclParseError`, `literal` — add `Symbol` to the `jackal.value_parts` import line):

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_proc_builds_procdef_from_bridge_json():
    out = json.dumps(
        {
            "name": "REPROC",
            "defaults": {},
            "steps": [
                {
                    "name": "PRC001",
                    "pgm": "IDCAMS",
                    "cond": [],
                    "parm": [],
                    "dds": [
                        {
                            "ddname": "SYSIN",
                            "dsn": [
                                {"type": "Symbol", "name": "CNTLLIB"},
                                {"type": "Literal", "name": "(REPROCT)"},
                            ],
                            "disp_words": ["SHR"],
                            "in_stream": [],
                            "sysout": False,
                        }
                    ],
                    "proc_parms": {},
                }
            ],
        }
    )
    runner = _FakeRunner(out=out)
    proc = JclBridgeParser(runner, "jcl.jar").parse_proc("//REPROC PROC\n")
    assert proc.name == "REPROC"
    assert proc.defaults == {}
    assert proc.steps[0].name == "PRC001"
    assert proc.steps[0].dds[0].dsn == DirectDSN((Symbol("CNTLLIB"), Literal("(REPROCT)")))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_proc_builds_defaults():
    out = json.dumps(
        {
            "name": "REPROC",
            "defaults": {"CNTLLIB": [{"type": "Literal", "name": "DEFAULT.LIB"}]},
            "steps": [],
        }
    )
    runner = _FakeRunner(out=out)
    proc = JclBridgeParser(runner, "jcl.jar").parse_proc("//REPROC PROC CNTLLIB=DEFAULT.LIB\n")
    assert proc.defaults == {"CNTLLIB": literal("DEFAULT.LIB")}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_step_from_json_builds_proc_parms():
    out = json.dumps(
        {
            "name": "J",
            "steps": [
                {
                    "name": "S",
                    "pgm": "REPROC",
                    "dds": [],
                    "proc_parms": {"CNTLLIB": [{"type": "Literal", "name": "AWS.M2.CARDDEMO.CNTL"}]},
                }
            ],
        }
    )
    runner = _FakeRunner(out=out)
    job = JclBridgeParser(runner, "jcl.jar").parse("//J JOB 1\n")
    assert job.steps[0].proc_parms == {"CNTLLIB": literal("AWS.M2.CARDDEMO.CNTL")}
```

(this last test needs `Literal` imported too — the file's `jackal.value_parts` import line should read `from jackal.value_parts import Literal, Symbol, literal`.)

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run --no-sync python -m pytest jackal/tests/unit/test_jcl_bridge_parser.py -v
```
Expected: the three new tests FAIL — `AttributeError: 'JclBridgeParser' object has no attribute 'parse_proc'`, and `job.steps[0].proc_parms` is `{}` (the JSON's `proc_parms` key isn't read yet).

- [ ] **Step 3: Update `bridge_parser.py`**

Change the import line (currently `from jackal.model import Cond, CondOp, DD, Disp, DispNormal, DispStatus, Job, Step`) to add `ProcDef`:
```python
from jackal.model import Cond, CondOp, DD, Disp, DispNormal, DispStatus, Job, ProcDef, Step
```

Change `_step_from_json` (currently ending `parm=_value_from_json(s.get("parm", [])),`) to add `proc_parms`:
```python
def _step_from_json(s: dict) -> Step:
    return Step(
        name=s["name"],
        pgm=s["pgm"],
        dds=tuple(_dd_from_json(d) for d in s["dds"]),
        conds=tuple(_cond_from_json(c) for c in s.get("cond", ())),
        parm=_value_from_json(s.get("parm", [])),
        proc_parms={
            k: _value_from_json(v) for k, v in s.get("proc_parms", {}).items()
        },
    )
```

Add a new function after `_job_from_json`:
```python
def _proc_from_json(data: dict) -> ProcDef:
    return ProcDef(
        name=data["name"],
        defaults={
            k: _value_from_json(v) for k, v in data.get("defaults", {}).items()
        },
        steps=tuple(_step_from_json(s) for s in data["steps"]),
    )
```

Add a new method to `JclBridgeParser`, directly after `parse`:
```python
    def parse_proc(self, text: str) -> ProcDef:
        command = ["java", "-jar", self._bridge_jar]
        out = self._runner.run(command, text)
        try:
            return _proc_from_json(json.loads(out))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            snippet = out[:120].replace("\n", " ")
            raise JclParseError(
                f"bridge returned malformed/incomplete JSON: {e} — output: {snippet!r}"
            ) from e
```

- [ ] **Step 4: Update `parser.py`**

Read the current file first — it's:
```python
"""JCL parser: text -> Job, via the jcl-bridge JAR (ANTLR mapa grammar)."""

from __future__ import annotations

import os

from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner
from jackal.model import Job


def parse_jcl(text: str) -> Job:
    jar = os.environ["JCL_BRIDGE_JAR"]  # fail loud if unset
    return JclBridgeParser(JclSubprocessRunner(), jar).parse(text)
```

Replace it with:
```python
"""JCL parser: text -> Job, via the jcl-bridge JAR (ANTLR mapa grammar)."""

from __future__ import annotations

import os

from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner
from jackal.model import Job, ProcDef


def parse_jcl(text: str) -> Job:
    jar = os.environ["JCL_BRIDGE_JAR"]  # fail loud if unset
    return JclBridgeParser(JclSubprocessRunner(), jar).parse(text)


def parse_proc(text: str) -> ProcDef:
    """Parse a bare PROC document (.prc file: //NAME PROC ... // PEND, no
    JOB card) via the same jcl-bridge grammar's procJCL alternative."""
    jar = os.environ["JCL_BRIDGE_JAR"]  # fail loud if unset
    return JclBridgeParser(JclSubprocessRunner(), jar).parse_proc(text)
```

- [ ] **Step 5: Run the unit tests to verify they pass**

```bash
uv run --no-sync python -m pytest jackal/tests/unit/test_jcl_bridge_parser.py -v
```
Expected: all pass.

- [ ] **Step 6: Add and run a real-bridge integration test**

Add to `jackal/tests/integration/test_jcl_bridge_jar.py` (append; add `from jackal.jcl.bridge_parser import ...` already imports `JclBridgeParser`, `JclSubprocessRunner` — reuse them):

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_proc_document(jcl_bridge_jar):
    jcl = (
        "//REPROC PROC\n"
        "//PRC001 EXEC PGM=IDCAMS\n"
        "//FILEIN  DD DISP=SHR,DSN=NULLFILE\n"
        "//SYSIN   DD DISP=SHR,DSN=&CNTLLIB(REPROCT)\n"
        "// PEND\n"
    )
    proc = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse_proc(jcl)
    assert proc.name == "REPROC"
    assert proc.defaults == {}
    assert [s.name for s in proc.steps] == ["PRC001"]
    assert proc.steps[0].dds[1].dsn == DirectDSN((Symbol("CNTLLIB"), Literal("(REPROCT)")))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_exec_proc_parm_override(jcl_bridge_jar):
    jcl = "//J JOB 1\n//STEP1 EXEC PROC=REPROC,CNTLLIB=AWS.M2.CARDDEMO.CNTL\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].proc_parms == {"CNTLLIB": literal("AWS.M2.CARDDEMO.CNTL")}
```

Run:
```bash
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest jackal/tests/integration/test_jcl_bridge_jar.py -v
```
Expected: all pass (9 tests: 7 existing + 2 new).

- [ ] **Step 7: Commit**

```bash
git add jackal/jackal/jcl/bridge_parser.py jackal/jackal/jcl/parser.py \
        jackal/tests/unit/test_jcl_bridge_parser.py jackal/tests/integration/test_jcl_bridge_jar.py
git commit -m "feat: add parse_proc() and Step.proc_parms deserialization"
```

---

## Task 4: `proc_expand.py` — the core algorithm

**Files:**
- Create: `jackal/jackal/jcl/proc_expand.py`
- Test: `jackal/tests/unit/test_proc_expand.py`
- Fixtures: `jackal/tests/unit/fixtures/proc/REPROC.prc`, `jackal/tests/unit/fixtures/proc/CALLER.prc` (synthetic, small)

**Interfaces:**
- Consumes: `Job`, `Step`, `DD`, `ProcDef` (model.py); `jackal.jcl.parser.parse_proc`; `jackal.value_parts.{Literal, Symbol, Value}`; `jackal.dsn.DirectDSN`.
- Produces: `expand_procs(job: Job, proclib_dirs: Sequence[Path]) -> Job`; `class ProcExpansionError(Exception)`.

- [ ] **Step 1: Write the failing tests first**

Create `jackal/tests/unit/fixtures/proc/REPROC.prc`:
```
//REPROC PROC
//PRC001 EXEC PGM=IDCAMS
//FILEIN  DD DISP=SHR,DSN=NULLFILE
//FILEOUT DD DISP=SHR,DSN=NULLFILE
//SYSIN   DD DISP=SHR,DSN=&CNTLLIB(REPROCT)
// PEND
```

Create `jackal/tests/unit/fixtures/proc/CALLER.prc`:
```
//CALLER PROC
//STEP01R EXEC PROC=REPROC,CNTLLIB=AWS.M2.CARDDEMO.CNTL
// PEND
```

Create `jackal/tests/unit/test_proc_expand.py`:

```python
"""Unit tests for expand_procs()."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.dsn import DirectDSN
from jackal.jcl.proc_expand import ProcExpansionError, expand_procs
from jackal.model import DD, Cond, CondOp, Disp, DispNormal, DispStatus, Job, Step
from jackal.value_parts import Literal, Symbol, literal

_FIXTURES = Path(__file__).parent / "fixtures" / "proc"
_DEFAULT_DISP = Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)


@pytest.fixture(autouse=True)
def _require_jcl_bridge(jcl_bridge_jar):
    """expand_procs parses referenced .prc files via parse_proc; ensure JCL_BRIDGE_JAR is set."""


def _step(name: str, pgm: str, dds: tuple[DD, ...] = (), proc_parms=None) -> Step:
    return Step(name=name, pgm=pgm, dds=dds, proc_parms=proc_parms or {})


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_non_proc_step_passes_through_unchanged():
    step = _step("STEP1", "IEFBR14")
    job = Job(name="J", steps=(step,))
    result = expand_procs(job, proclib_dirs=[_FIXTURES])
    assert result.steps == (step,)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_proc_call_expands_to_qualified_inner_step():
    step = _step("STEP05R", "REPROC", proc_parms={"CNTLLIB": literal("AWS.M2.CARDDEMO.CNTL")})
    job = Job(name="TRANREPT", steps=(step,))
    result = expand_procs(job, proclib_dirs=[_FIXTURES])
    assert [s.name for s in result.steps] == ["STEP05R.PRC001"]
    assert result.steps[0].pgm == "IDCAMS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_proc_symbol_substituted_from_caller_override():
    step = _step("STEP05R", "REPROC", proc_parms={"CNTLLIB": literal("AWS.M2.CARDDEMO.CNTL")})
    job = Job(name="TRANREPT", steps=(step,))
    result = expand_procs(job, proclib_dirs=[_FIXTURES])
    sysin = next(d for d in result.steps[0].dds if d.ddname == "SYSIN")
    assert sysin.dsn == DirectDSN((Literal("AWS.M2.CARDDEMO.CNTL"), Literal("(REPROCT)")))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_missing_symbol_raises():
    step = _step("STEP05R", "REPROC")  # no CNTLLIB override, REPROC.prc has no default either
    job = Job(name="TRANREPT", steps=(step,))
    with pytest.raises(ProcExpansionError, match="CNTLLIB"):
        expand_procs(job, proclib_dirs=[_FIXTURES])


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_qualified_override_replaces_placeholder():
    outer_dd = DD(
        ddname="PRC001.FILEIN",
        dsn=DirectDSN(literal("AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS")),
        disp=_DEFAULT_DISP,
    )
    step = _step(
        "STEP05R", "REPROC",
        dds=(outer_dd,),
        proc_parms={"CNTLLIB": literal("AWS.M2.CARDDEMO.CNTL")},
    )
    job = Job(name="TRANREPT", steps=(step,))
    result = expand_procs(job, proclib_dirs=[_FIXTURES])
    filein = next(d for d in result.steps[0].dds if d.ddname == "FILEIN")
    assert filein.dsn == DirectDSN(literal("AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dd_qualified_override_unmatched_step_name_is_not_applied():
    # A qualified override for a step name the PROC doesn't have is simply
    # never matched — it stays on the outer step's own dds, unconsumed.
    outer_dd = DD(
        ddname="NOPE.FILEIN",
        dsn=DirectDSN(literal("SOME.DATASET")),
        disp=_DEFAULT_DISP,
    )
    step = _step(
        "STEP05R", "REPROC",
        dds=(outer_dd,),
        proc_parms={"CNTLLIB": literal("AWS.M2.CARDDEMO.CNTL")},
    )
    job = Job(name="TRANREPT", steps=(step,))
    result = expand_procs(job, proclib_dirs=[_FIXTURES])
    filein = next(d for d in result.steps[0].dds if d.ddname == "FILEIN")
    assert filein.dsn == DirectDSN(literal("NULLFILE"))  # unchanged placeholder


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_nested_proc_call_expands_recursively():
    step = _step("STEP01R", "CALLER")
    job = Job(name="OUTER", steps=(step,))
    result = expand_procs(job, proclib_dirs=[_FIXTURES])
    # CALLER.prc's own STEP01R calls REPROC with CNTLLIB=AWS.M2.CARDDEMO.CNTL
    assert [s.name for s in result.steps] == ["STEP01R.STEP01R.PRC001"]
    assert result.steps[0].pgm == "IDCAMS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_circular_proc_reference_raises(tmp_path):
    (tmp_path / "SELFCALL.prc").write_text(
        "//SELFCALL PROC\n//S1 EXEC PROC=SELFCALL\n// PEND\n"
    )
    step = _step("STEP1", "SELFCALL")
    job = Job(name="J", steps=(step,))
    with pytest.raises(ProcExpansionError, match="Circular"):
        expand_procs(job, proclib_dirs=[tmp_path])


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_job_steps_flatten_in_order_around_a_proc_call():
    before = _step("STEP01", "IEFBR14")
    proc_call = _step("STEP05R", "REPROC", proc_parms={"CNTLLIB": literal("X")})
    after = _step("STEP10", "IEFBR14")
    job = Job(name="J", steps=(before, proc_call, after))
    result = expand_procs(job, proclib_dirs=[_FIXTURES])
    assert [s.name for s in result.steps] == ["STEP01", "STEP05R.PRC001", "STEP10"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest jackal/tests/unit/test_proc_expand.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'jackal.jcl.proc_expand'`.

- [ ] **Step 3: Write the implementation**

```python
"""expand_procs() — resolve and inline JCL EXEC PROC= calls: symbol
substitution, DD-qualified overriding, recursive nesting. Parses everything
(the outer job's already-parsed Step, and each referenced .prc file) through
the real jcl-bridge grammar — never a bespoke text scanner. See
jackal/docs/superpowers/specs/2026-07-08-jcl-proc-expansion-design.md.

SET statements are not supported (forge-6qr) — verified absent from every
real PROC in the CardDemo corpus.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from jackal.dsn import DirectDSN
from jackal.jcl.parser import parse_proc
from jackal.model import DD, Job, Step
from jackal.value_parts import Literal, Symbol, Value


class ProcExpansionError(Exception):
    """Raised when PROC resolution/inlining fails: PROC not found, an
    unbound symbol, or a circular PROC reference."""


def _resolve_proc_path(name: str, proclib_dirs: Sequence[Path]) -> Path | None:
    for proclib_dir in proclib_dirs:
        candidate = proclib_dir / f"{name}.prc"
        if candidate.is_file():
            return candidate
    return None


def _substitute(value: Value, symbols: dict[str, Value]) -> Value:
    parts: list[Literal] = []
    for part in value:
        match part:
            case Literal():
                parts.append(part)
            case Symbol(name=n):
                if n not in symbols:
                    raise ProcExpansionError(f"Unbound symbol '&{n}'")
                parts.extend(symbols[n])
    return tuple(parts)


def _substitute_dd(dd: DD, symbols: dict[str, Value]) -> DD:
    match dd.dsn:
        case DirectDSN(name=n):
            return DD(dd.ddname, DirectDSN(_substitute(n, symbols)), dd.disp, dd.in_stream, dd.sysout)
        case _:
            return dd


def _merge_dd_overrides(inner_step: Step, outer_dds: tuple[DD, ...], single_step: bool) -> Step:
    """Apply qualified (stepname.ddname) DD overrides from the outer step's
    own dds onto this inner step — full replace of a matching ddname, append
    if new. A single-step PROC also accepts an unqualified override."""
    targeted: dict[str, DD] = {}
    for dd in outer_dds:
        if "." in dd.ddname:
            qualifier, real_ddname = dd.ddname.split(".", 1)
            if qualifier == inner_step.name:
                targeted[real_ddname] = DD(real_ddname, dd.dsn, dd.disp, dd.in_stream, dd.sysout)
        elif single_step:
            targeted[dd.ddname] = dd

    if not targeted:
        return inner_step

    new_dds: list[DD] = []
    seen: set[str] = set()
    for dd in inner_step.dds:
        if dd.ddname in targeted:
            new_dds.append(targeted[dd.ddname])
            seen.add(dd.ddname)
        else:
            new_dds.append(dd)
    for ddname, dd in targeted.items():
        if ddname not in seen:
            new_dds.append(dd)

    return Step(
        inner_step.name, inner_step.pgm, tuple(new_dds),
        inner_step.conds, inner_step.parm, inner_step.proc_parms,
    )


def _expand_step(step: Step, proclib_dirs: Sequence[Path], stack: frozenset[str]) -> list[Step]:
    proc_path = _resolve_proc_path(step.pgm, proclib_dirs)
    if proc_path is None:
        return [step]

    if step.pgm in stack:
        raise ProcExpansionError(
            f"Circular PROC reference: {' -> '.join((*stack, step.pgm))}"
        )

    proc_def = parse_proc(proc_path.read_text())
    symbols: dict[str, Value] = dict(proc_def.defaults)
    symbols.update(step.proc_parms)
    single_step = len(proc_def.steps) == 1

    expanded: list[Step] = []
    for inner_step in proc_def.steps:
        merged = _merge_dd_overrides(inner_step, step.dds, single_step)
        substituted = Step(
            name=f"{step.name}.{merged.name}",
            pgm=merged.pgm,
            dds=tuple(_substitute_dd(dd, symbols) for dd in merged.dds),
            conds=merged.conds,
            parm=_substitute(merged.parm, symbols),
            proc_parms=merged.proc_parms,
        )
        expanded.extend(_expand_step(substituted, proclib_dirs, stack | {step.pgm}))
    return expanded


def expand_procs(job: Job, proclib_dirs: Sequence[Path]) -> Job:
    """Return a new Job with every EXEC PROC= step replaced by its real,
    recursively-expanded, symbol-substituted, DD-merged inner steps. A step
    whose pgm doesn't resolve to a {proclib_dir}/{pgm}.prc file is returned
    unchanged — this function is a safe no-op for a job with no PROC calls."""
    new_steps: list[Step] = []
    for step in job.steps:
        new_steps.extend(_expand_step(step, proclib_dirs, frozenset()))
    return Job(name=job.name, steps=tuple(new_steps), cond=job.cond)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest jackal/tests/unit/test_proc_expand.py -v
```
Expected: 9 passed.

Note on `test_nested_proc_call_expands_recursively`'s expected name `"STEP01R.STEP01R.PRC001"`: `CALLER.prc`'s own inner step is named `STEP01R` (matching `TRANREPT.prc`'s real structure), and the outer call is also named `STEP01R` in this fixture — the double qualification is correct given the fixture's naming, not a bug. If this reads confusingly during implementation, that's expected; it is exercising real double-nesting qualification, not a fixture mistake.

- [ ] **Step 5: Commit**

```bash
git add jackal/jackal/jcl/proc_expand.py jackal/tests/unit/test_proc_expand.py jackal/tests/unit/fixtures/proc/
git commit -m "feat: add expand_procs() — resolve, substitute, merge, recurse JCL PROC calls"
```

---

## Task 5: Real CardDemo corpus integration test

**Files:**
- Test: `jackal/tests/integration/test_proc_expansion_carddemo_e2e.py`

**Interfaces:**
- Consumes: `expand_procs` (Task 4); `parse_jcl` (existing); the `carddemo_home` pytest fixture (existing, `jackal/tests/conftest.py`).

This task exists specifically because a prior session's ad hoc investigation found `TRANREPT.jcl`'s `STEP05R EXEC PROC=REPROC,CNTLLIB=AWS.M2.CARDDEMO.CNTL` unexpanded in the knowledge graph — this test proves the fix against that exact real file, not just synthetic fixtures.

- [ ] **Step 1: Write the failing test first**

```python
"""End-to-end proof: expand_procs() against the real CardDemo TRANREPT.jcl,
REPROC.prc, and TRANREPT.prc — not synthetic fixtures. Skips cleanly without
CARDDEMO_HOME (see jackal/tests/conftest.py's carddemo_home fixture)."""

from __future__ import annotations

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.dsn import DirectDSN
from jackal.jcl.parser import parse_jcl
from jackal.jcl.proc_expand import expand_procs
from jackal.value_parts import literal


@pytest.fixture(autouse=True)
def _require_jcl_bridge(jcl_bridge_jar):
    """parse_jcl/parse_proc shell to the bridge; ensure JCL_BRIDGE_JAR is set."""


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_tranrept_jcl_expands_reproc_call(carddemo_home):
    jcl_text = (carddemo_home / "jcl" / "TRANREPT.jcl").read_text()
    job = parse_jcl(jcl_text)

    # Before expansion: STEP05R's pgm is literally "REPROC" (the bug this
    # feature fixes — a graph/runner consumer would treat REPROC as if it
    # were a real executable).
    step05r = next(s for s in job.steps if s.name == "STEP05R")
    assert step05r.pgm == "REPROC"
    assert step05r.proc_parms == {"CNTLLIB": literal("AWS.M2.CARDDEMO.CNTL")}

    expanded = expand_procs(job, proclib_dirs=[carddemo_home / "proc"])

    # After expansion: STEP05R is gone, replaced by its real qualified inner
    # step running the real program (IDCAMS), plus STEP10R (a plain
    # EXEC PGM=CBTRN03C step, unaffected — it was never a PROC call).
    names = [s.name for s in expanded.steps]
    assert "STEP05R" not in names
    assert "STEP05R.PRC001" in names
    assert "STEP10R" in names

    prc001 = next(s for s in expanded.steps if s.name == "STEP05R.PRC001")
    assert prc001.pgm == "IDCAMS"

    step10r = next(s for s in expanded.steps if s.name == "STEP10R")
    assert step10r.pgm == "CBTRN03C"


@pytest.mark.carddemo_e2e
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_tranrept_jcl_dd_overrides_reach_the_real_datasets(carddemo_home):
    jcl_text = (carddemo_home / "jcl" / "TRANREPT.jcl").read_text()
    job = parse_jcl(jcl_text)
    expanded = expand_procs(job, proclib_dirs=[carddemo_home / "proc"])

    prc001 = next(s for s in expanded.steps if s.name == "STEP05R.PRC001")
    filein = next(d for d in prc001.dds if d.ddname == "FILEIN")
    fileout = next(d for d in prc001.dds if d.ddname == "FILEOUT")

    # These come from TRANREPT.jcl's own //PRC001.FILEIN / //PRC001.FILEOUT
    # qualified DD overrides — replacing REPROC.prc's own NULLFILE
    # placeholders, proving the override mechanism against real JCL text.
    assert filein.dsn == DirectDSN(literal("AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS"))
    assert fileout.dsn != DirectDSN(literal("NULLFILE"))
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
CARDDEMO_HOME=$(pwd)/jackal/third-party/carddemo/app \
uv run --no-sync python -m pytest jackal/tests/integration/test_proc_expansion_carddemo_e2e.py -v
```
Expected at this point: this should actually already PASS if Task 4's implementation is correct, since it's exercising the same `expand_procs` logic already tested against synthetic fixtures — the "RED" step here is really "run it before this test file exists" (trivially true) plus a genuine correctness check against real, more complex JCL than the synthetic fixtures (real continuation lines, real multi-DD overrides, the real `REPROC.prc`'s exact structure). If it fails, the failure is informative: it means something about the real corpus's actual syntax (continuation lines, whitespace, DD ordering) isn't handled by Task 4's implementation the way the synthetic fixtures assumed — investigate and fix `proc_expand.py`, do not adjust this test's assertions to match incorrect output.

- [ ] **Step 3: If it fails, fix `proc_expand.py`; once it passes, verify explicitly**

```bash
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
CARDDEMO_HOME=$(pwd)/jackal/third-party/carddemo/app \
uv run --no-sync python -m pytest jackal/tests/integration/test_proc_expansion_carddemo_e2e.py -v
```
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add jackal/tests/integration/test_proc_expansion_carddemo_e2e.py
git commit -m "test: prove expand_procs() against the real CardDemo TRANREPT.jcl/REPROC.prc"
```

---

## Task 6: `jcl_graph.py` — qualified ids + `proc` attrs

**Files:**
- Modify: `jackal/jackal/jcl_graph.py`
- Modify: `jackal/tests/unit/test_jcl_graph.py`

**Interfaces:**
- Consumes: `expand_procs` (Task 4).
- Produces: `extract_jcl_graph(jcl_source: str, proclib_dirs: Sequence[Path] = ()) -> tuple[list[GraphNode], list[GraphEdge]]` — new optional parameter, default `()` (empty — expansion is then a no-op, preserving every existing caller's behavior unchanged).

- [ ] **Step 1: Write the failing test first**

Add to `jackal/tests/unit/test_jcl_graph.py` (append; needs a `tmp_path` fixture, already a standard pytest fixture, and imports `Path` — add `from pathlib import Path` near the top if not present):

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_proc_call_expands_with_qualified_id_and_proc_attr(tmp_path: Path):
    (tmp_path / "REPROC.prc").write_text(
        "//REPROC PROC\n//PRC001 EXEC PGM=IDCAMS\n//SYSIN DD DISP=SHR,DSN=NULLFILE\n// PEND\n"
    )
    jcl = "//TRANREPT JOB 'demo'\n//STEP05R EXEC PROC=REPROC\n"
    nodes, edges = extract_jcl_graph(jcl, proclib_dirs=[tmp_path])

    step_nodes = [n for n in nodes if n.kind == NodeKind.STEP]
    assert any(n.id == "TRANREPT.STEP05R.PRC001" for n in step_nodes)
    assert not any(n.id == "TRANREPT.STEP05R" for n in step_nodes)

    job_to_step = [
        e for e in edges
        if e.kind == EdgeKind.JCL_STEP_RUNS and e.source == "TRANREPT"
    ]
    assert job_to_step[0].target == "TRANREPT.STEP05R.PRC001"
    assert job_to_step[0].attrs == {"proc": "REPROC"}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_extract_jcl_graph_without_proclib_dirs_is_unchanged():
    # Default proclib_dirs=() must produce byte-identical behavior to every
    # existing call site that predates this feature.
    nodes, edges = extract_jcl_graph(JCL)
    assert [s for s in nodes if s.kind == NodeKind.STEP]
    step_to_prog = {
        e.source: e.target
        for e in edges
        if e.kind == EdgeKind.JCL_STEP_RUNS and e.source.startswith("PIPE.")
    }
    assert step_to_prog["PIPE.STEP1"] == "UPCASE"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest jackal/tests/unit/test_jcl_graph.py -k "proc_call or without_proclib" -v
```
Expected: `test_proc_call_expands_with_qualified_id_and_proc_attr` FAILS — `extract_jcl_graph()` takes no `proclib_dirs` argument (`TypeError`). `test_extract_jcl_graph_without_proclib_dirs_is_unchanged` should already PASS (it's a regression guard, not new behavior) — if it fails, stop, that would indicate an unrelated pre-existing problem.

- [ ] **Step 3: Update `jcl_graph.py`**

Change the imports (currently `from jackal.jcl.parser import parse_jcl`) to add `expand_procs` and the `Path`/`Sequence` types:
```python
from pathlib import Path
from typing import Sequence

from jackal.jcl.parser import parse_jcl
from jackal.jcl.proc_expand import expand_procs
```

Change `_job_to_graph`'s per-step loop to thread through PROC provenance. The current step-node-creation block is:
```python
    for step in job.steps:
        step_id = _add_node(NodeKind.STEP, f"{job.name.upper()}.{step.name.upper()}")
        edges.append(
            GraphEdge(
                source=job_id,
                source_kind=NodeKind.JOB,
                target=step_id,
                target_kind=NodeKind.STEP,
                kind=EdgeKind.JCL_STEP_RUNS,
            )
        )
```

Change it to accept and use a `step_proc: dict[str, str]` lookup (built by `extract_jcl_graph` before calling `_job_to_graph`, mapping each *expanded* step's uppercased name to the PROC name it came from, absent for steps that were never a PROC call):
```python
    for step in job.steps:
        step_id = _add_node(NodeKind.STEP, f"{job.name.upper()}.{step.name.upper()}")
        proc_name = step_proc.get(step.name.upper())
        edges.append(
            GraphEdge(
                source=job_id,
                source_kind=NodeKind.JOB,
                target=step_id,
                target_kind=NodeKind.STEP,
                kind=EdgeKind.JCL_STEP_RUNS,
                attrs={"proc": proc_name} if proc_name else {},
            )
        )
```

This requires `_job_to_graph`'s signature to accept `step_proc`:
```python
def _job_to_graph(
    job: Job, step_proc: dict[str, str]
) -> tuple[list[GraphNode], list[GraphEdge]]:
```

Change `extract_jcl_graph` itself. It currently is:
```python
def extract_jcl_graph(jcl_source: str) -> tuple[list[GraphNode], list[GraphEdge]]:
    """..."""
    job = parse_jcl(jcl_source)
    return _job_to_graph(job)
```

Add this new helper function directly above it (after `_job_to_graph`, before `extract_jcl_graph`):

```python
def _step_proc_provenance(job: Job, expanded_job: Job) -> dict[str, str]:
    """Map each expanded step's uppercased name to the PROC name it came
    from. A step whose (uppercased) name matches an outer step's own name
    exactly wasn't expanded (no dot added) — everything else with a dot in
    its name that isn't in the original job is PROC-sourced, and the PROC
    name is the part before the first dot's corresponding original step's
    pgm."""
    original_by_name = {s.name.upper(): s for s in job.steps}
    provenance: dict[str, str] = {}
    for step in expanded_job.steps:
        name = step.name.upper()
        if name in original_by_name:
            continue  # unexpanded, ordinary step
        outer_name = name.split(".", 1)[0]
        outer_step = original_by_name.get(outer_name)
        if outer_step is not None:
            provenance[name] = outer_step.pgm.upper()
    return provenance
```

Then replace `extract_jcl_graph` with:
```python
def extract_jcl_graph(
    jcl_source: str, proclib_dirs: Sequence[Path] = ()
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Parse JCL text and return its step-sequencing portion of the shared
    knowledge graph: JOB/STEP/PROGRAM/DATASET/INSTREAM_DATA nodes;
    JCL_STEP_RUNS edges (job->step, in step order, and step->program) and
    READS/WRITES/UPDATES edges (step->dataset, derived from DD disposition —
    NEW/MOD->WRITES, OLD->UPDATES, SHR->READS; the raw DispStatus is kept in
    attrs["disp"]).

    A DD fed by literal inline content (DD *) has no dataset identity to
    read/write — it gets its own INSTREAM_DATA node (id scoped by
    JOB.STEP.DDNAME, so distinct occurrences never collide) and a READS edge
    from its step, instead of being folded into DATASET. That edge's
    attrs["text"] carries the raw in-stream lines verbatim (e.g. IDCAMS
    control statements) as an opaque string — this module does no semantic
    parsing of the content, just passes it through.

    TempRef (&&NAME) and BackwardRef (*.STEP.DD) datasets, DummyDSN (DD
    DUMMY), and SYSOUT DDs, are not stable cross-job identities and are not
    represented as nodes at all.

    proclib_dirs (default empty — no-op) resolves and inlines EXEC PROC=
    calls via expand_procs before building the graph. An expanded step's
    JOB -> STEP edge carries attrs["proc"] naming the PROC it came from, so
    it's visibly distinguishable from a step written directly in the job —
    following the same "opaque discriminant on the edge" precedent as
    attrs["text"] (SYSIN) and attrs["select_name"] (COBOL_FILE).
    """
    job = parse_jcl(jcl_source)
    step_proc: dict[str, str] = {}
    if proclib_dirs:
        expanded_job = expand_procs(job, proclib_dirs)
        step_proc = _step_proc_provenance(job, expanded_job)
        job = expanded_job
    return _job_to_graph(job, step_proc)
```

Now replace the earlier (buggy placeholder) `extract_jcl_graph` body with the clean version:
```python
def extract_jcl_graph(
    jcl_source: str, proclib_dirs: Sequence[Path] = ()
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """[docstring exactly as written above]"""
    job = parse_jcl(jcl_source)
    step_proc: dict[str, str] = {}
    if proclib_dirs:
        expanded_job = expand_procs(job, proclib_dirs)
        step_proc = _step_proc_provenance(job, expanded_job)
        job = expanded_job
    return _job_to_graph(job, step_proc)
```

Note: this provenance approach only correctly attributes the *directly*-called PROC name for a single level of nesting (e.g. `STEP05R.PRC001` → attributed to `REPROC`, correct). For a doubly-nested case (`STEP01R.STEP01R.PRC001`, from Task 4's `CALLER`→`REPROC` nesting test), this simple name-split approach attributes it to `CALLER` (the outer step's own `pgm`) rather than tracing the full chain to `REPROC` — that's an acceptable, deliberate simplification for the graph's display purpose (the `attrs["proc"]` is meant as a "this step didn't come from the job's own text" discriminant, not a full call-stack trace); do not over-engineer multi-level provenance tracking here unless a test requires it.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest jackal/tests/unit/test_jcl_graph.py -v
```
Expected: all pass (14 tests: 12 existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add jackal/jackal/jcl_graph.py jackal/tests/unit/test_jcl_graph.py
git commit -m "feat: expand PROC calls in the JCL graph, with qualified ids and proc attrs"
```

---

## Task 7: `runner.py` — `proclib_dirs` wiring

**Files:**
- Modify: `jackal/jackal/runner.py`
- Test: `jackal/tests/unit/test_runner.py`

**Interfaces:**
- Consumes: `expand_procs` (Task 4).
- Produces: `JobRunner.__init__` gains an optional `proclib_dirs: Sequence[Path] = ()` parameter; `JobRunner.run_job` calls `expand_procs` first when `proclib_dirs` is non-empty.

- [ ] **Step 1: Write the failing test first**

Add to `jackal/tests/unit/test_runner.py` (append; the file already imports `DirectDSN`, `DD`, `Cond`, `CondOp`, `Disp`, `DispNormal`, `DispStatus`, `Job`, `Step`, `StepDisposition`, `JobRunner` — add `from jackal.value_parts import literal` if not already present from the earlier plan's Task 7):

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_runner_expands_proc_call_before_running(tmp_path: Path) -> None:
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc" / "WRAPIT.prc").write_text(
        "//WRAPIT PROC\n"
        "//P1 EXEC PGM=IEFBR14\n"
        "//D DD DSN=J.X,DISP=(NEW,DELETE,DELETE)\n"
        "// PEND\n"
    )
    job = Job(name="J", steps=(Step(name="STEP1", pgm="WRAPIT", dds=()),))
    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
        proclib_dirs=[tmp_path / "proc"],
    )
    res = runner.run(job, workdir=tmp_path, seeds={})
    assert [s.name for s in res.steps] == ["STEP1.P1"]
    assert res.steps[0].ran and res.steps[0].return_code == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_runner_without_proclib_dirs_is_unchanged(tmp_path: Path) -> None:
    # Default proclib_dirs=() must produce byte-identical behavior to every
    # existing call site that predates this feature (this is the exact body
    # of test_runner_runs_all_steps, re-run with no proclib_dirs argument).
    job = Job(
        name="J",
        steps=(
            Step(name="A", pgm="IEFBR14", dds=()),
            Step(name="B", pgm="IEFBR14", dds=()),
        ),
    )
    runner = JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )
    res = runner.run(job, workdir=tmp_path, seeds={})
    assert [s.name for s in res.steps] == ["A", "B"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run --no-sync python -m pytest jackal/tests/unit/test_runner.py -k "expands_proc or without_proclib" -v
```
Expected: `test_runner_expands_proc_call_before_running` FAILS — `JobRunner.__init__()` doesn't accept `proclib_dirs` (`TypeError`). `test_runner_without_proclib_dirs_is_unchanged` should already PASS.

- [ ] **Step 3: Update `runner.py`**

Change the imports (currently ending `from jackal.utilities import UTILITIES`) to add:
```python
from pathlib import Path
from typing import Sequence

from jackal.jcl.proc_expand import expand_procs
from jackal.utilities import UTILITIES
```
(`from pathlib import Path` already exists at the top of the file — do not duplicate it; only add the `Sequence` import and the `expand_procs` import if not already present.)

Change `JobRunner.__init__` from:
```python
    def __init__(
        self,
        source_dir: Path,
        bridge_jar: str,
        data_dir: Path,
        copybook_dir: Path,
    ):
        self._source_dir = source_dir
        self._bridge_jar = bridge_jar
        self._data_dir = data_dir
        self._copybook_dir = copybook_dir
```
to:
```python
    def __init__(
        self,
        source_dir: Path,
        bridge_jar: str,
        data_dir: Path,
        copybook_dir: Path,
        proclib_dirs: Sequence[Path] = (),
    ):
        self._source_dir = source_dir
        self._bridge_jar = bridge_jar
        self._data_dir = data_dir
        self._copybook_dir = copybook_dir
        self._proclib_dirs = proclib_dirs
```

Change `run_job`'s opening line from:
```python
    def run_job(self, job: Job, catalog: DatasetCatalog) -> JobResult:
        """Run a job against a pre-built catalog, honoring COND= and backward refs."""
        executed: list[StepResult] = []
```
to:
```python
    def run_job(self, job: Job, catalog: DatasetCatalog) -> JobResult:
        """Run a job against a pre-built catalog, honoring COND= and backward refs."""
        if self._proclib_dirs:
            job = expand_procs(job, self._proclib_dirs)
        executed: list[StepResult] = []
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run --no-sync python -m pytest jackal/tests/unit/test_runner.py -v
```
Expected: all pass (existing + 2 new).

- [ ] **Step 5: Run the full jackal suite once to confirm nothing else regressed**

```bash
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
PROLEAP_BRIDGE_JAR=$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
uv run --no-sync python -m pytest jackal -q
```
Expected: all pass (no regressions in any file this plan hasn't touched).

- [ ] **Step 6: Commit**

```bash
git add jackal/jackal/runner.py jackal/tests/unit/test_runner.py
git commit -m "feat: expand PROC calls in JobRunner before executing a job's steps"
```

---

## Task 8: Wire the real CardDemo proclib into `build_carddemo_graph.py`

**Files:**
- Modify: `knowledge_graph/build_carddemo_graph.py`

**Interfaces:**
- Consumes: `extract_jcl_graph`'s new `proclib_dirs` parameter (Task 6).

This is the whole-pipeline proof the user asked for: not just `expand_procs` in isolation (Task 4) or against one file directly (Task 5), but the actual CardDemo knowledge-graph build actually using it end to end.

- [ ] **Step 1: Locate and update `_build_jcl_graph`**

Read the current function (it currently calls `extract_jcl_graph(path.read_text())` with no second argument). Change the call to pass the real CardDemo proc directory:

Change:
```python
def _build_jcl_graph(failures: list[str]) -> tuple[list, list]:
    all_nodes, all_edges = [], []
    jcl_dir = _CARDDEMO_HOME / "jcl"
    jcl_files = sorted(jcl_dir.glob("*.jcl")) + sorted(jcl_dir.glob("*.JCL"))
    for path in jcl_files:
        try:
            nodes, edges = extract_jcl_graph(path.read_text())
        except Exception as exc:  # noqa: BLE001 — one bad job must not abort the run
            failures.append(f"JCL {path.name}: {exc}")
            continue
        all_nodes.extend(nodes)
        all_edges.extend(edges)
    print(f"JCL: {len(jcl_files)} files, {len(all_nodes)} nodes, {len(all_edges)} edges")
    return all_nodes, all_edges
```
to:
```python
def _build_jcl_graph(failures: list[str]) -> tuple[list, list]:
    all_nodes, all_edges = [], []
    jcl_dir = _CARDDEMO_HOME / "jcl"
    proclib_dirs = [_CARDDEMO_HOME / "proc"]
    jcl_files = sorted(jcl_dir.glob("*.jcl")) + sorted(jcl_dir.glob("*.JCL"))
    for path in jcl_files:
        try:
            nodes, edges = extract_jcl_graph(path.read_text(), proclib_dirs=proclib_dirs)
        except Exception as exc:  # noqa: BLE001 — one bad job must not abort the run
            failures.append(f"JCL {path.name}: {exc}")
            continue
        all_nodes.extend(nodes)
        all_edges.extend(edges)
    print(f"JCL: {len(jcl_files)} files, {len(all_nodes)} nodes, {len(all_edges)} edges")
    return all_nodes, all_edges
```

- [ ] **Step 2: Rebuild the CardDemo graph and verify `CBTRN03C` gains its `TRANREPT`-via-`REPROC` provenance**

```bash
PROLEAP_BRIDGE_JAR=$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
uv run --no-sync python knowledge_graph/build_carddemo_graph.py
```

Then inspect the output for the `REPROC` PROGRAM node and the `TRANREPT.STEP05R.PRC001` step node:
```bash
grep -o '"REPROC"' tests/integration/output/carddemo_knowledge_graph.html | head -1
```
Expected: **no match** — `REPROC` should no longer appear as a `PROGRAM` node label at all (it was previously a spurious `PROGRAM` node; now every reference to it is fully expanded into real `IDCAMS` steps).

Also regenerate the NDJSON export (reuse the scratch script pattern from earlier sessions, or add a one-off) and confirm `TRANREPT.STEP05R.PRC001` exists with `pgm=IDCAMS` and `attrs={"proc": "REPROC"}` on its `JOB -> STEP` edge, and that `STEP10R` (the real `CBTRN03C` step, untouched by this feature since it was never a PROC call) is unaffected.

If the `JCL:` node/edge counts printed by the build differ from a plausible expansion (more steps than before, since `REPROC`/`TRANREPT`-style PROC calls now contribute their real inner steps instead of one stub `PROGRAM` node), that is expected and correct — do not treat a count *increase* as a regression. Only investigate if a count *decreases*, or if the run reports new failures beyond the pre-existing `COCRDSEC` one.

- [ ] **Step 3: Commit**

```bash
git add knowledge_graph/build_carddemo_graph.py
git commit -m "feat: resolve real CardDemo PROC calls (REPROC, etc.) in the knowledge graph build"
```

---

## Task 9: Full suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full jackal test suite**

```bash
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
PROLEAP_BRIDGE_JAR=$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
CARDDEMO_HOME=$(pwd)/jackal/third-party/carddemo/app \
uv run --no-sync python -m pytest jackal -q
```
Expected: all pass, including the two new `carddemo_e2e`-marked tests from Task 5 (they only run with `CARDDEMO_HOME` set — confirm they're not silently skipped in this run).

- [ ] **Step 2: Run the top-level and knowledge_graph suites**

```bash
PROLEAP_BRIDGE_JAR=$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
uv run --no-sync python -m pytest tests/unit -q
```
Expected: all pass, unaffected by this plan (no file under `tests/` or `knowledge_graph/` other than `build_carddemo_graph.py` — a script, not covered by `tests/unit` — changed).

- [ ] **Step 3: Rebuild the CardDemo graph one final time and open it**

```bash
PROLEAP_BRIDGE_JAR=$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
uv run --no-sync python knowledge_graph/build_carddemo_graph.py
open tests/integration/output/carddemo_knowledge_graph.html
```

## Self-Review

**Spec coverage:** every section of the design spec (`jackal/docs/superpowers/specs/2026-07-08-jcl-proc-expansion-design.md`) maps to a task — the "Bridge/model changes required" section to Tasks 1-3, the `expand_procs` algorithm to Task 4, "Graph representation" to Task 6, "Testing" (real-corpus integration) to Task 5, `runner.py` wiring to Task 7. The design's two "open verification items" were resolved during planning (both grammar rules — `procJCL`, `defineSymbolicParameter`/`execProcParm` — confirmed to exist, class/token names confirmed against the generated ANTLR sources) rather than left as in-plan placeholders. `SET` statements are explicitly out of scope per the user's decision, filed as forge-6qr, and called out in Global Constraints so no task drifts into implementing them.

**Placeholder scan:** no TBD/TODO. Task 6 originally left a broken intermediate code block (a `pass` placeholder) ahead of the correct implementation — caught on self-review and removed; the task now shows only the final, correct `_step_proc_provenance` helper and `extract_jcl_graph` body, in the right definition order.

**Type consistency:** `expand_procs(job, proclib_dirs)`'s signature, `ProcExpansionError`, `ProcDef(name, defaults, steps)`, and `Step.proc_parms: dict[str, Value]` are identical from their Task 2/4 definitions through every later task's usage (Tasks 5-8 all call `expand_procs`/consume `Step.proc_parms` with the exact same signature).
