# JCL Symbolic Value Type (Literal/Symbol) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `DirectDSN.name: str` and `Step.parm: str` with a typed value representation (`Value = tuple[Literal | Symbol, ...]`) so a JCL `&SYMBOL` reference is a distinct, structurally-classified type — never re-inferred from flattened text by pattern matching downstream.

**Architecture:** The `jcl-bridge` Java lexer already classifies a `&NAME` reference as a distinct `SYMBOLIC` token type (separate from ordinary literal text, and separate from the `&&NAME`/`*.STEP.DD` special forms, which tokenize as `KEYWORD_VALUE` and never compete with `SYMBOLIC` — verified empirically, see Task 2). `JclSerializer.java` currently discards that classification, flattening every value to one string via `getText()`. This plan changes the JSON contract for `"dsn"`/`"parm"` from a flat string to an ordered array of `{"type": "Literal"|"Symbol", "name": ...}` parts, built by walking the parse tree's terminal nodes and classifying each by its actual ANTLR token type — never by regex or string-pattern inference on already-flattened text. Every existing Python consumer that touches a DSN name or PARM value as a plain string is updated to call `resolve()`, which concatenates an all-`Literal` `Value` to `str` and raises loudly if any `Symbol` part survived unresolved (a real correctness improvement — today an unresolved `&SYMBOL` would silently flow through as if it were a literal dataset name).

**Tech Stack:** Python 3.13 (dataclasses, `match`/`case`), Java 17 (ANTLR4, Gson), pytest.

## Global Constraints

- TDD throughout: write the failing test, run it, watch it fail, implement, run it again, watch it pass, commit. No exceptions, including for the Java-side change (verified via direct JAR invocation before any Python test is written against it).
- No regex, no string-pattern inference for symbol detection anywhere in this plan. Classification comes only from the ANTLR token type (`JCLLexer.SYMBOLIC`).
- Every existing test that currently asserts `dd.dsn == DirectDSN("...")` or `step.parm == "..."` is updated in place to construct/compare against the new `Value` type — never worked around, never left broken, never skipped.
- `PROLEAP_BRIDGE_JAR` is not needed for this plan (no COBOL parsing involved). `JCL_BRIDGE_JAR` must be set for every task that runs a real-bridge test — build it first if `jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar` is missing or stale: `cd jackal/jcl-bridge && mvn -DskipTests package -q`.
- Run tests from the repo root: `cd ~/code/red-dragon-forge`.

---

## File Structure

| File | Responsibility |
|---|---|
| `jackal/jackal/value_parts.py` (new) | `Literal`, `Symbol`, `ValuePart`, `Value` types; `resolve()`, `literal()` |
| `jackal/jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java` | Emits structured `Value` parts for `"dsn"`/`"parm"` instead of flat strings |
| `jackal/jackal/dsn.py` | `DirectDSN.name: Value`; `dsn_key()` resolves |
| `jackal/jackal/model.py` | `Step.parm: Value` |
| `jackal/jackal/jcl/bridge_parser.py` | Deserializes the new structured JSON shape into `Value` |
| `jackal/jackal/catalog.py` | Resolves `Value` to `str` at its two `DirectDSN(name=name)` match sites |
| `jackal/jackal/jcl_graph.py` | Resolves `Value` to `str` when building a `DATASET` node id |
| `jackal/jackal/cobol_step.py` | Resolves `Value` to `str` before building the PARM region |
| `jackal/jackal/runner.py` | Constructs a `Value` (not a plain string) when building a `DirectDSN` from a stripped `TempRef` alias |

---

## Task 1: `value_parts.py` — the new type

**Files:**
- Create: `jackal/jackal/value_parts.py`
- Test: `jackal/tests/unit/test_value_parts.py`

**Interfaces:**
- Produces: `Literal(text: str)`, `Symbol(name: str)`, `type ValuePart = Literal | Symbol`, `type Value = tuple[ValuePart, ...]`, `resolve(value: Value) -> str`, `literal(text: str) -> Value`.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for the Literal/Symbol value-part type."""

from __future__ import annotations

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.value_parts import Literal, Symbol, literal, resolve


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_literal_helper_builds_single_literal_part():
    assert literal("A.B") == (Literal("A.B"),)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_literal_helper_empty_string_is_empty_value():
    assert literal("") == (Literal(""),)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_concatenates_literal_parts():
    value = (Literal("A."), Literal("B"))
    assert resolve(value) == "A.B"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_empty_tuple_is_empty_string():
    assert resolve(()) == ""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_raises_on_unresolved_symbol():
    value = (Symbol("CNTLLIB"),)
    with pytest.raises(ValueError, match="CNTLLIB"):
        resolve(value)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_raises_on_symbol_mixed_with_literal():
    value = (Symbol("CNTLLIB"), Literal("(REPROCT)"))
    with pytest.raises(ValueError, match="CNTLLIB"):
        resolve(value)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_literal_and_symbol_are_frozen_and_hashable():
    assert hash(Literal("A")) == hash(Literal("A"))
    assert hash(Symbol("A")) == hash(Symbol("A"))
    assert Literal("A") != Symbol("A")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync python -m pytest jackal/tests/unit/test_value_parts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jackal.value_parts'`

- [ ] **Step 3: Write the implementation**

```python
"""Literal/Symbol value parts: the typed replacement for a plain str wherever
a JCL value (a DSN name, a PARM) can contain either literal text or a
&SYMBOL reference. A part's classification always comes from the jcl-bridge
lexer's own SYMBOLIC token type (see JclSerializer.java's buildValueParts) —
never re-inferred here from string content.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Literal:
    text: str


@dataclass(frozen=True)
class Symbol:
    name: str  # symbol name, no leading '&'


type ValuePart = Literal | Symbol
type Value = tuple[ValuePart, ...]


def literal(text: str) -> Value:
    """Build a Value out of a single, already-known-literal string."""
    return (Literal(text),)


def resolve(value: Value) -> str:
    """Concatenate value to a plain string.

    Raises ValueError naming the symbol if any part is an unresolved Symbol
    — a genuine correctness improvement over silently carrying "&SYMBOL" as
    if it were literal dataset-name text.
    """
    parts: list[str] = []
    for part in value:
        match part:
            case Literal(text=t):
                parts.append(t)
            case Symbol(name=n):
                raise ValueError(f"Unresolved symbol '&{n}' in value {value!r}")
    return "".join(parts)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-sync python -m pytest jackal/tests/unit/test_value_parts.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add jackal/jackal/value_parts.py jackal/tests/unit/test_value_parts.py
git commit -m "feat: add Literal/Symbol value-part type for JCL DSN/PARM values"
```

---

## Task 2: `JclSerializer.java` — structured `"dsn"`/`"parm"` JSON

**Files:**
- Modify: `jackal/jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java`

**Interfaces:**
- Consumes: nothing new (same ANTLR parse tree it already builds).
- Produces: `"dsn"` and `"parm"` JSON fields change from a flat string to a JSON array of `{"type": "Literal"|"Symbol", "name": "..."}` objects. Empty value → `[]` (was `""`).

This task has no Python-side test — it's verified by direct JAR invocation, matching the pattern already used in this session for grammar/serializer changes (`java -jar ... < input.jcl`). Task 3 adds the Python-side test that exercises this through `bridge_parser.py`.

- [ ] **Step 1: Confirm current (pre-change) flat-string behavior**

Build the JAR if stale: `cd jackal/jcl-bridge && mvn -DskipTests package -q`

Run:
```bash
cat > /tmp/valparts.jcl << 'EOF'
//J JOB 1
//S EXEC PGM=IDCAMS,PARM='HELLO'
//D DD DISP=SHR,DSN=&CNTLLIB(REPROCT)
//W DD DSN=&&TEMP,DISP=(NEW,PASS)
EOF
java -jar ~/code/red-dragon-forge/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar < /tmp/valparts.jcl
```
Expected (current, pre-change): `"dsn":"&CNTLLIB(REPROCT)"`, `"dsn":"&&TEMP"`, `"parm":"HELLO"` — flat strings.

- [ ] **Step 2: Add `buildValueParts` and wire it into `buildDd`/`buildStep`**

In `JobBuilder`, add this new private method (place it near `extractWords`, e.g. directly after it):

```java
        /**
         * Build an ordered list of {"type":"Symbol"|"Literal","name":...}
         * parts from a parse-tree node, classified by each terminal's own
         * lexer token type (JCLLexer.SYMBOLIC vs everything else) — never
         * inferred from text content. Hidden-channel tokens (e.g. the
         * apostrophes around a quoted PARM value) are not tree children and
         * so are naturally excluded — no separate stripping needed. Adjacent
         * non-SYMBOLIC terminals are merged into one Literal part.
         */
        private JsonArray buildValueParts(ParseTree ctx) {
            JsonArray parts = new JsonArray();
            StringBuilder literalRun = new StringBuilder();
            collectValueParts(ctx, parts, literalRun);
            flushLiteral(parts, literalRun);
            return parts;
        }

        private void collectValueParts(ParseTree node, JsonArray parts, StringBuilder literalRun) {
            if (node instanceof TerminalNode) {
                TerminalNode tn = (TerminalNode) node;
                int type = tn.getSymbol().getType();
                if (type == JCLLexer.SYMBOLIC) {
                    flushLiteral(parts, literalRun);
                    String text = tn.getText(); // e.g. "&CNTLLIB"
                    JsonObject part = new JsonObject();
                    part.addProperty("type", "Symbol");
                    part.addProperty("name", text.substring(1)); // strip leading '&'
                    parts.add(part);
                } else {
                    literalRun.append(tn.getText());
                }
                return;
            }
            for (int i = 0; i < node.getChildCount(); i++) {
                collectValueParts(node.getChild(i), parts, literalRun);
            }
        }

        private void flushLiteral(JsonArray parts, StringBuilder literalRun) {
            if (literalRun.length() > 0) {
                JsonObject part = new JsonObject();
                part.addProperty("type", "Literal");
                part.addProperty("name", literalRun.toString());
                parts.add(part);
                literalRun.setLength(0);
            }
        }
```

Change the `DdParamFields` record's `dsn` field from `String` to `JsonArray`, and its `empty()` factory:

```java
        /** Immutable accumulator for one ddStatement's ddParameter children. */
        private record DdParamFields(
                JsonArray dsn,
                JsonArray dispWords,
                boolean sysout,
                boolean dummy,
                boolean isAsterisk,
                JsonObject backref) {

            static DdParamFields empty() {
                return new DdParamFields(new JsonArray(), new JsonArray(), false, false, false, null);
            }
        }
```

Change `foldDsname` to emit structured parts instead of the flat string, keeping the existing `raw`-based backward-ref detection exactly as-is (it's an internal classification, not part of the emitted `"dsn"` value):

```java
        /** Fold a DSNAME parameter: a direct dataset name, or a two/three-segment backward reference. */
        private DdParamFields foldDsname(DdParamFields acc, JCLParser.DdParmDSNAMEContext dsnCtx) {
            JCLParser.DatasetNameContext datasetName =
                    findChild(dsnCtx, JCLParser.DatasetNameContext.class);
            if (datasetName == null) {
                return acc;
            }
            String raw = datasetName.getText();
            if (!raw.startsWith("*.")) {
                return new DdParamFields(
                        buildValueParts(datasetName), acc.dispWords(), acc.sysout(), acc.dummy(),
                        acc.isAsterisk(), acc.backref());
            }
            // backward reference: *.STEPNAME.DDNAME (two-segment) or longer
            String[] parts = raw.substring(2).split("\\.");
            if (parts.length != 2) {
                // three-segment or malformed — pass structured parts; Python raises ValueError
                return new DdParamFields(
                        buildValueParts(datasetName), acc.dispWords(), acc.sysout(), acc.dummy(),
                        acc.isAsterisk(), acc.backref());
            }
            JsonObject backref = new JsonObject();
            backref.addProperty("step", parts[0]);
            backref.addProperty("ddname", parts[1]);
            // leave dsn=[] — Python parser dispatches on "backref" key first
            return new DdParamFields(
                    new JsonArray(), acc.dispWords(), acc.sysout(), acc.dummy(), acc.isAsterisk(), backref);
        }
```

Change `buildDd`'s final emission from `dd.addProperty("dsn", dsn)` (String overload) to `dd.add("dsn", dsn)` (JsonArray overload) — locate this line inside `buildDd`:

```java
            dd.addProperty("dsn", dsn);
```

replace with:

```java
            dd.add("dsn", dsn);
```

and change the local variable declaration two lines above it from `String dsn = fields.dsn();` to `JsonArray dsn = fields.dsn();`.

Also update `buildDd`'s early-return-on-null-ddStmt branch (the `if (ddStmt == null) { ... }` block near the top of `buildDd`), which currently does `empty.addProperty("dsn", "");` — change to `empty.add("dsn", new JsonArray());`.

Change `buildStep`'s PARM handling from flat-string extraction to structured parts. Replace:

```java
            // PARM= on the EXEC statement
            String parm = "";
            if (execStmt != null) {
                JCLParser.ExecParmPARMContext parmCtx =
                        findChild(execStmt, JCLParser.ExecParmPARMContext.class);
                if (parmCtx != null) {
                    JCLParser.KeywordOrSymbolicContext kwCtx =
                            findChild(parmCtx, JCLParser.KeywordOrSymbolicContext.class);
                    if (kwCtx != null) {
                        String raw = kwCtx.getText();
                        // Strip surrounding apostrophes from JCL quoted string convention
                        if (raw.startsWith("'") && raw.endsWith("'") && raw.length() >= 2) {
                            raw = raw.substring(1, raw.length() - 1);
                        }
                        parm = raw;
                    }
                }
            }
            step.addProperty("parm", parm);
```

with:

```java
            // PARM= on the EXEC statement
            JsonArray parmParts = new JsonArray();
            if (execStmt != null) {
                JCLParser.ExecParmPARMContext parmCtx =
                        findChild(execStmt, JCLParser.ExecParmPARMContext.class);
                if (parmCtx != null) {
                    JCLParser.KeywordOrSymbolicContext kwCtx =
                            findChild(parmCtx, JCLParser.KeywordOrSymbolicContext.class);
                    if (kwCtx != null) {
                        parmParts = buildValueParts(kwCtx);
                    }
                }
            }
            step.add("parm", parmParts);
```

- [ ] **Step 3: Rebuild the JAR**

```bash
cd jackal/jcl-bridge && mvn -DskipTests package -q
```

- [ ] **Step 4: Re-run the manual check from Step 1 and verify the new shape**

```bash
java -jar ~/code/red-dragon-forge/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar < /tmp/valparts.jcl
```
Expected:
- `"dsn":[{"type":"Symbol","name":"CNTLLIB"},{"type":"Literal","name":"(REPROCT)"}]`
- `"dsn":[{"type":"Literal","name":"&&TEMP"}]`
- `"parm":[{"type":"Literal","name":"HELLO"}]`

If `"parm"` instead comes back with leading/trailing apostrophes still present (e.g. `"'HELLO'"` split into parts) — that means the hidden-channel-token exclusion assumption in the `buildValueParts` docstring was wrong for this specific token path; if so, add an explicit skip for `SQUOTE`-typed terminals inside `collectValueParts` (check `type == JCLLexer.SQUOTE` alongside the `SYMBOLIC` check) before proceeding to Task 3. Do not proceed past this step until the output matches exactly.

- [ ] **Step 5: Commit**

```bash
git add jackal/jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java
git commit -m "feat(jcl-bridge): emit structured Literal/Symbol parts for dsn/parm instead of flat strings"
```

---

## Task 3: Core type change — `dsn.py`, `model.py`, `bridge_parser.py`

These three are interdependent (changing one without the others leaves broken types), so they land together. Their own direct unit/integration tests (`test_dsn.py`, `test_model.py`, `test_jcl_bridge_parser.py`, `test_jcl_bridge_jar.py`, `test_jcl_parser.py`) are updated in the same task.

**Files:**
- Modify: `jackal/jackal/dsn.py`
- Modify: `jackal/jackal/model.py`
- Modify: `jackal/jackal/jcl/bridge_parser.py`
- Modify: `jackal/tests/unit/test_dsn.py`
- Modify: `jackal/tests/unit/test_model.py`
- Modify: `jackal/tests/unit/test_jcl_bridge_parser.py`
- Modify: `jackal/tests/integration/test_jcl_bridge_jar.py`
- Modify: `jackal/tests/unit/test_jcl_parser.py`

**Interfaces:**
- Consumes: `jackal.value_parts.{Literal, Symbol, Value, ValuePart, literal, resolve}` (Task 1).
- Produces: `DirectDSN.name: Value` (was `str`), `Step.parm: Value` (was `str`), `dsn_key(dsn: DSN) -> str` (return type unchanged — now resolves internally).

- [ ] **Step 1: Update the failing tests first**

Edit `jackal/tests/unit/test_dsn.py` — replace the whole file:

```python
"""Unit tests for the DSN type hierarchy."""

from __future__ import annotations

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.value_parts import literal, Symbol


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_direct_dsn_name():
    from jackal.dsn import DirectDSN

    assert DirectDSN(literal("MY.DS")).name == literal("MY.DS")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_ref_alias():
    from jackal.dsn import TempRef

    assert TempRef("&&WORKIN").alias == "&&WORKIN"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_direct_dsn_equality():
    from jackal.dsn import DirectDSN

    assert DirectDSN(literal("A")) == DirectDSN(literal("A"))
    assert DirectDSN(literal("A")) != DirectDSN(literal("B"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_ref_equality():
    from jackal.dsn import TempRef

    assert TempRef("&&A") == TempRef("&&A")
    assert TempRef("&&A") != TempRef("&&B")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_key_extracts_direct_name():
    from jackal.dsn import DirectDSN, dsn_key

    assert dsn_key(DirectDSN(literal("MY.DS"))) == "MY.DS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_key_raises_for_unresolved_symbol():
    from jackal.dsn import DirectDSN, dsn_key

    with pytest.raises(ValueError, match="CNTLLIB"):
        dsn_key(DirectDSN((Symbol("CNTLLIB"),)))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_key_raises_for_temp_ref():
    from jackal.dsn import TempRef, dsn_key

    with pytest.raises(TypeError, match="TempRef"):
        dsn_key(TempRef("&&WORKIN"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_backward_ref_fields():
    from jackal.dsn import BackwardRef

    br = BackwardRef(step="STEP1", ddname="WRK")
    assert br.step == "STEP1"
    assert br.ddname == "WRK"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_backward_ref_equality():
    from jackal.dsn import BackwardRef

    assert BackwardRef("STEP1", "WRK") == BackwardRef("STEP1", "WRK")
    assert BackwardRef("STEP1", "WRK") != BackwardRef("STEP2", "WRK")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_key_raises_for_backward_ref():
    from jackal.dsn import BackwardRef, dsn_key

    with pytest.raises(TypeError, match="BackwardRef"):
        dsn_key(BackwardRef("STEP1", "WRK"))
```

Edit `jackal/tests/unit/test_model.py` — lines 1-16, replace:

```python
from tests.covers import covers, NotLanguageFeature
from jackal.dsn import DirectDSN
from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step
from jackal.value_parts import literal


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_job_model_construction():
    dd = DD(
        ddname="INDD",
        dsn=DirectDSN(literal("J.IN")),
        disp=Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP),
    )
    step = Step(name="STEP1", pgm="UPCASE", dds=(dd,))
    job = Job(name="PIPE", steps=(step,))
    assert job.steps[0].dds[0].ddname == "INDD"
    assert job.steps[0].dds[0].disp.status is DispStatus.SHR
```

And line 25 (inside `test_dd_instream_and_sysout_and_org`), change:
```python
        dsn=DirectDSN(""),
```
to:
```python
        dsn=DirectDSN(()),
```

Edit `jackal/tests/unit/test_jcl_bridge_parser.py` — replace the whole file:

```python
import json
import pytest
from tests.covers import NotLanguageFeature, covers
from jackal.dsn import DirectDSN
from jackal.jcl.bridge_parser import JclBridgeParser, JclParseError
from jackal.value_parts import literal


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
    out = json.dumps(
        {
            "name": "J",
            "steps": [
                {
                    "name": "S",
                    "pgm": "P",
                    "dds": [
                        {
                            "ddname": "D",
                            "dsn": [{"type": "Literal", "name": "A.B"}],
                            "disp_words": ["SHR"],
                            "in_stream": [],
                            "sysout": False,
                        }
                    ],
                }
            ],
        }
    )
    runner = _FakeRunner(out=out)
    job = JclBridgeParser(runner, "jcl.jar").parse("//J JOB 1\n")
    assert job.steps[0].dds[0].dsn == DirectDSN(literal("A.B"))
    assert runner.command == ["java", "-jar", "jcl.jar"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_builds_symbol_part_from_bridge_json():
    out = json.dumps(
        {
            "name": "J",
            "steps": [
                {
                    "name": "S",
                    "pgm": "P",
                    "dds": [
                        {
                            "ddname": "D",
                            "dsn": [
                                {"type": "Symbol", "name": "CNTLLIB"},
                                {"type": "Literal", "name": "(REPROCT)"},
                            ],
                            "disp_words": ["SHR"],
                            "in_stream": [],
                            "sysout": False,
                        }
                    ],
                }
            ],
        }
    )
    runner = _FakeRunner(out=out)
    job = JclBridgeParser(runner, "jcl.jar").parse("//J JOB 1\n")
    from jackal.dsn import DirectDSN
    from jackal.value_parts import Literal, Symbol

    assert job.steps[0].dds[0].dsn == DirectDSN((Symbol("CNTLLIB"), Literal("(REPROCT)")))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_propagates_bridge_failure():
    runner = _FakeRunner(exc=JclParseError("boom"))
    with pytest.raises(JclParseError):
        JclBridgeParser(runner, "jcl.jar").parse("garbage")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_raises_on_malformed_json():
    runner = _FakeRunner(out="not json{")
    with pytest.raises(JclParseError):
        JclBridgeParser(runner, "jcl.jar").parse("//J JOB\n")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_raises_on_missing_required_key():
    # step is missing "name" — KeyError in _step_from_json
    out = json.dumps({"name": "J", "steps": [{"pgm": "P", "dds": []}]})
    runner = _FakeRunner(out=out)
    with pytest.raises(JclParseError):
        JclBridgeParser(runner, "jcl.jar").parse("//J JOB\n")
```

Edit `jackal/tests/integration/test_jcl_bridge_jar.py` — replace the whole file:

```python
from tests.covers import NotLanguageFeature, covers
from jackal.dsn import DirectDSN
from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner
from jackal.value_parts import Literal, Symbol, literal


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_simple_job(jcl_bridge_jar):
    jcl = "//PIPE JOB 1\n//STEP1 EXEC PGM=UPCASE\n//INDD DD DSN=J.IN,DISP=SHR\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.name == "PIPE"
    assert job.steps[0].pgm == "UPCASE"
    assert job.steps[0].dds[0].dsn == DirectDSN(literal("J.IN"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_proc_step(jcl_bridge_jar):
    jcl = "//J JOB 1\n//STEP1 EXEC PROC=MYPROC\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].pgm == "MYPROC"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_parm(jcl_bridge_jar):
    jcl = "//J JOB 1\n//STEP1 EXEC PGM=CBACT04C,PARM='2022071800'\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].parm == literal("2022071800")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_absent_parm_is_empty_value(jcl_bridge_jar):
    jcl = "//J JOB 1\n//STEP1 EXEC PGM=MYPGM\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].parm == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_symbolic_dsn(jcl_bridge_jar):
    jcl = "//J JOB 1\n//STEP1 EXEC PGM=IDCAMS\n//D DD DISP=SHR,\n//   DSN=&CNTLLIB(REPROCT)\n"
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    assert job.steps[0].dds[0].dsn == DirectDSN((Symbol("CNTLLIB"), Literal("(REPROCT)")))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_real_jar_parses_backward_ref(jcl_bridge_jar):
    jcl = (
        "//J JOB 1\n"
        "//STEP1 EXEC PGM=IEFBR14\n"
        "//WRK DD DSN=MY.FILE,DISP=(NEW,PASS)\n"
        "//STEP2 EXEC PGM=IEFBR14\n"
        "//INPUT DD DSN=*.STEP1.WRK,DISP=(OLD,DELETE)\n"
    )
    from jackal.dsn import BackwardRef

    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    dd = job.steps[1].dds[0]
    assert isinstance(dd.dsn, BackwardRef)
    assert dd.dsn.step == "STEP1"
    assert dd.dsn.ddname == "WRK"
```

Edit `jackal/tests/unit/test_jcl_parser.py` — add the import and change two assertions. Add to the import block at the top (after `from jackal.model import DispNormal, DispStatus`):
```python
from jackal.value_parts import literal
```

Change line 52 (in `test_dd_continuation_line`) from:
```python
    assert dd.dsn == DirectDSN("A.B") and dd.disp.status is DispStatus.NEW
```
to:
```python
    assert dd.dsn == DirectDSN(literal("A.B")) and dd.disp.status is DispStatus.NEW
```

Change line 95 (in `test_dsn_disp_still_parses`) from:
```python
    assert parse_jcl(jcl).steps[0].dds[0].dsn == DirectDSN("A.B")
```
to:
```python
    assert parse_jcl(jcl).steps[0].dds[0].dsn == DirectDSN(literal("A.B"))
```

- [ ] **Step 2: Run all six test files to verify they fail**

```bash
uv run --no-sync python -m pytest jackal/tests/unit/test_dsn.py jackal/tests/unit/test_model.py jackal/tests/unit/test_jcl_bridge_parser.py -v
```
Expected: FAIL — `DirectDSN(literal("MY.DS"))` etc. don't type-check against the current `str`-typed `name` field, or `TypeError`/`AttributeError` from `jackal.value_parts` not yet being imported into `dsn.py`'s expectations. (The two integration files require `JCL_BRIDGE_JAR` and the *already-modified* Task 2 JAR — run them too, expect them to fail on the now-mismatched flat-string JSON contract if the JAR is stale, or on Python-side type mismatch once the JAR is current.)

- [ ] **Step 3: Update `dsn.py`**

Replace the whole file:

```python
"""DSN type hierarchy: DirectDSN for permanent datasets, TempRef for &&NAME
temps, BackwardRef for *.STEP.DD references resolved at runtime by the
runner, InStreamDSN for instream data (DD *), DummyDSN for an explicit null
dataset (DD DUMMY), and NoDSN for a DD whose empty DSN isn't explained by any
of the above (currently: SYSOUT — has its own dd.sysout flag everywhere it
matters — or a genuine gap worth treating with suspicion)."""

from __future__ import annotations

from dataclasses import dataclass

from jackal.value_parts import Value, resolve


@dataclass(frozen=True)
class DirectDSN:
    name: Value


@dataclass(frozen=True)
class TempRef:
    alias: str  # full &&NAME string, e.g. "&&WORKIN"


@dataclass(frozen=True)
class BackwardRef:
    step: str  # step name, e.g. "STEP1"
    ddname: str  # DD name, e.g. "WRK"


@dataclass(frozen=True)
class InStreamDSN:
    """A DD fed by literal inline data (DD * / DD DATA) rather than a
    catalogued dataset. Carries no fields of its own — the actual content
    stays in DD.in_stream, which already exists for this; this is purely a
    type discriminant so callers can tell "positively identified as instream
    data" apart from NoDSN's "unexplained empty DSN"."""


@dataclass(frozen=True)
class DummyDSN:
    """An explicit null dataset (DD DUMMY): reads hit EOF immediately,
    writes are discarded. A deliberate, well-formed JCL construct — not an
    error, and not the same as NoDSN's "unexplained empty DSN"."""


@dataclass(frozen=True)
class NoDSN:
    """A DD with an empty DSN not explained by InStreamDSN or DummyDSN —
    currently SYSOUT (DD SYSOUT=*), which already has its own dd.sysout flag
    checked everywhere it matters, so nothing is lost by routing it here."""


type DSN = DirectDSN | TempRef | BackwardRef | InStreamDSN | DummyDSN | NoDSN


def dsn_key(dsn: DSN) -> str:
    """Extract the string DSN name from a DirectDSN, resolving its Value.

    Raises ValueError if the DirectDSN's Value has an unresolved Symbol part.
    Raises TypeError for every other DSN variant — none of them can be used
    as a string key (TempRef/BackwardRef must first be resolved via the
    catalog / runner; InStreamDSN/DummyDSN/NoDSN have no dataset to resolve
    to at all).
    """
    match dsn:
        case DirectDSN(name=n):
            return resolve(n)
        case TempRef(alias=a):
            raise TypeError(f"TempRef '{a}' must be resolved via the catalog")
        case BackwardRef(step=s, ddname=d):
            raise TypeError(f"BackwardRef '*.{s}.{d}' must be resolved via the runner")
        case InStreamDSN():
            raise TypeError("InStreamDSN has no dataset to resolve to")
        case DummyDSN():
            raise TypeError("DummyDSN has no dataset to resolve to")
        case NoDSN():
            raise TypeError("NoDSN has no dataset to resolve to")
        case _:
            raise TypeError(f"Unhandled DSN type: {dsn!r}")
```

- [ ] **Step 4: Update `model.py`**

Change line 8 (import) from:
```python
from jackal.dsn import DSN
```
to:
```python
from jackal.dsn import DSN
from jackal.value_parts import Value
```

Change line 68 (the `Step.parm` field) from:
```python
    parm: str = ""
```
to:
```python
    parm: Value = ()
```

- [ ] **Step 5: Update `bridge_parser.py`**

Replace the whole file:

```python
"""Bridge to the jcl-bridge JAR: JSON AST -> Job, and the JSON->model deserializer."""

from __future__ import annotations

import json
import subprocess

from jackal.dsn import (
    DSN,
    DirectDSN,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    TempRef,
    BackwardRef,
)
from jackal.model import Cond, CondOp, DD, Disp, DispNormal, DispStatus, Job, Step
from jackal.value_parts import Literal, Symbol, Value, resolve

_DEFAULT_DISP = Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)


def _value_from_json(parts: list[dict]) -> Value:
    result: list[Literal | Symbol] = []
    for part in parts:
        if part["type"] == "Symbol":
            result.append(Symbol(part["name"]))
        else:
            result.append(Literal(part["name"]))
    return tuple(result)


def _disp_from_words(words: tuple[str, ...]) -> Disp:
    status = DispStatus(words[0])
    normal = DispNormal(words[1]) if len(words) > 1 else DispNormal.KEEP
    abnormal = DispNormal(words[2]) if len(words) > 2 else normal
    return Disp(status, normal, abnormal)


def _dd_from_json(d: dict) -> DD:
    words = tuple(d.get("disp_words", ()))
    disp = _disp_from_words(words) if words else _DEFAULT_DISP
    dsn_value = _value_from_json(d.get("dsn", []))
    raw_dsn = resolve(dsn_value) if not any(isinstance(p, Symbol) for p in dsn_value) else ""
    if "backref" in d:
        br = d["backref"]
        dsn: DSN = BackwardRef(step=br["step"], ddname=br["ddname"])
    elif raw_dsn.startswith("*."):
        raise ValueError(
            f"Three-segment backward reference '{raw_dsn}' is not yet supported "
            "(see jackal-lz8 — requires PROC support from jackal-1o2.2)"
        )
    elif raw_dsn.startswith("&&"):
        dsn = TempRef(raw_dsn)
    elif raw_dsn == "" and d.get("dummy", False):
        dsn = DummyDSN()
    elif raw_dsn == "" and d.get("in_stream"):
        dsn = InStreamDSN()
    elif raw_dsn == "" and not dsn_value:
        dsn = NoDSN()
    else:
        dsn = DirectDSN(dsn_value)
    return DD(
        ddname=d["ddname"],
        dsn=dsn,
        disp=disp,
        in_stream=tuple(d.get("in_stream", ())),
        sysout=d.get("sysout", False),
    )


def _cond_from_json(c: dict) -> Cond:
    return Cond(code=c["code"], op=CondOp(c["op"]), step=c.get("step", ""))


def _step_from_json(s: dict) -> Step:
    return Step(
        name=s["name"],
        pgm=s["pgm"],
        dds=tuple(_dd_from_json(d) for d in s["dds"]),
        conds=tuple(_cond_from_json(c) for c in s.get("cond", ())),
        parm=_value_from_json(s.get("parm", [])),
    )


def _job_from_json(data: dict) -> Job:
    return Job(
        name=data["name"],
        steps=tuple(_step_from_json(s) for s in data["steps"]),
        cond=tuple(_cond_from_json(c) for c in data.get("cond", ())),
    )


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
        try:
            return _job_from_json(json.loads(out))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            snippet = out[:120].replace("\n", " ")
            raise JclParseError(
                f"bridge returned malformed/incomplete JSON: {e} — output: {snippet!r}"
            ) from e
```

Note on `_dd_from_json`: the `raw_dsn` prefix checks (`"*."`, `"&&"`) need the *resolved* text, but only when it's safe to resolve (no `Symbol` part present) — a genuinely symbolic DSN (e.g. `&CNTLLIB(REPROCT)`, parsed while reading a `.prc` file's raw text through this same function) must not raise here just because `_dd_from_json` speculatively tried to resolve it for prefix-checking. The `raw_dsn = resolve(...) if not any(...) else ""` guard exists for exactly this: a DSN with any `Symbol` part skips straight to the final `else: dsn = DirectDSN(dsn_value)` branch, carrying the unresolved `Value` through unchanged, since none of the `*.`/`&&`/dummy/instream/empty special cases can apply to it anyway. Verify this precisely in Step 6 below — this is the one piece of new logic in this task that isn't a direct mechanical port of the old string-based code — if any test constructed to cover the symbolic-DSN case in this file fails, this is the line to re-examine first.

- [ ] **Step 6: Run all six test files again to verify they pass**

```bash
uv run --no-sync python -m pytest jackal/tests/unit/test_dsn.py jackal/tests/unit/test_model.py jackal/tests/unit/test_jcl_bridge_parser.py -v
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest jackal/tests/integration/test_jcl_bridge_jar.py jackal/tests/unit/test_jcl_parser.py -v
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add jackal/jackal/dsn.py jackal/jackal/model.py jackal/jackal/jcl/bridge_parser.py \
        jackal/tests/unit/test_dsn.py jackal/tests/unit/test_model.py \
        jackal/tests/unit/test_jcl_bridge_parser.py jackal/tests/integration/test_jcl_bridge_jar.py \
        jackal/tests/unit/test_jcl_parser.py
git commit -m "feat: migrate DirectDSN.name and Step.parm to the typed Literal/Symbol Value"
```

---

## Task 4: `catalog.py` consumers

**Files:**
- Modify: `jackal/jackal/catalog.py`
- Modify: `jackal/tests/unit/test_catalog.py`
- Modify: `jackal/tests/unit/test_utilities.py`

**Interfaces:**
- Consumes: `jackal.value_parts.{literal, resolve}` (Task 1), `DirectDSN.name: Value` (Task 3).

- [ ] **Step 1: Update the failing tests first**

Edit `jackal/tests/unit/test_catalog.py` — add the import (after `from tests.covers import covers, NotLanguageFeature`):
```python
from jackal.value_parts import literal
```

Change the `_dd` helper (lines 11-14) from:
```python
def _dd(dsn: str, status: DispStatus, normal: DispNormal = DispNormal.KEEP) -> DD:
    return DD(
        ddname="D", dsn=DirectDSN(dsn), disp=Disp(status, normal, DispNormal.DELETE)
    )
```
to:
```python
def _dd(dsn: str, status: DispStatus, normal: DispNormal = DispNormal.KEEP) -> DD:
    return DD(
        ddname="D", dsn=DirectDSN(literal(dsn)), disp=Disp(status, normal, DispNormal.DELETE)
    )
```

Change line 61 (in `test_shr_resolves_from_data_dir`) from:
```python
        "D", DirectDSN("A.B.PS"), Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)
```
to:
```python
        "D", DirectDSN(literal("A.B.PS")), Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)
```

Change line 140 (in `test_open_dataset_ps_empty_returns_eof`) from:
```python
        DirectDSN("J.FLAT"),
```
to:
```python
        DirectDSN(literal("J.FLAT")),
```

Edit `jackal/tests/unit/test_utilities.py` — add the import (after `from jackal.dsn import DirectDSN`):
```python
from jackal.value_parts import literal
```

Change line 14 (in `test_iefbr14_allocates_then_deletes`) from:
```python
        dsn=DirectDSN("J.TMP"),
```
to:
```python
        dsn=DirectDSN(literal("J.TMP")),
```

Change line 29 (in `test_iefbr14_skips_sysout_dd`) from:
```python
        dsn=DirectDSN(""),
```
to:
```python
        dsn=DirectDSN(()),
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run --no-sync python -m pytest jackal/tests/unit/test_catalog.py jackal/tests/unit/test_utilities.py -v
```
Expected: FAIL — `catalog.py`'s `case DirectDSN(name=name):` binds `name` to a `Value` tuple, then does `self._datasets[name]` / `self._data_dir / name` / `name.replace(".", "_")`, all of which require `str`, so these raise `TypeError`.

- [ ] **Step 3: Update `catalog.py`**

Change line 10 (import) from:
```python
from jackal.dsn import DirectDSN, TempRef
```
to:
```python
from jackal.dsn import DirectDSN, TempRef
from jackal.value_parts import resolve
```

Change line 58 (in `allocate`) from:
```python
            case DirectDSN(name=name):
                return self._allocate_direct(name, dd)
```
to:
```python
            case DirectDSN(name=name):
                return self._allocate_direct(resolve(name), dd)
```

Change line 164 (in `dispose`) from:
```python
            case DirectDSN(name=name):
                self.delete_dsn(name)
```
to:
```python
            case DirectDSN(name=name):
                self.delete_dsn(resolve(name))
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run --no-sync python -m pytest jackal/tests/unit/test_catalog.py jackal/tests/unit/test_utilities.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add jackal/jackal/catalog.py jackal/tests/unit/test_catalog.py jackal/tests/unit/test_utilities.py
git commit -m "feat: resolve DirectDSN.name Value to str at catalog.py's two match sites"
```

---

## Task 5: `jcl_graph.py` consumer

**Files:**
- Modify: `jackal/jackal/jcl_graph.py`

**Interfaces:**
- Consumes: `jackal.value_parts.resolve` (Task 1), `DirectDSN.name: Value` (Task 3).

`test_jcl_graph.py` builds every fixture from raw JCL text parsed through the real bridge (no direct `DirectDSN(...)` construction), so it needs no test changes — it exercises the new code path automatically once `jcl_graph.py` is updated.

- [ ] **Step 1: Run the existing test to verify it fails**

```bash
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest jackal/tests/unit/test_jcl_graph.py -v
```
Expected: FAIL on `dd.dsn.name.upper()` (`jackal/jackal/jcl_graph.py:77`) — `.upper()` on a `Value` tuple raises `AttributeError`.

- [ ] **Step 2: Update `jcl_graph.py`**

Add to the imports (after `from jackal.jcl.parser import parse_jcl`):
```python
from jackal.value_parts import resolve
```

Change line 77 from:
```python
            dataset_id = _add_node(NodeKind.DATASET, dd.dsn.name.upper())
```
to:
```python
            dataset_id = _add_node(NodeKind.DATASET, resolve(dd.dsn.name).upper())
```

- [ ] **Step 3: Run the test to verify it passes**

```bash
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest jackal/tests/unit/test_jcl_graph.py -v
```
Expected: 12 passed.

- [ ] **Step 4: Commit**

```bash
git add jackal/jackal/jcl_graph.py
git commit -m "feat: resolve DirectDSN.name Value to str when building DATASET graph node ids"
```

---

## Task 6: `cobol_step.py` consumer

**Files:**
- Modify: `jackal/jackal/cobol_step.py`
- Modify: `jackal/tests/integration/test_cobol_step.py`

**Interfaces:**
- Consumes: `jackal.value_parts.{literal, resolve}` (Task 1), `Step.parm: Value` (Task 3).

- [ ] **Step 1: Update the failing test first**

Edit `jackal/tests/integration/test_cobol_step.py` — add the import (after `from jackal.dsn import DirectDSN`):
```python
from jackal.value_parts import literal
```

Change the `_dd` helper (lines 25-28) from:
```python
def _dd(ddname, dsn: str, status, normal=DispNormal.KEEP):
    return DD(
        ddname=ddname, dsn=DirectDSN(dsn), disp=Disp(status, normal, DispNormal.DELETE)
    )
```
to:
```python
def _dd(ddname, dsn: str, status, normal=DispNormal.KEEP):
    return DD(
        ddname=ddname, dsn=DirectDSN(literal(dsn)), disp=Disp(status, normal, DispNormal.DELETE)
    )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run --no-sync python -m pytest jackal/tests/integration/test_cobol_step.py -v
```
Expected: FAIL — `DirectDSN(literal(dsn))` doesn't match the current `str`-typed constructor expectation until `dsn.py` from Task 3 is in place; since Task 3 already landed by this point in the plan, the actual failure here is upstream — this file has no direct PARM-typed assertion, so it should currently PASS unchanged once Tasks 1-5 are in. Run it first to confirm this (it is a verification step, not expected to fail) — if it already passes, skip Step 3 and proceed to updating `cobol_step.py` directly, then re-run to confirm it still passes.

- [ ] **Step 3: Update `cobol_step.py`**

Add to the imports (after `from jackal.model import Step`):
```python
from jackal.value_parts import resolve
```

Change line 71 from:
```python
    if step.parm:
```
to:
```python
    if step.parm:
        parm_text = resolve(step.parm)
```

(keep the existing `if step.parm:` line — a non-empty `Value` tuple is still truthy — and add the `parm_text = resolve(step.parm)` line directly inside the `if` block, before the existing `_, linked = compile_cobol(...)` line)

Change line 79 (inside the `if step.parm:` block) from:
```python
        parm_vm.region_set(parm_addr, bytearray(build_parm_region(step.parm)))
```
to:
```python
        parm_vm.region_set(parm_addr, bytearray(build_parm_region(parm_text)))
```

- [ ] **Step 4: Run the test to verify it still passes**

```bash
uv run --no-sync python -m pytest jackal/tests/integration/test_cobol_step.py -v
```
Expected: pass.

- [ ] **Step 5: Run the PARM-passing e2e test too (it exercises this exact code path with a real PARM value)**

```bash
uv run --no-sync python -m pytest jackal/tests/integration/test_jcl_execute_e2e.py -k parm -v
```
Expected: pass (this test constructs its `Step` via real `parse_jcl` on JCL text containing `PARM='HELLO     '`, so it exercises the full Task 3 + Task 6 chain).

- [ ] **Step 6: Commit**

```bash
git add jackal/jackal/cobol_step.py jackal/tests/integration/test_cobol_step.py
git commit -m "feat: resolve Step.parm Value to str before building the COBOL PARM region"
```

---

## Task 7: `runner.py` consumer, `test_runner.py`, `test_backward_refs.py`, `test_idcams_executor.py`

**Files:**
- Modify: `jackal/jackal/runner.py`
- Modify: `jackal/tests/unit/test_runner.py`
- Modify: `jackal/tests/integration/test_backward_refs.py`
- Modify: `jackal/tests/unit/test_idcams_executor.py`

**Interfaces:**
- Consumes: `jackal.value_parts.literal` (Task 1), `DirectDSN.name: Value` (Task 3).

`test_idcams_executor.py` constructs `DirectDSN(...)` directly for its `DD` fixtures — `IdcamsCommand` types (`Delete.dsn: str`, `DefineCluster.name: str`) are a separate, unrelated str-typed model (IDCAMS's own command objects, parsed from SYSIN text by a different grammar) and are explicitly out of scope for this migration — only the `DD`/`DirectDSN` construction sites in this file need updating.

- [ ] **Step 1: Update the failing tests first**

Edit `jackal/tests/unit/test_runner.py` — add the import (after `from jackal.dsn import DirectDSN`):
```python
from jackal.value_parts import literal
```

Change line 24 from:
```python
                        DirectDSN("J.X"),
```
to:
```python
                        DirectDSN(literal("J.X")),
```

Change lines 63, 69, 96 (all three `DirectDSN("")`) to `DirectDSN(())`.

Change line 186 from:
```python
    resolved_dds = {"STEP1": {"WRK": DirectDSN("MY.FILE")}}
```
to:
```python
    resolved_dds = {"STEP1": {"WRK": DirectDSN(literal("MY.FILE"))}}
```

Change line 200 from:
```python
    assert result.dds[0].dsn == DirectDSN("MY.FILE")
```
to:
```python
    assert result.dds[0].dsn == DirectDSN(literal("MY.FILE"))
```

Change line 247 from:
```python
            DirectDSN("MY.FILE"),
```
to:
```python
            DirectDSN(literal("MY.FILE")),
```

Change lines 253-254 from:
```python
    assert registry["STEP1"]["WRK"] == DirectDSN("TEMP")  # alias[2:]
    assert registry["STEP1"]["OUT"] == DirectDSN("MY.FILE")
```
to:
```python
    assert registry["STEP1"]["WRK"] == DirectDSN(literal("TEMP"))  # alias[2:]
    assert registry["STEP1"]["OUT"] == DirectDSN(literal("MY.FILE"))
```

Change line 269 from:
```python
    resolved_dds = {"STEP1": {"WRK": DirectDSN("MY.FILE")}}
```
to:
```python
    resolved_dds = {"STEP1": {"WRK": DirectDSN(literal("MY.FILE"))}}
```

Edit `jackal/tests/integration/test_backward_refs.py` — add the import (after `from jackal.dsn import DirectDSN, TempRef`):
```python
from jackal.value_parts import literal
```

Change line 35 from:
```python
                        DirectDSN("MY.FILE"),
```
to:
```python
                        DirectDSN(literal("MY.FILE")),
```

Change line 86 from:
```python
                        DirectDSN("MY.FILE"),
```
to:
```python
                        DirectDSN(literal("MY.FILE")),
```

Edit `jackal/tests/unit/test_idcams_executor.py` — add the import (after `from jackal.dsn import DirectDSN`):
```python
from jackal.value_parts import literal
```

Change line 28 from:
```python
            DirectDSN("IN.PS"),
```
to:
```python
            DirectDSN(literal("IN.PS")),
```

Change line 33 from:
```python
            DirectDSN("OUT.KSDS"),
```
to:
```python
            DirectDSN(literal("OUT.KSDS")),
```

- [ ] **Step 2: Run all three test files to verify they fail**

```bash
uv run --no-sync python -m pytest jackal/tests/unit/test_runner.py jackal/tests/integration/test_backward_refs.py jackal/tests/unit/test_idcams_executor.py -v
```
Expected: FAIL — `runner.py`'s `_record_dds` builds `DirectDSN(a[2:])` (line 119, `a` is a plain `str` alias) which now needs to be a `Value`.

- [ ] **Step 3: Update `runner.py`**

Add to the imports (after `from jackal.results import JobResult, StepDisposition, StepResult`):
```python
from jackal.value_parts import literal
```

Change line 119 (in `_record_dds`) from:
```python
                    entry[dd.ddname] = DirectDSN(a[2:])  # strip leading &&
```
to:
```python
                    entry[dd.ddname] = DirectDSN(literal(a[2:]))  # strip leading &&
```

- [ ] **Step 4: Run all three test files to verify they pass**

```bash
uv run --no-sync python -m pytest jackal/tests/unit/test_runner.py jackal/tests/integration/test_backward_refs.py jackal/tests/unit/test_idcams_executor.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add jackal/jackal/runner.py jackal/tests/unit/test_runner.py \
        jackal/tests/integration/test_backward_refs.py jackal/tests/unit/test_idcams_executor.py
git commit -m "feat: construct a Literal Value when building DirectDSN from a stripped TempRef alias"
```

---

## Task 8: Full suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full jackal test suite**

```bash
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
PROLEAP_BRIDGE_JAR=$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
uv run --no-sync python -m pytest jackal -q
```
Expected: all pass, 0 failures. (This includes `jackal/tests/integration/test_carddemo_acctfile_e2e.py` and any other corpus-driven e2e tests not touched directly by this plan but which parse real CardDemo JCL through the now-changed bridge/model — they must still pass unmodified, since no real CardDemo JCL/PARM in the corpus is expected to behave differently under `resolve()` for already-literal values.)

- [ ] **Step 2: Run the CardDemo knowledge-graph build end-to-end as a final real-corpus check**

```bash
PROLEAP_BRIDGE_JAR=$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
uv run --no-sync python knowledge_graph/build_carddemo_graph.py
```
Expected: same node/edge counts as before this plan (443 nodes, 788 edges, 1 pre-existing `COCRDSEC` failure) — this plan changes representation, not behavior, so the merged graph must be identical.

- [ ] **Step 3: If anything differs from the expected counts, stop and investigate before proceeding — do not adjust the expected numbers to match unexpected output.**

## Self-Review

**Spec coverage:** every file the "no regex, structure from the grammar" spec section names (`DirectDSN.name`, `Step.parm`, `JclSerializer.java`, `bridge_parser.py`) has a task. `catalog.py`, `jcl_graph.py`, `cobol_step.py`, `runner.py` were discovered by grepping every `DirectDSN(` construction site and every `.parm`/`.dsn.name` consumption site directly — not assumed from memory.

**Placeholder scan:** no TBD/TODO. Task 3 Step 5 and Task 6 Step 2 each flag one specific, bounded thing to verify empirically at that exact point (quote-stripping behavior; whether the file already passes) rather than assuming — these are verification checkpoints with a stated expected outcome and a stated fallback action, not open-ended hand-waving.

**Type consistency:** `Value`/`Literal`/`Symbol`/`resolve`/`literal` names and signatures are identical from their Task 1 definition through every later task's usage. `DirectDSN.name: Value` and `Step.parm: Value` are the only two field-type changes in the whole plan; every other file only ever calls `resolve()` on them, never reaches into their internals directly.
