# JCL Parser via ANTLR Grammar behind a Java Bridge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace jackal's hand-written Lark JCL parser with the MIT `mapa` ANTLR grammar run in Java behind a subprocess bridge, deserialized into jackal's existing frozen model — with 100% parse-behavior parity before the Lark grammar is deleted.

**Architecture:** A jackal-owned `jcl-bridge/` Maven module vendors mapa's two `.g4` files (copied, not a submodule), generates an ANTLR parser, and a thin `JclSerializer` main reads JCL on stdin → parses → emits a **projected JSON AST** to stdout. The Python side (`JclBridgeParser`) shells to the shaded JAR (mirroring red-dragon's `ProLeapCobolParser`), deserializes JSON → `Job`/`Step`/`DD`. `parse_jcl(text) -> Job` keeps its signature; the Lark grammar + Transformer are removed.

**Tech Stack:** Java 17 + Maven + ANTLR4 (maven-antlr4-plugin) + Gson + maven-shade (build-time); Python 3.13 + uv + pytest + Black (runtime needs only `java` + the shaded JAR — no new Python dependency).

## Global Constraints

- **Grammar = `cschneid-the-elder/mapa`**, files `jcl/src/JCLLexer.g4` + `jcl/src/JCLParser.g4`, start rule `startRule`, `tokenVocab=JCLLexer`. MIT.
- **Vendor, NOT a submodule** — copy the two `.g4` into the module; keep mapa's `LICENSE` and a `PROVENANCE.md` (upstream URL + exact commit SHA + any local edits) beside them.
- **Raw-parse-first** — run the main JCL grammar on raw source; do NOT wire mapa's JCLPP preprocessor / symbolic / INCLUDE expansion (deferred to `jackal-1o2.2`/`1o2.15`).
- **Keep `parse_jcl(text: str) -> Job`** — callers and the model are unchanged.
- **No `None` defaults in function signatures; no silent error-swallowing — fail loud.** (JSON-presence defaults via `dict.get(key, concrete)` are fine; required fields use `d["key"]` so a missing one raises.)
- **No regex for parsing** — satisfied by ANTLR (a parser generator), as Lark was.
- **FP:** frozen model unchanged; functional core / imperative shell (subprocess lives in the shell).
- **Parity gate:** the full suite + the gated `carddemo_e2e` test must be green on the new parser BEFORE `grammar.lark` is deleted/merged.
- **Build product** — the shaded JAR is gitignored (`.gitignore` already has `*.jar` + `**/target/`); built via `build.sh`. Env var `JCL_BRIDGE_JAR` locates it (mirroring `PROLEAP_BRIDGE_JAR`).
- Tooling: `uv run pytest`, `uv run black .`. Commit through the real pre-commit hooks (append Talisman false-positives to `.talismanrc` BEFORE the `version:` line).

### THE JSON CONTRACT (both the Java emitter in Task 1 and the Python deserializer in Task 2 implement THIS exact shape)

```json
{
  "name": "PIPE",
  "steps": [
    {
      "name": "STEP1",
      "pgm": "UPCASE",
      "dds": [
        {"ddname": "INDD",   "dsn": "J.IN",   "disp_words": ["SHR"],               "in_stream": [], "sysout": false},
        {"ddname": "WORKDD", "dsn": "J.WORK", "disp_words": ["NEW","PASS","DELETE"], "in_stream": [], "sysout": false},
        {"ddname": "SYSIN",  "dsn": "",       "disp_words": [], "in_stream": ["   DELETE A.B CLUSTER"], "sysout": false},
        {"ddname": "SYSPRINT","dsn": "",      "disp_words": [], "in_stream": [], "sysout": true}
      ]
    }
  ]
}
```

Field rules (identical on both sides):
- `name` (job), `steps[].name`, `steps[].pgm`, `dds[].ddname` are **required** strings.
- `dds[].dsn` — `""` when no `DSN=` (e.g. in-stream / SYSOUT DDs).
- `dds[].disp_words` — the `DISP=` words **as written**, 0–3 entries (`[]` when no `DISP=`). Default resolution happens in Python (`_disp_from_words`), so Java just passes the words through. `DISP=SHR` → `["SHR"]`; `DISP=(NEW,PASS,DELETE)` → `["NEW","PASS","DELETE"]`.
- `dds[].in_stream` — the in-stream data lines (between `DD *` and `/*`), verbatim, `[]` if none.
- `dds[].sysout` — `true` for `DD SYSOUT=...`, else `false`.
- For a step EXECuting a PROC (`EXEC PROC=X` / `EXEC X`), emit the proc name as `pgm` (executing PROCs is `1o2.2`; parsing it must still round-trip).

---

## File Structure

**New — Java bridge module (`jcl-bridge/`):**
- `jcl-bridge/pom.xml` — Maven: antlr4 plugin (generate from local `.g4`), shade plugin (fat JAR incl. ANTLR runtime + Gson), mainClass `org.jackal.jcl.JclSerializer`.
- `jcl-bridge/src/main/antlr4/org/jackal/jcl/JCLLexer.g4` — vendored from mapa.
- `jcl-bridge/src/main/antlr4/org/jackal/jcl/JCLParser.g4` — vendored from mapa.
- `jcl-bridge/LICENSE` — mapa's MIT license (verbatim).
- `jcl-bridge/PROVENANCE.md` — upstream repo URL + exact commit SHA + note of any local `.g4` edits.
- `jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java` — `main`: read stdin → parse → walk tree → print JSON.

**New — Python:**
- `jackal/jcl/bridge_parser.py` — `JclParseError`, `JclSubprocessRunner` (real runner, fail-loud), `JclBridgeParser`, the pure `_job_from_json` deserializer, and the moved `_disp_from_words` / `_DEFAULT_DISP` helpers.

**Modified:**
- `jackal/jcl/parser.py` — `parse_jcl` delegates to `JclBridgeParser`; Lark code removed.
- `tests/conftest.py` — add `jcl_bridge_jar` fixture (reads `JCL_BRIDGE_JAR`, fail-loud).
- `build.sh` — also build the `jcl-bridge` JAR.
- `.pre-commit-config.yaml` — export `JCL_BRIDGE_JAR` for the test hook (mirroring `PROLEAP_BRIDGE_JAR`).

**Deleted:**
- `jackal/jcl/grammar.lark`

---

## Task 1: `jcl-bridge` Maven module — vendor grammar, emit JSON, build the JAR

**Files:**
- Create: `jcl-bridge/pom.xml`, `jcl-bridge/src/main/antlr4/org/jackal/jcl/JCLLexer.g4`, `jcl-bridge/src/main/antlr4/org/jackal/jcl/JCLParser.g4`, `jcl-bridge/LICENSE`, `jcl-bridge/PROVENANCE.md`, `jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java`
- Modify: `build.sh`

**Interfaces:**
- Produces: a shaded JAR at `jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar` whose `main` reads JCL on **stdin** and writes the **JSON contract** (see Global Constraints) to **stdout**; non-zero exit + stderr diagnostic on parse failure.

- [ ] **Step 1: Vendor the grammar.** From `https://github.com/cschneid-the-elder/mapa` (default branch), copy `jcl/src/JCLLexer.g4` and `jcl/src/JCLParser.g4` into `jcl-bridge/src/main/antlr4/org/jackal/jcl/` **unmodified**. Copy mapa's `LICENSE` to `jcl-bridge/LICENSE`. Record in `jcl-bridge/PROVENANCE.md`: the repo URL, the exact commit SHA you copied from (`git ls-remote https://github.com/cschneid-the-elder/mapa HEAD`), the two file paths, and "no local edits". 
  - **Grammar-import check:** open both `.g4` and look for `import` statements or `tokenVocab` referencing grammars OTHER than `JCLLexer`/`JCLParser`. The spike parsed cleanly with just these two via `antlr4-parse`, so none are expected — but if ANTLR generation (Step 4) reports an unresolved imported grammar, vendor that referenced `.g4` too and note it in `PROVENANCE.md`.
  - Add the ANTLR `header`/package: ANTLR's maven plugin places generated sources by grammar `@header`/path. Ensure the two `.g4` declare no conflicting `@header{ package ... }` that fights the `org/jackal/jcl` directory; if mapa's `.g4` has a package-setting `@header`, leave it and match the Java package to it (note the actual package in `PROVENANCE.md`).

- [ ] **Step 2: Write `pom.xml`.** Mirror `vendor/red-dragon/proleap-bridge/pom.xml` (Java 17, shade plugin with `ManifestResourceTransformer` mainClass, `shadedClassifierName=shaded`). Differences: `groupId=org.jackal`, `artifactId=jcl-bridge`, `version=0.1.0`, mainClass `org.jackal.jcl.JclSerializer`; dependencies = `org.antlr:antlr4-runtime:4.13.1` + `com.google.code.gson:gson:2.11.0`; add the `org.antlr:antlr4-maven-plugin:4.13.1` (goal `antlr4`, default phase) so the `.g4` under `src/main/antlr4` generate lexer/parser at build.

```xml
<plugin>
  <groupId>org.antlr</groupId>
  <artifactId>antlr4-maven-plugin</artifactId>
  <version>4.13.1</version>
  <executions><execution><goals><goal>antlr4</goal></goals></execution></executions>
</plugin>
```

- [ ] **Step 3: Discover the parse-tree shape.** Install `antlr4-tools` (`pip install antlr4-tools` in a throwaway venv, or use the ANTLR jar) and run, against a small sample saved to `/tmp/sample.jcl`:
```
printf '//PIPE JOB 1\n//STEP1 EXEC PGM=UPCASE\n//INDD DD DSN=J.IN,DISP=SHR\n//SYSIN DD *\n   HELLO\n/*\n' > /tmp/sample.jcl
antlr4-parse jcl-bridge/src/main/antlr4/org/jackal/jcl/JCLLexer.g4 jcl-bridge/src/main/antlr4/org/jackal/jcl/JCLParser.g4 startRule -tree /tmp/sample.jcl
```
Read the printed tree to learn the **actual rule names** for: the job card + job name; each step's EXEC + `PGM=`/`PROC=` value; each DD statement + its DDname; the `DSN=`, `DISP=`, `SYSOUT=` parameter sub-rules; and the in-stream data node(s). (Spike-observed names to expect: `jcl > execJCL > jobCard > jobName`, `execStatement`, DD statements with per-parameter rules e.g. `ddStatementParameterDSN`/`...DISP`/`...SYSOUT`, and in-stream `ddParmASTERISK`/`DD_ASTERISK_DATA`. Confirm exact spellings from YOUR tree output — these are the only "unknowns" and the tree dump resolves them.) Record the rule names you'll use in a comment block at the top of `JclSerializer.java`.

- [ ] **Step 4: Write `JclSerializer.java`.** Structure (fill the rule accessors from Step 3; use Gson to emit the contract):

```java
package org.jackal.jcl;

import com.google.gson.*;
import org.antlr.v4.runtime.*;
import org.antlr.v4.runtime.tree.*;
import java.io.*;
import java.nio.charset.StandardCharsets;

public final class JclSerializer {
    public static void main(String[] args) throws IOException {
        String src = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        JCLLexer lexer = new JCLLexer(CharStreams.fromString(src));
        CommonTokenStream tokens = new CommonTokenStream(lexer);
        JCLParser parser = new JCLParser(tokens);
        // Fail loud: collect syntax errors, exit non-zero if any.
        FailingErrorListener errs = new FailingErrorListener();
        lexer.removeErrorListeners(); lexer.addErrorListener(errs);
        parser.removeErrorListeners(); parser.addErrorListener(errs);
        ParseTree tree = parser.startRule();
        if (errs.hasErrors()) { System.err.print(errs.text()); System.exit(1); }
        JsonObject job = new JobBuilder(tokens).build(tree);   // walk tree -> contract
        System.out.print(new Gson().toJson(job));
    }
}
```
Implement `FailingErrorListener` (a `BaseErrorListener` accumulating `line:col msg` into a buffer; `hasErrors()`/`text()`), and `JobBuilder` — a visitor/walker over the tree that emits the JSON contract: `name` from the jobCard rule; one `steps[]` entry per EXEC rule (`pgm` from `PGM=`/`PROC=`); each step's `dds[]` from the DD rules between consecutive EXECs (`ddname`, `dsn` = `DSN=` value or `""`, `disp_words` = the DISP words list or `[]`, `in_stream` = the in-stream lines or `[]`, `sysout` = `SYSOUT=` present). Use `getText()` on the relevant subtrees; for in-stream lines, split the in-stream payload token on newlines preserving content (match the existing Lark behavior: each physical line between `DD *` and `/*`, leading spaces kept).

- [ ] **Step 5: Build the JAR.**
```bash
cd jcl-bridge && mvn -DskipTests package -q && cd ..
ls jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
```
Expected: the JAR exists.

- [ ] **Step 6: Smoke-test the JAR against the contract.**
```bash
printf '//PIPE JOB 1\n//STEP1 EXEC PGM=UPCASE\n//INDD DD DSN=J.IN,DISP=SHR\n' | java -jar jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
```
Expected stdout (JSON, field order irrelevant): `{"name":"PIPE","steps":[{"name":"STEP1","pgm":"UPCASE","dds":[{"ddname":"INDD","dsn":"J.IN","disp_words":["SHR"],"in_stream":[],"sysout":false}]}]}`. Also verify failure: `printf 'garbage' | java -jar …; echo "exit=$?"` → non-zero exit, error text on stderr.

- [ ] **Step 7: Wire the build.** Add to `build.sh` (read it first; append next to the proleap build): `(cd jcl-bridge && mvn -DskipTests package -q)`. Confirm `.gitignore` already ignores `jcl-bridge/target/` + the JAR (it has `**/target/` and `*.jar` — verify, don't duplicate).

- [ ] **Step 8: Commit.**
```bash
git add jcl-bridge build.sh
# if Talisman flags the .g4 / LICENSE, append fileignoreconfig entries before the version: line in .talismanrc, then re-add
git commit -m "feat(jcl-bridge): vendor mapa ANTLR JCL grammar; Java serializer -> JSON; build wiring"
```

---

## Task 2: Python JSON → model deserializer (pure, no JAR)

**Files:**
- Create: `jackal/jcl/bridge_parser.py`
- Test: `tests/unit/test_jcl_bridge_deserialize.py`

**Interfaces:**
- Consumes: the JSON contract (Global Constraints).
- Produces: `_job_from_json(data: dict) -> Job`; helpers `_disp_from_words(words: tuple[str, ...]) -> Disp` and `_DEFAULT_DISP: Disp` (moved here from `parser.py`).

- [ ] **Step 1: Write failing tests.**
```python
from tests.covers import NotLanguageFeature, covers
from jackal.jcl.bridge_parser import _job_from_json
from jackal.model import DispNormal, DispStatus

@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_job_steps_dds():
    data = {"name": "PIPE", "steps": [
        {"name": "STEP1", "pgm": "UPCASE", "dds": [
            {"ddname": "INDD", "dsn": "J.IN", "disp_words": ["SHR"], "in_stream": [], "sysout": False},
            {"ddname": "WORKDD", "dsn": "J.WORK", "disp_words": ["NEW","PASS","DELETE"], "in_stream": [], "sysout": False},
        ]},
        {"name": "STEP2", "pgm": "STARRER", "dds": []},
    ]}
    job = _job_from_json(data)
    assert job.name == "PIPE"
    assert [s.name for s in job.steps] == ["STEP1", "STEP2"]
    assert [s.pgm for s in job.steps] == ["UPCASE", "STARRER"]
    w = job.steps[0].dds[1]
    assert (w.disp.status, w.disp.normal, w.disp.abnormal) == (DispStatus.NEW, DispNormal.PASS, DispNormal.DELETE)

@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_disp_shr_defaults_keep_keep():
    data = {"name": "J", "steps": [{"name": "S", "pgm": "P", "dds": [
        {"ddname": "D", "dsn": "A.B", "disp_words": ["SHR"], "in_stream": [], "sysout": False}]}]}
    d = _job_from_json(data).steps[0].dds[0]
    assert (d.disp.status, d.disp.normal, d.disp.abnormal) == (DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)

@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_deserialize_instream_and_sysout():
    data = {"name": "J", "steps": [{"name": "S", "pgm": "IDCAMS", "dds": [
        {"ddname": "SYSIN", "dsn": "", "disp_words": [], "in_stream": ["   DELETE A.B CLUSTER"], "sysout": False},
        {"ddname": "SYSPRINT", "dsn": "", "disp_words": [], "in_stream": [], "sysout": True}]}]}
    dds = _job_from_json(data).steps[0].dds
    assert dds[0].in_stream == ("   DELETE A.B CLUSTER",)
    assert dds[1].sysout is True
```

- [ ] **Step 2: Run → fail.** `uv run pytest tests/unit/test_jcl_bridge_deserialize.py -v` → FAIL (module `bridge_parser` missing).

- [ ] **Step 3: Implement `bridge_parser.py` (deserializer + helpers only for now).**
```python
"""Bridge to the jcl-bridge JAR: JSON AST -> Job, and the JSON->model deserializer."""

from __future__ import annotations

from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step

_DEFAULT_DISP = Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)


def _disp_from_words(words: tuple[str, ...]) -> Disp:
    status = DispStatus(words[0])
    normal = DispNormal(words[1]) if len(words) > 1 else DispNormal.KEEP
    abnormal = DispNormal(words[2]) if len(words) > 2 else normal
    return Disp(status, normal, abnormal)


def _dd_from_json(d: dict) -> DD:
    words = tuple(d.get("disp_words", ()))
    disp = _disp_from_words(words) if words else _DEFAULT_DISP
    return DD(
        ddname=d["ddname"],
        dsn=d.get("dsn", ""),
        disp=disp,
        in_stream=tuple(d.get("in_stream", ())),
        sysout=d.get("sysout", False),
    )


def _step_from_json(s: dict) -> Step:
    return Step(name=s["name"], pgm=s["pgm"], dds=tuple(_dd_from_json(d) for d in s["dds"]))


def _job_from_json(data: dict) -> Job:
    return Job(name=data["name"], steps=tuple(_step_from_json(s) for s in data["steps"]))
```

- [ ] **Step 4: Run → pass.** `uv run pytest tests/unit/test_jcl_bridge_deserialize.py -v` → 3 passed.

- [ ] **Step 5: Format + commit.**
```bash
uv run black jackal/jcl/bridge_parser.py tests/unit/test_jcl_bridge_deserialize.py
git add jackal/jcl/bridge_parser.py tests/unit/test_jcl_bridge_deserialize.py
git commit -m "feat(jcl): JSON->model deserializer for the JCL bridge"
```

---

## Task 3: `JclBridgeParser` subprocess wrapper (fake-runner unit + real-JAR integration)

**Files:**
- Modify: `jackal/jcl/bridge_parser.py`
- Modify: `tests/conftest.py` (add `jcl_bridge_jar` fixture)
- Test: `tests/unit/test_jcl_bridge_parser.py`, `tests/integration/test_jcl_bridge_jar.py`

**Interfaces:**
- Consumes: `_job_from_json` (Task 2); the JAR from Task 1.
- Produces: `class JclParseError(Exception)`; `class JclSubprocessRunner` with `run(self, command: list[str], input_data: str) -> str`; `class JclBridgeParser` with `__init__(self, runner, bridge_jar: str)` and `parse(self, text: str) -> Job`.

- [ ] **Step 1: Write failing unit tests (fake runner — no JVM).**
```python
import json
import pytest
from tests.covers import NotLanguageFeature, covers
from jackal.jcl.bridge_parser import JclBridgeParser, JclParseError

class _FakeRunner:
    def __init__(self, out=None, exc=None):
        self._out, self._exc = out, exc
        self.command = None
    def run(self, command, input_data):
        self.command = command
        if self._exc:
            raise self._exc
        return self._out

@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_builds_model_from_bridge_json():
    out = json.dumps({"name": "J", "steps": [
        {"name": "S", "pgm": "P", "dds": [
            {"ddname": "D", "dsn": "A.B", "disp_words": ["SHR"], "in_stream": [], "sysout": False}]}]})
    runner = _FakeRunner(out=out)
    job = JclBridgeParser(runner, "jcl.jar").parse("//J JOB 1\n")
    assert job.steps[0].dds[0].dsn == "A.B"
    assert runner.command == ["java", "-jar", "jcl.jar"]

@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_propagates_bridge_failure():
    runner = _FakeRunner(exc=JclParseError("boom"))
    with pytest.raises(JclParseError):
        JclBridgeParser(runner, "jcl.jar").parse("garbage")
```

- [ ] **Step 2: Run → fail.** `uv run pytest tests/unit/test_jcl_bridge_parser.py -v` → FAIL (names missing).

- [ ] **Step 3: Implement (append to `bridge_parser.py`).**
```python
import json
import subprocess


class JclParseError(Exception):
    """Raised when the jcl-bridge fails to parse JCL."""


class JclSubprocessRunner:
    """Production runner: invoke the bridge JAR, fail loud on non-zero exit."""

    def run(self, command: list[str], input_data: str) -> str:
        result = subprocess.run(
            command, input=input_data, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise JclParseError(
                f"jcl-bridge failed (exit {result.returncode}): {result.stderr}"
            )
        return result.stdout


class JclBridgeParser:
    """Parse JCL by delegating to the jcl-bridge JAR via subprocess."""

    def __init__(self, runner: JclSubprocessRunner, bridge_jar: str):
        self._runner = runner
        self._bridge_jar = bridge_jar

    def parse(self, text: str) -> Job:
        command = ["java", "-jar", self._bridge_jar]
        out = self._runner.run(command, text)
        return _job_from_json(json.loads(out))
```
(Add `from jackal.model import ...` already present; add `import json`, `import subprocess` at top.)

- [ ] **Step 4: Run → pass.** `uv run pytest tests/unit/test_jcl_bridge_parser.py -v` → 2 passed.

- [ ] **Step 5: Add the `jcl_bridge_jar` fixture** to `tests/conftest.py` (mirror `bridge_jar`):
```python
@pytest.fixture
def jcl_bridge_jar() -> str:
    """The jcl-bridge JAR path; fail loudly if unset."""
    jar = os.environ["JCL_BRIDGE_JAR"]
    assert jar, "JCL_BRIDGE_JAR must point at the built jcl-bridge JAR"
    return jar
```

- [ ] **Step 6: Write the real-JAR integration test.**
```python
from tests.covers import NotLanguageFeature, covers
from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner

@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_simple_job(jcl_bridge_jar):
    jcl = "//PIPE JOB 1\n//STEP1 EXEC PGM=UPCASE\n//INDD DD DSN=J.IN,DISP=SHR\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.name == "PIPE"
    assert job.steps[0].pgm == "UPCASE"
    assert job.steps[0].dds[0].dsn == "J.IN"
```

- [ ] **Step 7: Run → pass (real JAR).**
```bash
export JCL_BRIDGE_JAR="$(pwd)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar"
uv run pytest tests/integration/test_jcl_bridge_jar.py -v
```
Expected: 1 passed. If the model fields don't match, fix `JclSerializer`'s tree mapping (Task 1) — the JSON contract is the source of truth.

- [ ] **Step 8: Format + commit.**
```bash
uv run black jackal/jcl/bridge_parser.py tests/unit/test_jcl_bridge_parser.py tests/integration/test_jcl_bridge_jar.py tests/conftest.py
git add jackal/jcl/bridge_parser.py tests/unit/test_jcl_bridge_parser.py tests/integration/test_jcl_bridge_jar.py tests/conftest.py
git commit -m "feat(jcl): JclBridgeParser subprocess wrapper + jcl_bridge_jar fixture"
```

---

## Task 4: Rewire `parse_jcl` to the bridge, retire Lark, prove parity

**Files:**
- Modify: `jackal/jcl/parser.py`
- Delete: `jackal/jcl/grammar.lark`
- Modify: `tests/unit/test_jcl_parser.py` (becomes bridge-backed parity tests)
- Modify: `.pre-commit-config.yaml`

**Interfaces:**
- Consumes: `JclBridgeParser`, `JclSubprocessRunner` (Task 3).
- Produces: `parse_jcl(text: str) -> Job` (unchanged signature), now bridge-backed.

- [ ] **Step 1: Find all `parse_jcl` callers + Lark references.**
```bash
grep -rn "parse_jcl\|grammar.lark\|jcl.parser import\|from lark" jackal/ tests/ | grep -iv idcams
```
Expected callers: `jackal/cli.py`, `tests/unit/test_jcl_parser.py`, `tests/integration/test_pipeline.py`. (`jackal/idcams/parser.py` also uses `lark` — that is the IDCAMS parser and MUST be left untouched; the `lark` dependency stays in `pyproject.toml` for it.)

- [ ] **Step 2: Rewrite `jackal/jcl/parser.py` to delegate to the bridge.**
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
(Delete the entire previous Lark implementation — `_GRAMMAR`, `_PARSER`, `_Build`, `_assemble`, `_fold_steps`, `_disp_from_words`, `_DEFAULT_DISP`, and the `lark` import. Those helpers now live in `bridge_parser.py`.)

- [ ] **Step 3: Delete the Lark grammar.**
```bash
git rm jackal/jcl/grammar.lark
```

- [ ] **Step 4: Convert `tests/unit/test_jcl_parser.py` into bridge-backed parity tests.** These existing tests call `parse_jcl`, which now needs the JAR — add the `jcl_bridge_jar` fixture to each so they run against the real bridge (this IS the parity proof: same inputs, same expected model). Add the fixture parameter and an autouse env guard:
```python
import os
import pytest
from tests.covers import NotLanguageFeature, covers
from jackal.jcl.parser import parse_jcl
from jackal.model import DispNormal, DispStatus

@pytest.fixture(autouse=True)
def _require_jcl_bridge(jcl_bridge_jar):
    """parse_jcl now shells to the bridge; ensure JCL_BRIDGE_JAR is set."""

JCL = """//PIPE JOB 'demo'
//STEP1 EXEC PGM=UPCASE
//INDD DD DSN=J.IN,DISP=SHR
//WORKDD DD DSN=J.WORK,DISP=(NEW,PASS,DELETE)
//STEP2 EXEC PGM=STARRER
//WORKDD DD DSN=J.WORK,DISP=SHR
//OUTDD DD DSN=J.OUT,DISP=(NEW,CATLG,DELETE)
"""
```
Keep ALL existing assertions (job/steps/dds, DISP shorthand, continuation line, `DD *` in-stream capture, `DD SYSOUT=*`, the `DSN=…,DISP=SHR` regression). They must pass byte-for-byte identically through the bridge. If any fails, the bridge's JSON mapping (Task 1 `JclSerializer`) is wrong — fix it there, not by weakening the test.

- [ ] **Step 5: Run the parity tests (real JAR).**
```bash
export JCL_BRIDGE_JAR="$(pwd)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar"
uv run pytest tests/unit/test_jcl_parser.py -v
```
Expected: all existing cases pass. Investigate any diff against the old behavior as a bridge mapping bug (Task 1).

- [ ] **Step 6: Update `.pre-commit-config.yaml`** so the test hook exports `JCL_BRIDGE_JAR` alongside `PROLEAP_BRIDGE_JAR` (read the file; mirror the existing `PROLEAP_BRIDGE_JAR=...` export in the "Full test suite" hook, pointing at `jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar`).

- [ ] **Step 7: Full suite + gated e2e parity.**
```bash
export PROLEAP_BRIDGE_JAR="$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
export JCL_BRIDGE_JAR="$(pwd)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar"
export CARDDEMO_HOME="$HOME/code/aws-mainframe-carddemo/app"
uv run black .
uv run pytest -q
```
Expected: the entire suite green, INCLUDING `tests/integration/test_carddemo_acctfile_e2e.py` (which parses the real ACCTFILE/READACCT JCL — now through the bridge). This is the parity gate. Do NOT proceed to commit until green.

- [ ] **Step 8: Add a CardDemo parse-parity sweep (gated).** New test `tests/integration/test_jcl_bridge_carddemo_parse.py`:
```python
from pathlib import Path
from tests.covers import NotLanguageFeature, covers
from jackal.jcl.parser import parse_jcl

@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_carddemo_jobs_parse_via_bridge(carddemo_home, jcl_bridge_jar):
    jcl_dir = carddemo_home / "jcl"
    for name in ["ACCTFILE.jcl", "READACCT.jcl", "TRANBKP.jcl", "DEFGDGB.jcl"]:
        job = parse_jcl((jcl_dir / name).read_text())
        assert job.name and job.steps, f"{name} parsed empty"
```
Run: `uv run pytest tests/integration/test_jcl_bridge_carddemo_parse.py -v` → 1 passed (4 jobs parse non-empty). (Asserts the broader grammar parses real jobs the Lark parser could not.)

- [ ] **Step 9: Commit.**
```bash
git add jackal/jcl/parser.py tests/unit/test_jcl_parser.py tests/integration/test_jcl_bridge_carddemo_parse.py .pre-commit-config.yaml
git rm jackal/jcl/grammar.lark
git commit -m "refactor(jcl): parse via ANTLR bridge, retire Lark grammar (jackal-1o2.9)"
```

---

## Self-Review

**Spec coverage:**
- jcl-bridge Maven module + vendored `.g4` + LICENSE/PROVENANCE → Task 1 ✓
- JsonSerializer emitting the projected JSON contract → Task 1 ✓
- Python deserializer (projected model) → Task 2 ✓
- `JclBridgeParser` subprocess wrapper (proleap pattern) + `JclParseError` fail-loud → Task 3 ✓
- `parse_jcl` keeps signature, env-located JAR → Task 4 ✓
- Retire Lark grammar + Transformer → Task 4 ✓
- Parity gate (reuse existing tests + e2e green) → Task 4 Steps 4–7 ✓
- CardDemo parse-parity sweep → Task 4 Step 8 ✓
- Raw-parse-first (no JCLPP) → Task 1 vendors only the main lexer/parser; no preprocessor wiring ✓
- Vendor-not-submodule + provenance pinning → Task 1 Step 1 ✓
- Build wiring (`build.sh`, gitignored JAR, `JCL_BRIDGE_JAR`, pre-commit) → Task 1 Step 7, Task 3 Step 5, Task 4 Step 6 ✓
- `lark` stays for IDCAMS (not removed) → Task 4 Step 1 note ✓

**Placeholder scan:** No "TBD"/"add error handling"/"similar to". The one inherent unknown — mapa's exact internal rule names — is handled by an explicit discovery step (Task 1 Step 3, `antlr4-parse -tree`) rather than guessed, because those names live only in the vendored grammar the implementer copies in that task.

**Type consistency:** `_job_from_json`/`_step_from_json`/`_dd_from_json`, `_disp_from_words`, `_DEFAULT_DISP`, `JclBridgeParser(runner, bridge_jar).parse(text) -> Job`, `JclSubprocessRunner.run(command, input_data) -> str`, `JclParseError` — consistent across Tasks 2–4. JSON contract field names (`name`/`steps`/`pgm`/`dds`/`ddname`/`dsn`/`disp_words`/`in_stream`/`sysout`) identical in Task 1 (emitter) and Task 2 (consumer).
