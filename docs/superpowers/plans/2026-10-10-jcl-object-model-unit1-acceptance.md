# JCL Object Model, Unit 1: Acceptance Suite and CardDemo Snapshot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Commit an acceptance suite that pins the exact `Job` and `ExpandedJob`/`JclError` the new JCL object model must produce for every construct family, as strict xfail, plus a frozen snapshot of what today's code reads from every CardDemo job, with a comparison test that is green today.

**Architecture:** Tests live in `jackal/tests/acceptance/`. Each family has its JCL (and PROC) fixtures under `fixtures/<family>/` and one test module. Tests import the new model only inside test bodies through a builder module, so an `ImportError` or `TypeError` today is caught by the strict xfail marker, and each test turns green, and then must lose its marker, when unit 3 or 4 lands. The CardDemo snapshot is a JSON file written once by a small CLI and read back through Pydantic models.

**Tech Stack:** Python 3.13, pytest 9, Pydantic 2 (already in the workspace through cobble and squall), the jcl-bridge JAR via `. ./bridge-env.sh`.

**Spec:** `docs/superpowers/specs/2026-10-10-jackal-jcl-object-model-build-design.md` (unit 1), building `docs/superpowers/specs/2026-10-10-jackal-job-level-domain-model-design.md` (the blueprint) §4, §5, §12.1.

**Issue:** `red-dragon-forge-2cy.8`. Markers cite `red-dragon-forge-2cy.9` (unit 3, parsed model) and `red-dragon-forge-2cy.10` (unit 4, expansion); bridge-dependent tests also cite `2cy.2` (DCB), `2cy.3` (concatenation), `2cy.7` (IF structure).

## Global Constraints

- Every acceptance test is `@pytest.mark.xfail(reason=<issue ids>, strict=True)` and decorated `@covers(NotLanguageFeature.INFRASTRUCTURE)`, the convention every jackal test follows.
- Fixture JCL uses made-up names only (guidelines/data-security.md): job `ACCEPT`, steps `S1…`, procstep `P1…`, datasets `T.*`.
- Tests assert whole objects with `==`. No `isinstance`, containment, length or truthiness assertions.
- New-model imports happen inside test bodies, through `tests.acceptance.build`, never at module top.
- Run jackal tests from `jackal/` after `. ./bridge-env.sh` at the repo root: `cd jackal && uv run --no-sync python -m pytest <path> -q`.
- No test counts in any living doc.

## The model contract these tests pin

Units 3 and 4 must provide exactly these names. Where this differs from the blueprint, the difference is listed under "Deviations"; units 3 and 4 follow this contract.

| Module | Names and constructor fields, in order |
|---|---|
| `jackal.value_parts` | `SymbolName(text)`, `Literal(text)`, `Symbol(name: SymbolName)`, `Value = tuple[Literal \| Symbol, ...]`, `literal(text) -> Value` |
| `jackal.dsn` | `DirectDSN(name: Value)`, `TempRef(name: str)`, `BackwardRef(step: R, ddname: str)`, `InStreamDSN()`, `DummyDSN()`, `NoDSN()` |
| `jackal.model` | `StepName(text)`, `Unnamed()`, `OwnScope()`, `CalledProcScope(call: StepName)`, `StepRef(scope, step: StepName)` |
| | `CondOp` (`GT GE EQ NE LT LE`), `RcComparison(code, op)`, `AllPriorSteps()`, `BypassTest(comparison, target)`, `AbendMode` (`NORMAL EVEN ONLY`), `StepCondition(bypass_tests, abend_mode)` |
| | `DispStatus` (`NEW OLD SHR MOD`), `DispNormal` (`PASS CATLG UNCATLG KEEP DELETE`), `DispAbnormal` (`CATLG UNCATLG KEEP DELETE`), `Disp(status, normal, abnormal)` |
| | `ConcatMember(dsn, disp, in_stream=())`, `DD(ddname, dsn, disp, in_stream=(), sysout=False, concatenated=())` |
| | `SystemAbend(code)`, `UserAbend(code)` |
| | `Always()`, `RcTest(target, op, code)`, `AbendTest(target)`, `AbendCodeTest(target, code)`, `RunTest(step)`, `Negated(guard)`, `AllOf(guards)`, `AnyOf(guards)` |
| | `ProgramStep(label, pgm, dds=(), cond=StepCondition((), NORMAL), parm=(), guard=Always())` |
| | `NotOverridden()`, `ProcStepOverrides(cond=NotOverridden(), parm=NotOverridden(), dds=())` |
| | `ProcCall(label, proc, symbol_overrides=(), cond_for_every_step=NotOverridden(), parm_for_first_step=NotOverridden(), dds_for_first_step=(), per_step=())` |
| | `IfBlock(label, condition, then, otherwise=())`, `Job(name, steps, end_job_tests=())`, `ProcDef(name, defaults, steps)` |
| `jackal.expansion` | `QualifiedStep(calls, step)`, `UnresolvedProcCall(call)`, `ExpandedJob(name, steps, end_job_tests=())` |
| | `ErrorSite(calls, step)`, `DanglingReference(site, ref)`, `DanglingDdReference(site, ref, ddname)`, `ForwardReference(site, ref)`, `ReferenceToProcCall(site, ref)`, `OverrideNamesNoStep(call, step)`, `CircularProc(procs)` |
| | `DirectoryProcLibrary(dirs)`, `expand_procs(job, library) -> ExpandedJob \| JclError` |
| `jackal.jcl.parser` | `parse_jcl(text) -> Job` (exists today; returns the new `Job` from unit 3) |

Normalisation rules the expected values rely on:

- **PARM and DSN text** after expansion is one `Literal` holding the resolved text, or `()` when empty. A period directly after a symbol is the symbol's delimiter and is dropped: `&HLQ..TRANS` with `HLQ=T` is `literal("T.TRANS")`.
- **Before expansion,** values keep their parts: `&HLQ..TRANS` is `(Symbol(SymbolName("HLQ")), Literal(".TRANS"))`. The bridge emits `..TRANS` today; unit 2 or 3 drops the delimiter period at parse time.
- **A parsed `PARM`** is the text without its enclosing quotes, as one `Literal`.
- **Omitted DISP** follows blueprint §4.4: no `DISP` is `(NEW, DELETE, DELETE)`; `OLD`, `SHR` and `MOD` alone are `(status, KEEP, KEEP)`; `(,PASS)` is `(NEW, PASS, DELETE)`; `(OLD,PASS)` is `(OLD, PASS, KEEP)`; an omitted abnormal value repeats the normal one unless the normal one is `PASS`.
- **`DD *`, `DD DATA`, `DD DUMMY`, `SYSOUT=`** carry `Disp(NEW, DELETE, DELETE)`.
- **`DSN=&NAME`,** a lone symbol no PROC defines, is `DirectDSN((Symbol(NAME),))` when parsed and `TempRef("NAME")` after expansion.
- **`IF` operators `NG` and `NL`** normalise to `LE` and `GE`.

Deviations from the blueprint (record them in unit 3's or 4's commit message):

- `TempRef(name)` holds the bare name (`"T"`), never the `&&` text.
- `JclError` variants hold an `ErrorSite(calls: tuple[ProcCall, ...], step: ProgramStep[StepRef])` instead of a `QualifiedStep`: a step whose reference failed to resolve has no resolved form. `OverrideNamesNoStep` holds the offending `ProcCall`.
- The parsed model has `IfBlock(label, condition: Guard[StepRef], then, otherwise)` in `JobStep`; expansion turns it into each step's `guard`. Bare `RC`, `ABEND` and `ABENDCC` use `AllPriorSteps()` as their target.

## Review Focus

- **A period after a symbol** (`&HLQ..TRANS`): JCL drops the first period. Today's parts keep it, so the resolved name would be `PROD..TRANS`. Pinned by `test_symbols_expand` (Task 4).
- **`DD DATA` content:** today the bridge emits no card images for `DD DATA`, so a program reading it gets nothing. Pinned by `test_dsn_kinds_parse` (Task 3).
- **`DSN=NULLFILE`** reaches the model as an ordinary dataset name today, so allocation would look for a dataset called `NULLFILE`. Pinned by `test_dsn_kinds_parse` (Task 3).
- **A lone `&T`** today becomes `TempRef("&T")`, which `catalog._allocate_temp` slices to an empty name. Pinned by `test_lone_symbol_dsn_expands_to_temp` (Task 3).
- **A COND inside a PROC naming its own step** never matches today, because inner step names become `"S1.P1"` and inner references are not rewritten. Pinned by `test_reference_inside_proc_expands` (Task 5).

---

### Task 1: Harness and the steps/labels family

**Files:**
- Create: `jackal/tests/acceptance/__init__.py` (empty)
- Create: `jackal/tests/acceptance/conftest.py`
- Create: `jackal/tests/acceptance/markers.py`
- Create: `jackal/tests/acceptance/build.py`
- Create: `jackal/tests/acceptance/fixtures/steps/labels.jcl`
- Create: `jackal/tests/acceptance/fixtures/steps/MYP.prc`
- Test: `jackal/tests/acceptance/test_steps.py`

**Interfaces:**
- Consumes: `jackal.jcl.parser.parse_jcl` (exists); the contract table above.
- Produces: fixtures `parse_fixture(rel: str) -> Job` and `expand_fixture(rel: str) -> ExpandedJob | JclError`; markers `PARSED`, `EXPANDED`, `bridge_then_parsed(issue: str)`; builder functions in `tests.acceptance.build` used by every later task.

- [ ] **Step 1: Write the harness**

`jackal/tests/acceptance/markers.py`:

```python
"""Strict xfail markers naming the unit that makes each acceptance test pass."""

import pytest

PARSED = pytest.mark.xfail(
    reason="red-dragon-forge-2cy.9: blueprint parsed model not built yet",
    strict=True,
)
EXPANDED = pytest.mark.xfail(
    reason="red-dragon-forge-2cy.10: expand_procs -> ExpandedJob not built yet",
    strict=True,
)


def bridge_then_parsed(issue: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(
        reason=f"{issue} (bridge) and red-dragon-forge-2cy.9 (parsed model)",
        strict=True,
    )


def bridge_then_expanded(issue: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(
        reason=f"{issue} (bridge) and red-dragon-forge-2cy.10 (expansion)",
        strict=True,
    )
```

`jackal/tests/acceptance/conftest.py`:

```python
"""Fixtures that turn an acceptance fixture path into a parsed or expanded job."""

from collections.abc import Callable
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def parse_fixture(jcl_bridge_jar: str) -> Callable[[str], object]:
    def _parse(rel: str) -> object:
        from jackal.jcl.parser import parse_jcl

        return parse_jcl((FIXTURES / rel).read_text())

    return _parse


@pytest.fixture
def expand_fixture(
    parse_fixture: Callable[[str], object],
) -> Callable[[str], object]:
    def _expand(rel: str) -> object:
        from jackal.expansion import DirectoryProcLibrary, expand_procs

        path = FIXTURES / rel
        return expand_procs(parse_fixture(rel), DirectoryProcLibrary((path.parent,)))

    return _expand
```

`jackal/tests/acceptance/build.py` (imported only inside test bodies):

```python
"""Short constructors for expected model values in the acceptance suite."""

from jackal.dsn import (
    BackwardRef,
    DirectDSN,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    TempRef,
)
from jackal.expansion import QualifiedStep
from jackal.model import (
    DD,
    AbendMode,
    AllPriorSteps,
    BypassTest,
    CalledProcScope,
    ConcatMember,
    CondOp,
    Disp,
    DispAbnormal,
    DispNormal,
    DispStatus,
    OwnScope,
    ProgramStep,
    RcComparison,
    StepCondition,
    StepName,
    StepRef,
    Unnamed,
)
from jackal.value_parts import Symbol, SymbolName, literal

NO_COND = StepCondition((), AbendMode.NORMAL)


def name(text: str) -> StepName:
    return StepName(text)


def ref(step: str) -> StepRef:
    return StepRef(OwnScope(), StepName(step))


def ref_in(call: str, step: str) -> StepRef:
    return StepRef(CalledProcScope(StepName(call)), StepName(step))


def disp(status: str, normal: str, abnormal: str) -> Disp:
    return Disp(DispStatus[status], DispNormal[normal], DispAbnormal[abnormal])


SHR = disp("SHR", "KEEP", "KEEP")
OLD = disp("OLD", "KEEP", "KEEP")
DEFAULT_DISP = disp("NEW", "DELETE", "DELETE")


def dataset(ddname: str, dsn: str, d: Disp = SHR) -> DD:
    return DD(ddname, DirectDSN(literal(dsn)), d)


def temp(ddname: str, temp_name: str, d: Disp) -> DD:
    return DD(ddname, TempRef(temp_name), d)


def in_stream(ddname: str, lines: tuple[str, ...]) -> DD:
    return DD(ddname, InStreamDSN(), DEFAULT_DISP, in_stream=lines)


def dummy(ddname: str) -> DD:
    return DD(ddname, DummyDSN(), DEFAULT_DISP)


def sysout(ddname: str) -> DD:
    return DD(ddname, NoDSN(), DEFAULT_DISP, sysout=True)


def backref(ddname: str, step: object, target_dd: str, d: Disp = SHR) -> DD:
    return DD(ddname, BackwardRef(step, target_dd), d)


def concat(ddname: str, first: str, rest: tuple[ConcatMember, ...]) -> DD:
    return DD(ddname, DirectDSN(literal(first)), SHR, concatenated=rest)


def member(dsn: str) -> ConcatMember:
    return ConcatMember(DirectDSN(literal(dsn)), SHR)


def on_step(code: int, op: str, target: object) -> BypassTest:
    return BypassTest(RcComparison(code, CondOp[op]), target)


def all_prior(code: int, op: str) -> BypassTest:
    return BypassTest(RcComparison(code, CondOp[op]), AllPriorSteps())


def cond(*tests: BypassTest, mode: str = "NORMAL") -> StepCondition:
    return StepCondition(tests, AbendMode[mode])


def pgm(
    label: str,
    program: str,
    dds: tuple[DD, ...] = (),
    condition: StepCondition = NO_COND,
    parm: str = "",
) -> ProgramStep:
    return ProgramStep(
        StepName(label) if label else Unnamed(),
        program,
        dds,
        condition,
        literal(parm) if parm else (),
    )


def symbol(sym: str) -> Symbol:
    return Symbol(SymbolName(sym))


def qualified(calls: tuple[object, ...], step: object) -> QualifiedStep:
    return QualifiedStep(calls, step)

```

- [ ] **Step 2: Write the steps/labels fixtures**

`jackal/tests/acceptance/fixtures/steps/labels.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC PGM=PGMA,PARM='A=(,255)'
//S2       EXEC MYP
//S3       EXEC PROC=MYP
//         EXEC PGM=PGMB,PARM='X (Y'
//S5       EXEC PGM=PGMC,PARM=PLAIN
```

`jackal/tests/acceptance/fixtures/steps/MYP.prc`:

```
//MYP      PROC
//P1       EXEC PGM=PGMP
```

- [ ] **Step 3: Write the failing tests**

`jackal/tests/acceptance/test_steps.py`:

```python
"""Acceptance: EXEC statements, labels and PARM text."""

from tests.acceptance.markers import EXPANDED, PARSED
from tests.covers import NotLanguageFeature, covers


@PARSED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_steps_parse(parse_fixture):
    from jackal.model import Job, ProcCall
    from tests.acceptance import build as b

    assert parse_fixture("steps/labels.jcl") == Job(
        "ACCEPT",
        (
            b.pgm("S1", "PGMA", parm="A=(,255)"),
            ProcCall(b.name("S2"), "MYP"),
            ProcCall(b.name("S3"), "MYP"),
            b.pgm("", "PGMB", parm="X (Y"),
            b.pgm("S5", "PGMC", parm="PLAIN"),
        ),
    )


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_steps_expand(expand_fixture):
    from jackal.expansion import ExpandedJob
    from jackal.model import ProcCall
    from tests.acceptance import build as b

    s2 = ProcCall(b.name("S2"), "MYP")
    s3 = ProcCall(b.name("S3"), "MYP")
    assert expand_fixture("steps/labels.jcl") == ExpandedJob(
        "ACCEPT",
        (
            b.qualified((), b.pgm("S1", "PGMA", parm="A=(,255)")),
            b.qualified((s2,), b.pgm("P1", "PGMP")),
            b.qualified((s3,), b.pgm("P1", "PGMP")),
            b.qualified((), b.pgm("", "PGMB", parm="X (Y")),
            b.qualified((), b.pgm("S5", "PGMC", parm="PLAIN")),
        ),
    )
```

- [ ] **Step 4: Run and confirm both are xfailed**

Run: `cd jackal && uv run --no-sync python -m pytest tests/acceptance/test_steps.py -q -rx`
Expected: `2 xfailed`. Read the `-rx` reasons: each must be the `ImportError` for `jackal.model.ProcCall` or `jackal.expansion`, not a fixture or syntax error in the test. A test that fails for any other reason is a broken test; fix it before going on.

- [ ] **Step 5: Commit**

```bash
git add jackal/tests/acceptance
git commit -m "test(jackal): acceptance harness and EXEC/label fixtures for the JCL object model"
```

---

### Task 2: COND and DISP families

**Files:**
- Create: `jackal/tests/acceptance/fixtures/cond/cond.jcl`
- Create: `jackal/tests/acceptance/fixtures/disp/disp.jcl`
- Test: `jackal/tests/acceptance/test_cond.py`, `jackal/tests/acceptance/test_disp.py`

**Interfaces:**
- Consumes: Task 1's fixtures, markers and builders.
- Produces: nothing new.

- [ ] **Step 1: Write the fixtures**

`fixtures/cond/cond.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A,COND=((8,LE),(12,EQ))
//S1       EXEC PGM=PGMA
//S2       EXEC PGM=PGMB,COND=(4,LT)
//S3       EXEC PGM=PGMC,COND=((4,LT),(8,EQ,S1))
//S4       EXEC PGM=PGMD,COND=(4,LT,S1.P1)
//S5       EXEC PGM=PGME,COND=EVEN
//S6       EXEC PGM=PGMF,COND=ONLY
//S7       EXEC PGM=PGMG,COND=((4,LT),EVEN,(8,EQ,S1))
//S8       EXEC PGM=PGMH,COND=((4,LT),ONLY)
```

`fixtures/disp/disp.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC PGM=PGMA
//A        DD DSN=T.A,DISP=NEW
//B        DD DSN=T.B,DISP=OLD
//C        DD DSN=T.C,DISP=SHR
//D        DD DSN=T.D,DISP=MOD
//E        DD DSN=T.E,DISP=(NEW,CATLG,DELETE)
//F        DD DSN=T.F,DISP=(OLD,UNCATLG)
//G        DD DSN=T.G,DISP=(,PASS)
//H        DD DSN=T.H,DISP=(OLD,PASS)
//I        DD DSN=T.I,DISP=(OLD,DELETE,KEEP)
//J        DD DSN=T.J
//K        DD DSN=T.K,DISP=(NEW,KEEP,UNCATLG)
```

- [ ] **Step 2: Write the failing tests**

`test_cond.py`:

```python
"""Acceptance: EXEC and JOB COND."""

from tests.acceptance.markers import PARSED
from tests.covers import NotLanguageFeature, covers


@PARSED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cond_parses(parse_fixture):
    from jackal.model import CondOp, Job, RcComparison
    from tests.acceptance import build as b

    s1 = b.ref("S1")
    assert parse_fixture("cond/cond.jcl") == Job(
        "ACCEPT",
        (
            b.pgm("S1", "PGMA"),
            b.pgm("S2", "PGMB", condition=b.cond(b.all_prior(4, "LT"))),
            b.pgm(
                "S3",
                "PGMC",
                condition=b.cond(b.all_prior(4, "LT"), b.on_step(8, "EQ", s1)),
            ),
            b.pgm(
                "S4", "PGMD", condition=b.cond(b.on_step(4, "LT", b.ref_in("S1", "P1")))
            ),
            b.pgm("S5", "PGME", condition=b.cond(mode="EVEN")),
            b.pgm("S6", "PGMF", condition=b.cond(mode="ONLY")),
            b.pgm(
                "S7",
                "PGMG",
                condition=b.cond(
                    b.all_prior(4, "LT"), b.on_step(8, "EQ", s1), mode="EVEN"
                ),
            ),
            b.pgm("S8", "PGMH", condition=b.cond(b.all_prior(4, "LT"), mode="ONLY")),
        ),
        end_job_tests=(RcComparison(8, CondOp.LE), RcComparison(12, CondOp.EQ)),
    )
```

`test_disp.py`:

```python
"""Acceptance: DISP values and their defaults."""

from tests.acceptance.markers import PARSED
from tests.covers import NotLanguageFeature, covers


@PARSED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_disp_parses(parse_fixture):
    from jackal.model import Job
    from tests.acceptance import build as b

    d = b.disp
    assert parse_fixture("disp/disp.jcl") == Job(
        "ACCEPT",
        (
            b.pgm(
                "S1",
                "PGMA",
                (
                    b.dataset("A", "T.A", d("NEW", "DELETE", "DELETE")),
                    b.dataset("B", "T.B", d("OLD", "KEEP", "KEEP")),
                    b.dataset("C", "T.C", d("SHR", "KEEP", "KEEP")),
                    b.dataset("D", "T.D", d("MOD", "KEEP", "KEEP")),
                    b.dataset("E", "T.E", d("NEW", "CATLG", "DELETE")),
                    b.dataset("F", "T.F", d("OLD", "UNCATLG", "UNCATLG")),
                    b.dataset("G", "T.G", d("NEW", "PASS", "DELETE")),
                    b.dataset("H", "T.H", d("OLD", "PASS", "KEEP")),
                    b.dataset("I", "T.I", d("OLD", "DELETE", "KEEP")),
                    b.dataset("J", "T.J", d("NEW", "DELETE", "DELETE")),
                    b.dataset("K", "T.K", d("NEW", "KEEP", "UNCATLG")),
                ),
            ),
        ),
    )
```

- [ ] **Step 3: Run and confirm xfailed for the right reason**

Run: `cd jackal && uv run --no-sync python -m pytest tests/acceptance/test_cond.py tests/acceptance/test_disp.py -q -rx`
Expected: `2 xfailed`. Each reason is an `ImportError` for `jackal.model.RcComparison`, `Job` with new fields, or `jackal.expansion` (pulled in by `build.py`). Today's bridge rejects the `COND=EVEN` step and the `UNCATLG` value; that does not show, because the import fails first. Unit 3 fixes both.

- [ ] **Step 4: Commit**

```bash
git add jackal/tests/acceptance
git commit -m "test(jackal): COND and DISP acceptance fixtures for the JCL object model"
```

---

### Task 3: DSN kinds, concatenation and DCB families

**Files:**
- Create: `fixtures/dsn/kinds.jcl`, `fixtures/dsn/temps.jcl`, `fixtures/concat/concat.jcl`, `fixtures/dcb/dcb.jcl`
- Test: `test_dsn.py`, `test_concat.py`, `test_dcb.py`

**Interfaces:**
- Consumes: Task 1's harness.
- Produces: nothing new.

- [ ] **Step 1: Write the fixtures**

`fixtures/dsn/kinds.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC PGM=PGMA
//IN       DD DSN=T.IN,DISP=SHR
//OUT      DD DSN=&&WORK,DISP=(NEW,PASS)
//SYSIN    DD *
 CARD ONE
 CARD TWO
/*
//DATA1    DD DATA
 DATA LINE
/*
//NULL1    DD DUMMY
//NULL2    DD DSN=NULLFILE
//REPORT   DD SYSOUT=*
//S2       EXEC PGM=PGMB
//COPY     DD DSN=*.S1.IN,DISP=SHR
//PCOPY    DD DSN=*.S1.P1.IN,DISP=SHR
```

`fixtures/dsn/temps.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC PGM=PGMA
//OUT      DD DSN=&WORK,DISP=(NEW,PASS)
//S2       EXEC PGM=PGMB
//IN       DD DSN=&&WORK,DISP=(OLD,DELETE)
//COPY     DD DSN=*.S1.OUT,DISP=SHR
```

`fixtures/concat/concat.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC PGM=PGMA
//TWO      DD DSN=T.A,DISP=SHR
//         DD DSN=T.B,DISP=SHR
//THREE    DD DSN=T.C,DISP=SHR
//         DD DSN=T.D,DISP=SHR
//         DD DSN=T.E,DISP=SHR
//MIXED    DD DSN=T.F,DISP=SHR
//         DD *
 CARD
/*
//         DD DUMMY
//LAST     DD DSN=T.G,DISP=SHR
```

`fixtures/dcb/dcb.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC PGM=PGMA
//A        DD DSN=T.A,DISP=(NEW,CATLG),DCB=T.MODEL
//B        DD DSN=T.B,DISP=(NEW,CATLG),DCB=(T.MODEL,RECFM=FB,LRECL=80)
//C        DD DSN=T.C,DISP=(NEW,CATLG),DCB=*.S1.A
//D        DD DSN=T.D,DISP=(NEW,CATLG),DCB=(RECFM=FB,LRECL=80)
//S2       EXEC PGM=PGMB
//E        DD DSN=T.A,DISP=SHR
```

- [ ] **Step 2: Write the failing tests**

`test_dsn.py`:

```python
"""Acceptance: every DSN kind, and temps and referbacks after expansion."""

from tests.acceptance.markers import EXPANDED, PARSED
from tests.covers import NotLanguageFeature, covers


@PARSED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_kinds_parse(parse_fixture):
    from jackal.model import Job
    from tests.acceptance import build as b

    assert parse_fixture("dsn/kinds.jcl") == Job(
        "ACCEPT",
        (
            b.pgm(
                "S1",
                "PGMA",
                (
                    b.dataset("IN", "T.IN"),
                    b.temp("OUT", "WORK", b.disp("NEW", "PASS", "DELETE")),
                    b.in_stream("SYSIN", (" CARD ONE", " CARD TWO")),
                    b.in_stream("DATA1", (" DATA LINE",)),
                    b.dummy("NULL1"),
                    b.dummy("NULL2"),
                    b.sysout("REPORT"),
                ),
            ),
            b.pgm(
                "S2",
                "PGMB",
                (
                    b.backref("COPY", b.ref("S1"), "IN"),
                    b.backref("PCOPY", b.ref_in("S1", "P1"), "IN"),
                ),
            ),
        ),
    )


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_lone_symbol_dsn_expands_to_temp(expand_fixture):
    from jackal.expansion import ExpandedJob
    from tests.acceptance import build as b

    s1 = b.qualified(
        (),
        b.pgm(
            "S1", "PGMA", (b.temp("OUT", "WORK", b.disp("NEW", "PASS", "DELETE")),)
        ),
    )
    assert expand_fixture("dsn/temps.jcl") == ExpandedJob(
        "ACCEPT",
        (
            s1,
            b.qualified(
                (),
                b.pgm(
                    "S2",
                    "PGMB",
                    (
                        b.temp("IN", "WORK", b.disp("OLD", "DELETE", "DELETE")),
                        b.backref("COPY", s1, "OUT"),
                    ),
                ),
            ),
        ),
    )
```

`test_concat.py`:

```python
"""Acceptance: DD concatenation."""

from tests.acceptance.markers import bridge_then_parsed
from tests.covers import NotLanguageFeature, covers


@bridge_then_parsed("red-dragon-forge-2cy.3")
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_concatenation_parses(parse_fixture):
    from jackal.dsn import DummyDSN, InStreamDSN
    from jackal.model import ConcatMember, Job
    from tests.acceptance import build as b

    assert parse_fixture("concat/concat.jcl") == Job(
        "ACCEPT",
        (
            b.pgm(
                "S1",
                "PGMA",
                (
                    b.concat("TWO", "T.A", (b.member("T.B"),)),
                    b.concat("THREE", "T.C", (b.member("T.D"), b.member("T.E"))),
                    b.concat(
                        "MIXED",
                        "T.F",
                        (
                            ConcatMember(InStreamDSN(), b.DEFAULT_DISP, (" CARD",)),
                            ConcatMember(DummyDSN(), b.DEFAULT_DISP),
                        ),
                    ),
                    b.dataset("LAST", "T.G"),
                ),
            ),
        ),
    )
```

`test_dcb.py`:

```python
"""Acceptance: every DCB form parses, and the job around it is intact."""

from tests.acceptance.markers import bridge_then_parsed
from tests.covers import NotLanguageFeature, covers


@bridge_then_parsed("red-dragon-forge-2cy.2")
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dcb_forms_parse(parse_fixture):
    from jackal.model import Job
    from tests.acceptance import build as b

    new_catlg = b.disp("NEW", "CATLG", "CATLG")
    assert parse_fixture("dcb/dcb.jcl") == Job(
        "ACCEPT",
        (
            b.pgm(
                "S1",
                "PGMA",
                (
                    b.dataset("A", "T.A", new_catlg),
                    b.dataset("B", "T.B", new_catlg),
                    b.dataset("C", "T.C", new_catlg),
                    b.dataset("D", "T.D", new_catlg),
                ),
            ),
            b.pgm("S2", "PGMB", (b.dataset("E", "T.A"),)),
        ),
    )
```

`(NEW,CATLG)` is `(NEW, CATLG, CATLG)`: an omitted abnormal value repeats the normal one. It is the easiest default to get wrong.

- [ ] **Step 3: Run and confirm xfailed for the right reason**

Run: `cd jackal && uv run --no-sync python -m pytest tests/acceptance/test_dsn.py tests/acceptance/test_concat.py tests/acceptance/test_dcb.py -q -rx`
Expected: `4 xfailed`, each on an `ImportError` from `tests.acceptance.build` or a new-model import.

- [ ] **Step 4: Commit**

```bash
git add jackal/tests/acceptance
git commit -m "test(jackal): DSN kind, concatenation and DCB acceptance fixtures"
```

---

### Task 4: PROC symbols and overrides families

**Files:**
- Create: `fixtures/symbols/symbols.jcl`, `fixtures/symbols/SYMP.prc`
- Create: `fixtures/overrides/overrides.jcl`, `fixtures/overrides/TWO.prc`
- Test: `test_symbols.py`, `test_overrides.py`

**Interfaces:**
- Consumes: Task 1's harness.
- Produces: nothing new.

- [ ] **Step 1: Write the fixtures**

`fixtures/symbols/SYMP.prc`:

```
//SYMP     PROC HLQ=T,SUFFIX=DFLT
//P1       EXEC PGM=PGMA,PARM='&SUFFIX'
//IN       DD DSN=&HLQ..IN,DISP=SHR
//OUT      DD DSN=&OUTNAME,DISP=(NEW,PASS)
```

`fixtures/symbols/symbols.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC SYMP
//S2       EXEC SYMP,HLQ=PROD,SUFFIX=&HLQ
```

`fixtures/overrides/TWO.prc`:

```
//TWO      PROC
//P1       EXEC PGM=PGMA,PARM='ONE',COND=(8,LT)
//IN       DD DSN=T.P1IN,DISP=SHR
//P2       EXEC PGM=PGMB,PARM='TWO'
//OUT      DD DSN=T.P2OUT,DISP=SHR
//LOG      DD DSN=T.P2LOG,DISP=SHR
```

`fixtures/overrides/overrides.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC TWO,PARM='X'
//S2       EXEC TWO,PARM.P2='Y'
//S3       EXEC TWO,PARM='X',PARM.P2='Y'
//S4       EXEC TWO,COND=(4,LT)
//S5       EXEC TWO,COND.P2=(0,NE)
//S6       EXEC TWO,PARM.P1=''
//S7       EXEC TWO
//IN       DD DSN=T.NEWIN,DISP=SHR
//P2.OUT   DD DSN=T.NEWOUT,DISP=SHR
//EXTRA    DD DSN=T.EXTRA,DISP=SHR
```

- [ ] **Step 2: Write the failing tests**

`test_symbols.py`:

```python
"""Acceptance: PROC symbolic parameters."""

from tests.acceptance.markers import EXPANDED
from tests.covers import NotLanguageFeature, covers


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_symbols_expand(expand_fixture):
    from jackal.expansion import ExpandedJob
    from jackal.model import ProcCall
    from jackal.value_parts import literal
    from tests.acceptance import build as b

    s1 = ProcCall(b.name("S1"), "SYMP")
    s2 = ProcCall(
        b.name("S2"),
        "SYMP",
        symbol_overrides=(
            (b.symbol("HLQ").name, literal("PROD")),
            (b.symbol("SUFFIX").name, (b.symbol("HLQ"),)),
        ),
    )
    out = b.temp("OUT", "OUTNAME", b.disp("NEW", "PASS", "DELETE"))
    assert expand_fixture("symbols/symbols.jcl") == ExpandedJob(
        "ACCEPT",
        (
            b.qualified(
                (s1,), b.pgm("P1", "PGMA", (b.dataset("IN", "T.IN"), out), parm="DFLT")
            ),
            b.qualified(
                (s2,),
                b.pgm("P1", "PGMA", (b.dataset("IN", "PROD.IN"), out), parm="PROD"),
            ),
        ),
    )
```

The second call's `SUFFIX=&HLQ` resolves against the caller's symbols. At job level `HLQ` is undefined, so this asserts the value resolves through the call's own `HLQ=PROD`. If the JCL Reference resolves a symbol in an override value against the job's symbols only, the expected `parm` is a JCL error instead; the unit-4 implementer checks the JCL Reference ("Symbolic parameters" chapter) before changing this expectation.

`test_overrides.py`:

```python
"""Acceptance: COND, PARM and DD overrides on a PROC call."""

from tests.acceptance.markers import EXPANDED, PARSED
from tests.covers import NotLanguageFeature, covers


@PARSED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_overrides_parse(parse_fixture):
    from jackal.model import Job, ProcCall, ProcStepOverrides
    from jackal.value_parts import literal
    from tests.acceptance import build as b

    p1, p2 = b.name("P1"), b.name("P2")
    assert parse_fixture("overrides/overrides.jcl") == Job(
        "ACCEPT",
        (
            ProcCall(b.name("S1"), "TWO", parm_for_first_step=literal("X")),
            ProcCall(
                b.name("S2"), "TWO", per_step=((p2, ProcStepOverrides(parm=literal("Y"))),)
            ),
            ProcCall(
                b.name("S3"),
                "TWO",
                parm_for_first_step=literal("X"),
                per_step=((p2, ProcStepOverrides(parm=literal("Y"))),),
            ),
            ProcCall(
                b.name("S4"), "TWO", cond_for_every_step=b.cond(b.all_prior(4, "LT"))
            ),
            ProcCall(
                b.name("S5"),
                "TWO",
                per_step=(
                    (p2, ProcStepOverrides(cond=b.cond(b.all_prior(0, "NE")))),
                ),
            ),
            ProcCall(b.name("S6"), "TWO", per_step=((p1, ProcStepOverrides(parm=())),)),
            ProcCall(
                b.name("S7"),
                "TWO",
                dds_for_first_step=(b.dataset("IN", "T.NEWIN"),),
                per_step=(
                    (
                        p2,
                        ProcStepOverrides(
                            dds=(
                                b.dataset("OUT", "T.NEWOUT"),
                                b.dataset("EXTRA", "T.EXTRA"),
                            )
                        ),
                    ),
                ),
            ),
        ),
    )


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_overrides_expand(expand_fixture, parse_fixture):
    from jackal.expansion import ExpandedJob
    from tests.acceptance import build as b

    calls = parse_fixture("overrides/overrides.jcl").steps
    p1_in = b.dataset("IN", "T.P1IN")
    p2_dds = (b.dataset("OUT", "T.P2OUT"), b.dataset("LOG", "T.P2LOG"))
    p1_cond = b.cond(b.all_prior(8, "LT"))

    def run(
        call: object,
        p1_parm: str,
        p2_parm: str,
        p1_condition: object = p1_cond,
        p2_condition: object = b.NO_COND,
        p1_dds: tuple[object, ...] = (p1_in,),
        p2_dds_: tuple[object, ...] = p2_dds,
    ) -> tuple[object, ...]:
        return (
            b.qualified((call,), b.pgm("P1", "PGMA", p1_dds, p1_condition, p1_parm)),
            b.qualified((call,), b.pgm("P2", "PGMB", p2_dds_, p2_condition, p2_parm)),
        )

    every = b.cond(b.all_prior(4, "LT"))
    assert expand_fixture("overrides/overrides.jcl") == ExpandedJob(
        "ACCEPT",
        (
            *run(calls[0], "X", ""),
            *run(calls[1], "ONE", "Y"),
            *run(calls[2], "X", "Y"),
            *run(calls[3], "ONE", "TWO", every, every),
            *run(calls[4], "ONE", "TWO", p2_condition=b.cond(b.all_prior(0, "NE"))),
            *run(calls[5], "", "TWO"),
            *run(
                calls[6],
                "ONE",
                "TWO",
                p1_dds=(b.dataset("IN", "T.NEWIN"),),
                p2_dds_=(
                    b.dataset("OUT", "T.NEWOUT"),
                    b.dataset("LOG", "T.P2LOG"),
                    b.dataset("EXTRA", "T.EXTRA"),
                ),
            ),
        ),
    )
```

- [ ] **Step 3: Run and confirm xfailed for the right reason**

Run: `cd jackal && uv run --no-sync python -m pytest tests/acceptance/test_symbols.py tests/acceptance/test_overrides.py -q -rx`
Expected: `3 xfailed`, each on a new-model `ImportError`.

- [ ] **Step 4: Commit**

```bash
git add jackal/tests/acceptance
git commit -m "test(jackal): PROC symbol and override acceptance fixtures"
```

---

### Task 5: Nesting, references, JCL errors and unresolved PROCs

**Files:**
- Create: `fixtures/nesting/nesting.jcl`, `fixtures/nesting/OUTER.prc`, `fixtures/nesting/INNER.prc`
- Create: `fixtures/refs/refs.jcl`, `fixtures/refs/TWO.prc`
- Create: `fixtures/errors/dangling.jcl`, `dangling_dd.jcl`, `forward.jcl`, `proc_call.jcl`, `no_step.jcl`, `circular.jcl`, `fixtures/errors/TWO.prc`, `fixtures/errors/CIRCA.prc`, `fixtures/errors/CIRCB.prc`
- Create: `fixtures/unresolved/unresolved.jcl`
- Test: `test_nesting.py`, `test_references.py`, `test_errors.py`, `test_unresolved.py`

**Interfaces:**
- Consumes: Task 1's harness; `tmp_path` for the 15-level chain.
- Produces: nothing new.

- [ ] **Step 1: Write the fixtures**

`fixtures/nesting/INNER.prc`:

```
//INNER    PROC
//Q1       EXEC PGM=PGMQ,PARM='INNER'
```

`fixtures/nesting/OUTER.prc`:

```
//OUTER    PROC
//P1       EXEC INNER,PARM.Q1='SET'
//P2       EXEC PGM=PGMB
```

`fixtures/nesting/nesting.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC OUTER
```

`fixtures/refs/TWO.prc`:

```
//TWO      PROC
//P1       EXEC PGM=PGMA
//P2       EXEC PGM=PGMB,COND=((0,NE,P1),(4,LT,S0))
```

`fixtures/refs/refs.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S0       EXEC PGM=PGMZ
//S1       EXEC TWO
//S2       EXEC PGM=PGMC,COND=((4,LT,S1.P2),(8,LT,S0))
//S3       EXEC TWO
```

`fixtures/errors/TWO.prc`: same text as `fixtures/refs/TWO.prc` but with `COND` removed:

```
//TWO      PROC
//P1       EXEC PGM=PGMA
//P2       EXEC PGM=PGMB
```

`fixtures/errors/dangling.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC PGM=PGMA
//S2       EXEC PGM=PGMB,COND=(4,LT,NOPE)
```

`fixtures/errors/dangling_dd.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC PGM=PGMA
//IN       DD DSN=T.IN,DISP=SHR
//S2       EXEC PGM=PGMB
//COPY     DD DSN=*.S1.NOPE,DISP=SHR
```

`fixtures/errors/forward.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC PGM=PGMA,COND=(4,LT,S2)
//S2       EXEC PGM=PGMB
```

`fixtures/errors/proc_call.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC TWO
//S2       EXEC PGM=PGMB,COND=(4,LT,S1)
```

`fixtures/errors/no_step.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC TWO,PARM.P9='X'
```

`fixtures/errors/CIRCA.prc`:

```
//CIRCA    PROC
//A1       EXEC CIRCB
```

`fixtures/errors/CIRCB.prc`:

```
//CIRCB    PROC
//B1       EXEC CIRCA
```

`fixtures/errors/circular.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC CIRCA
```

`fixtures/unresolved/unresolved.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC PGM=PGMA
//S2       EXEC NOSUCHP
```

- [ ] **Step 2: Write the failing tests**

`test_nesting.py`:

```python
"""Acceptance: nested PROCs, an override inside the intermediate PROC, 15 levels."""

from pathlib import Path

from tests.acceptance.markers import EXPANDED
from tests.covers import NotLanguageFeature, covers


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_nested_procs_expand(expand_fixture):
    from jackal.expansion import ExpandedJob
    from jackal.model import ProcCall, ProcStepOverrides
    from jackal.value_parts import literal
    from tests.acceptance import build as b

    s1 = ProcCall(b.name("S1"), "OUTER")
    p1 = ProcCall(
        b.name("P1"),
        "INNER",
        per_step=((b.name("Q1"), ProcStepOverrides(parm=literal("SET"))),),
    )
    assert expand_fixture("nesting/nesting.jcl") == ExpandedJob(
        "ACCEPT",
        (
            b.qualified((s1, p1), b.pgm("Q1", "PGMQ", parm="SET")),
            b.qualified((s1,), b.pgm("P2", "PGMB")),
        ),
    )


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_fifteen_levels_expand(tmp_path: Path, jcl_bridge_jar: str):
    from jackal.expansion import DirectoryProcLibrary, ExpandedJob, expand_procs
    from jackal.jcl.parser import parse_jcl
    from jackal.model import ProcCall
    from tests.acceptance import build as b

    for level in range(1, 15):
        (tmp_path / f"L{level}.prc").write_text(
            f"//L{level}       PROC\n//C{level}       EXEC L{level + 1}\n"
        )
    (tmp_path / "L15.prc").write_text("//L15      PROC\n//DEEP     EXEC PGM=PGMD\n")
    job = parse_jcl("//ACCEPT   JOB (A),'ACCEPT',CLASS=A\n//S1       EXEC L1\n")
    calls = (ProcCall(b.name("S1"), "L1"),) + tuple(
        ProcCall(b.name(f"C{level}"), f"L{level + 1}") for level in range(1, 15)
    )
    assert expand_procs(job, DirectoryProcLibrary((tmp_path,))) == ExpandedJob(
        "ACCEPT", (b.qualified(calls, b.pgm("DEEP", "PGMD")),)
    )
```

`test_references.py`:

```python
"""Acceptance: how references resolve in each scope."""

from tests.acceptance.markers import EXPANDED
from tests.covers import NotLanguageFeature, covers


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_reference_inside_proc_expands(expand_fixture, parse_fixture):
    from jackal.expansion import ExpandedJob
    from tests.acceptance import build as b

    steps = parse_fixture("refs/refs.jcl").steps
    s1_call, s3_call = steps[1], steps[3]
    s0 = b.qualified((), b.pgm("S0", "PGMZ"))

    def run(call: object) -> tuple[object, object]:
        p1 = b.qualified((call,), b.pgm("P1", "PGMA"))
        p2 = b.qualified(
            (call,),
            b.pgm(
                "P2", "PGMB", condition=b.cond(b.on_step(0, "NE", p1), b.on_step(4, "LT", s0))
            ),
        )
        return p1, p2

    first_p1, first_p2 = run(s1_call)
    second_p1, second_p2 = run(s3_call)
    s2 = b.qualified(
        (),
        b.pgm(
            "S2",
            "PGMC",
            condition=b.cond(b.on_step(4, "LT", first_p2), b.on_step(8, "LT", s0)),
        ),
    )
    assert expand_fixture("refs/refs.jcl") == ExpandedJob(
        "ACCEPT", (s0, first_p1, first_p2, s2, second_p1, second_p2)
    )
```

This test pins four rules at once: an inner name resolves within its own PROC run, an inner name falls back to a job-level program step (`S0`), `S1.P2` reaches into a call, and the second run of `TWO` resolves `P1` to its own run (blueprint D6, drafted answer).

`test_errors.py`:

```python
"""Acceptance: each JclError variant."""

from tests.acceptance.markers import EXPANDED
from tests.covers import NotLanguageFeature, covers


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_jcl_errors_expand(expand_fixture, parse_fixture):
    from jackal.expansion import (
        CircularProc,
        DanglingDdReference,
        DanglingReference,
        ErrorSite,
        ForwardReference,
        OverrideNamesNoStep,
        ReferenceToProcCall,
    )
    from tests.acceptance import build as b

    def step(rel: str, index: int) -> object:
        return parse_fixture(rel).steps[index]

    assert [
        expand_fixture("errors/dangling.jcl"),
        expand_fixture("errors/dangling_dd.jcl"),
        expand_fixture("errors/forward.jcl"),
        expand_fixture("errors/proc_call.jcl"),
        expand_fixture("errors/no_step.jcl"),
        expand_fixture("errors/circular.jcl"),
    ] == [
        DanglingReference(ErrorSite((), step("errors/dangling.jcl", 1)), b.ref("NOPE")),
        DanglingDdReference(
            ErrorSite((), step("errors/dangling_dd.jcl", 1)), b.ref("S1"), "NOPE"
        ),
        ForwardReference(ErrorSite((), step("errors/forward.jcl", 0)), b.ref("S2")),
        ReferenceToProcCall(
            ErrorSite((), step("errors/proc_call.jcl", 1)), b.ref("S1")
        ),
        OverrideNamesNoStep(step("errors/no_step.jcl", 0), b.name("P9")),
        CircularProc(("CIRCA", "CIRCB", "CIRCA")),
    ]
```

The six cases are one test because they are one behaviour, "expansion rejects JCL before any step runs", and the list comparison shows every mismatch at once.

`test_unresolved.py`:

```python
"""Acceptance: a call to a PROC in no library."""

from tests.acceptance.markers import EXPANDED
from tests.covers import NotLanguageFeature, covers


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_unresolved_proc_expands(expand_fixture):
    from jackal.expansion import ExpandedJob, UnresolvedProcCall
    from jackal.model import ProcCall
    from tests.acceptance import build as b

    assert expand_fixture("unresolved/unresolved.jcl") == ExpandedJob(
        "ACCEPT",
        (
            b.qualified((), b.pgm("S1", "PGMA")),
            b.qualified((), UnresolvedProcCall(ProcCall(b.name("S2"), "NOSUCHP"))),
        ),
    )
```

- [ ] **Step 3: Run and confirm xfailed for the right reason**

Run: `cd jackal && uv run --no-sync python -m pytest tests/acceptance/test_nesting.py tests/acceptance/test_references.py tests/acceptance/test_errors.py tests/acceptance/test_unresolved.py -q -rx`
Expected: `5 xfailed`, each on an `ImportError` for `jackal.expansion`.

- [ ] **Step 4: Commit**

```bash
git add jackal/tests/acceptance
git commit -m "test(jackal): nesting, reference, JCL error and unresolved-PROC acceptance fixtures"
```

---

### Task 6: IF/THEN/ELSE family

**Files:**
- Create: `fixtures/if/if.jcl`, `fixtures/if/terms.jcl`, `fixtures/if/IFP.prc`, `fixtures/if/in_proc.jcl`
- Test: `test_if.py`

**Interfaces:**
- Consumes: Task 1's harness.
- Produces: nothing new.

- [ ] **Step 1: Write the fixtures**

`fixtures/if/if.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC PGM=PGMA
//C1       IF (S1.RC = 0) THEN
//S2       EXEC PGM=PGMB
//C2       IF (S2.RC > 4) THEN
//S3       EXEC PGM=PGMC
//         ENDIF
//         ELSE
//S4       EXEC PGM=PGMD
//         ENDIF
//S5       EXEC PGM=PGME
```

`fixtures/if/terms.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC PGM=PGMA
//T1       IF RC NG 4 THEN
//S2       EXEC PGM=PGMB
//         ENDIF
//T2       IF ABEND THEN
//S3       EXEC PGM=PGMC
//         ENDIF
//T3       IF S1.ABEND THEN
//S4       EXEC PGM=PGMD
//         ENDIF
//T4       IF ¬ABEND THEN
//S5       EXEC PGM=PGME
//         ENDIF
//T5       IF ABENDCC = U0100 THEN
//S6       EXEC PGM=PGMF
//         ENDIF
//T6       IF S1.ABENDCC = S0C7 THEN
//S7       EXEC PGM=PGMG
//         ENDIF
//T7       IF S1.RUN AND (S1.RC < 8 OR NOT S1.ABEND) THEN
//S8       EXEC PGM=PGMH
//         ENDIF
//T8       IF S1.RUN & (S1.RC NL 2 | ¬S1.RUN) THEN
//S9       EXEC PGM=PGMI
//         ENDIF
```

`fixtures/if/IFP.prc`:

```
//IFP      PROC
//P1       EXEC PGM=PGMA
//I1       IF (P1.RC = 0) THEN
//P2       EXEC PGM=PGMB
//         ENDIF
```

`fixtures/if/in_proc.jcl`:

```
//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC IFP
```

- [ ] **Step 2: Write the failing tests**

`test_if.py`:

```python
"""Acceptance: IF/THEN/ELSE/ENDIF as structure, then as guards."""

from tests.acceptance.markers import bridge_then_expanded, bridge_then_parsed
from tests.covers import NotLanguageFeature, covers


@bridge_then_parsed("red-dragon-forge-2cy.7")
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_structure_parses(parse_fixture):
    from jackal.model import CondOp, IfBlock, Job, RcTest
    from tests.acceptance import build as b

    assert parse_fixture("if/if.jcl") == Job(
        "ACCEPT",
        (
            b.pgm("S1", "PGMA"),
            IfBlock(
                b.name("C1"),
                RcTest(b.ref("S1"), CondOp.EQ, 0),
                (
                    b.pgm("S2", "PGMB"),
                    IfBlock(
                        b.name("C2"),
                        RcTest(b.ref("S2"), CondOp.GT, 4),
                        (b.pgm("S3", "PGMC"),),
                    ),
                ),
                (b.pgm("S4", "PGMD"),),
            ),
            b.pgm("S5", "PGME"),
        ),
    )


@bridge_then_parsed("red-dragon-forge-2cy.7")
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_terms_parse(parse_fixture):
    from jackal.model import (
        AbendCodeTest,
        AbendTest,
        AllOf,
        AllPriorSteps,
        AnyOf,
        CondOp,
        IfBlock,
        Job,
        Negated,
        RcTest,
        RunTest,
        SystemAbend,
        UserAbend,
    )
    from tests.acceptance import build as b

    s1 = b.ref("S1")

    def block(label: str, guard: object, step: object) -> IfBlock:
        return IfBlock(b.name(label), guard, (step,))

    assert parse_fixture("if/terms.jcl") == Job(
        "ACCEPT",
        (
            b.pgm("S1", "PGMA"),
            block("T1", RcTest(AllPriorSteps(), CondOp.LE, 4), b.pgm("S2", "PGMB")),
            block("T2", AbendTest(AllPriorSteps()), b.pgm("S3", "PGMC")),
            block("T3", AbendTest(s1), b.pgm("S4", "PGMD")),
            block("T4", Negated(AbendTest(AllPriorSteps())), b.pgm("S5", "PGME")),
            block(
                "T5", AbendCodeTest(AllPriorSteps(), UserAbend(100)), b.pgm("S6", "PGMF")
            ),
            block("T6", AbendCodeTest(s1, SystemAbend(0x0C7)), b.pgm("S7", "PGMG")),
            block(
                "T7",
                AllOf(
                    (
                        RunTest(s1),
                        AnyOf((RcTest(s1, CondOp.LT, 8), Negated(AbendTest(s1)))),
                    )
                ),
                b.pgm("S8", "PGMH"),
            ),
            block(
                "T8",
                AllOf(
                    (
                        RunTest(s1),
                        AnyOf((RcTest(s1, CondOp.GE, 2), Negated(RunTest(s1)))),
                    )
                ),
                b.pgm("S9", "PGMI"),
            ),
        ),
    )


@bridge_then_expanded("red-dragon-forge-2cy.7")
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_guards_expand(expand_fixture):
    from jackal.expansion import ExpandedJob
    from jackal.model import AllOf, CondOp, Negated, ProgramStep, RcTest
    from tests.acceptance import build as b

    s1 = b.qualified((), b.pgm("S1", "PGMA"))
    on_s1 = RcTest(s1, CondOp.EQ, 0)

    def guarded(label: str, program: str, guard: object) -> object:
        plain = b.pgm(label, program)
        return b.qualified(
            (), ProgramStep(plain.label, plain.pgm, plain.dds, plain.cond, plain.parm, guard)
        )

    s2 = guarded("S2", "PGMB", on_s1)
    assert expand_fixture("if/if.jcl") == ExpandedJob(
        "ACCEPT",
        (
            s1,
            s2,
            guarded("S3", "PGMC", AllOf((on_s1, RcTest(s2, CondOp.GT, 4)))),
            guarded("S4", "PGMD", Negated(on_s1)),
            b.qualified((), b.pgm("S5", "PGME")),
        ),
    )


@bridge_then_expanded("red-dragon-forge-2cy.7")
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_inside_proc_expands(expand_fixture):
    from jackal.expansion import ExpandedJob
    from jackal.model import CondOp, ProcCall, ProgramStep, RcTest
    from tests.acceptance import build as b

    call = ProcCall(b.name("S1"), "IFP")
    p1 = b.qualified((call,), b.pgm("P1", "PGMA"))
    plain = b.pgm("P2", "PGMB")
    assert expand_fixture("if/in_proc.jcl") == ExpandedJob(
        "ACCEPT",
        (
            p1,
            b.qualified(
                (call,),
                ProgramStep(
                    plain.label,
                    plain.pgm,
                    plain.dds,
                    plain.cond,
                    plain.parm,
                    RcTest(p1, CondOp.EQ, 0),
                ),
            ),
        ),
    )
```

The `¬` in `terms.jcl` is the JCL NOT sign. If the Talisman hook rejects the fixture as it rejected the spec, stop and ask before touching `.talismanrc`; the character is the construct under test and cannot be reworded.

- [ ] **Step 3: Run and confirm xfailed for the right reason**

Run: `cd jackal && uv run --no-sync python -m pytest tests/acceptance/test_if.py -q -rx`
Expected: `4 xfailed`, each on a new-model `ImportError`.

- [ ] **Step 4: Commit**

```bash
git add jackal/tests/acceptance
git commit -m "test(jackal): IF/THEN/ELSE acceptance fixtures, structure and guards"
```

---

### Task 7: CardDemo snapshot and comparison test

**Files:**
- Create: `jackal/tests/acceptance/carddemo_facts.py`
- Create: `jackal/tests/acceptance/carddemo_snapshot.json` (generated)
- Test: `jackal/tests/acceptance/test_carddemo_snapshot.py`

**Interfaces:**
- Consumes: today's `jackal.jcl.parser.parse_jcl`, `jackal.jcl.proc_expand.expand_procs`, `jackal.model` (old), `jackal.dsn`, `jackal.value_parts`; the `carddemo_home` fixture from `jackal/tests/conftest.py`.
- Produces: `facts_for_corpus(carddemo_root: Path) -> CardDemoSnapshot`, `CardDemoSnapshot` and its models, and `EXPECTED_CHANGES: dict[str, str]`. Unit 3 rewrites only `facts_for_job` against the new model; the facts shape stays.

- [ ] **Step 1: Write the comparison test first**

`test_carddemo_snapshot.py`:

```python
"""What jackal reads from every CardDemo job matches the frozen snapshot."""

from pathlib import Path

from tests.acceptance.carddemo_facts import (
    EXPECTED_CHANGES,
    SNAPSHOT,
    CardDemoSnapshot,
    facts_for_corpus,
)
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_carddemo_matches_snapshot(carddemo_home: Path, jcl_bridge_jar: str):
    frozen = CardDemoSnapshot.model_validate_json(SNAPSHOT.read_text())
    current = facts_for_corpus(carddemo_home.parent)
    frozen_by_file = {job.file: job for job in frozen.jobs}
    differing = sorted(
        job.file for job in current.jobs if frozen_by_file.get(job.file) != job
    )
    assert (
        sorted(job.file for job in current.jobs),
        differing,
    ) == (
        sorted(frozen_by_file),
        sorted(EXPECTED_CHANGES),
    )
```

`carddemo_home` is `vendor/carddemo/app`; its parent is the CardDemo root, which holds `app/`, `app/app-*/` and `samples/`.

- [ ] **Step 2: Run it to see it fail**

Run: `cd jackal && uv run --no-sync python -m pytest tests/acceptance/test_carddemo_snapshot.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.acceptance.carddemo_facts'`.

- [ ] **Step 3: Write the facts module**

`carddemo_facts.py`:

```python
"""What jackal reads from each CardDemo job, as plain facts that survive a model change."""

import argparse
import logging
from pathlib import Path
from typing import Literal as TypeLiteral

from pydantic import BaseModel, ConfigDict

from jackal.dsn import (
    DSN,
    BackwardRef,
    DirectDSN,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    TempRef,
)
from jackal.jcl.bridge_parser import JclParseError
from jackal.jcl.parser import parse_jcl
from jackal.jcl.proc_expand import ProcExpansionError, expand_procs
from jackal.model import DD, Step
from jackal.value_parts import Literal, Symbol, Value

logger = logging.getLogger(__name__)

SNAPSHOT = Path(__file__).parent / "carddemo_snapshot.json"
PROC_DIRS = ("app/proc", "samples/proc")

EXPECTED_CHANGES: dict[str, str] = {}


class DdFacts(BaseModel):
    model_config = ConfigDict(frozen=True)
    ddname: str
    dsn: str
    disp: tuple[str, str, str]


class StepFacts(BaseModel):
    model_config = ConfigDict(frozen=True)
    step: str
    pgm: str
    parm: str
    cond: tuple[tuple[int, str, str], ...]
    dds: tuple[DdFacts, ...]


class ReadJob(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: TypeLiteral["read"] = "read"
    file: str
    job: str
    steps: tuple[StepFacts, ...]


class UnreadJob(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: TypeLiteral["unread"] = "unread"
    file: str
    error: str


class CardDemoSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    jobs: tuple[ReadJob | UnreadJob, ...]


def _part_text(part: Literal | Symbol) -> str:
    match part:
        case Literal(text=text):
            return text
        case Symbol(name=symbol):
            return f"&{symbol}"


def _text(value: Value) -> str:
    return "".join(_part_text(part) for part in value)


def _dsn_text(dsn: DSN, sysout: bool) -> str:
    match dsn:
        case DirectDSN(name=n):
            return _text(n)
        case TempRef(alias=a):
            return a
        case BackwardRef(step=s, ddname=d):
            return f"*.{s}.{d}"
        case InStreamDSN():
            return "*"
        case DummyDSN():
            return "DUMMY"
        case NoDSN():
            return "SYSOUT" if sysout else ""


def _dd_facts(dd: DD) -> DdFacts:
    return DdFacts(
        ddname=dd.ddname,
        dsn=_dsn_text(dd.dsn, dd.sysout),
        disp=(dd.disp.status.value, dd.disp.normal.value, dd.disp.abnormal.value),
    )


def _step_facts(step: Step) -> StepFacts:
    return StepFacts(
        step=step.name,
        pgm=step.pgm,
        parm=_text(step.parm),
        cond=tuple((c.code, c.op.value, c.step) for c in step.conds),
        dds=tuple(_dd_facts(dd) for dd in step.dds),
    )


def facts_for_job(carddemo_root: Path, path: Path) -> ReadJob | UnreadJob:
    rel = str(path.relative_to(carddemo_root))
    try:
        job = expand_procs(
            parse_jcl(path.read_text(errors="replace")),
            tuple(carddemo_root / d for d in PROC_DIRS),
        )
    except (JclParseError, ProcExpansionError) as error:
        return UnreadJob(file=rel, error=type(error).__name__)
    return ReadJob(
        file=rel, job=job.name, steps=tuple(_step_facts(s) for s in job.steps)
    )


def facts_for_corpus(carddemo_root: Path) -> CardDemoSnapshot:
    paths = sorted(
        p for p in carddemo_root.rglob("*") if p.suffix.lower() == ".jcl"
    )
    logger.info("reading %d CardDemo JCL members", len(paths))
    return CardDemoSnapshot(jobs=tuple(facts_for_job(carddemo_root, p) for p in paths))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write the CardDemo facts snapshot from today's code."
    )
    parser.add_argument("carddemo_root", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    SNAPSHOT.write_text(facts_for_corpus(args.carddemo_root).model_dump_json(indent=1))
    logger.info("wrote %s", SNAPSHOT)


if __name__ == "__main__":
    main()
```

`_dsn_text` renders today's `TempRef(alias)`, which holds `&&NAME` text, and today's `BackwardRef(step: str)`. Unit 3 changes this function to read the new `TempRef(name)` and the new `BackwardRef(step: StepRef)`, rendering them the same way (`&&NAME`, `*.S1.DD`, `*.S1.P1.DD`), so the frozen facts still compare.

- [ ] **Step 4: Generate the snapshot**

Run from the repo root:

```bash
. ./bridge-env.sh
cd jackal && uv run --no-sync python -m tests.acceptance.carddemo_facts ../vendor/carddemo
```

Expected log: `reading 55 CardDemo JCL members`, then `wrote …/carddemo_snapshot.json`. Open the file and check two entries by hand: `app/app-transaction-type-db2/jcl/TRANEXTR.jcl` is `{"kind": "unread", "error": "JclParseError"}` (bug `red-dragon-forge-z76`), and `samples/jcl/RACFCMDS.jcl` is unread too (its statements after the null `//` statement have no JOB card, so the parse error is correct JCL behaviour).

- [ ] **Step 5: Run the comparison test**

Run: `cd jackal && uv run --no-sync python -m pytest tests/acceptance/test_carddemo_snapshot.py -q`
Expected: PASS.

- [ ] **Step 6: Mutation-check it**

1. Change one `disp` value in `carddemo_snapshot.json` by hand. Rerun and expect FAIL, naming that file in the `differing` list. Revert.
2. Add `"app/jcl/ACCTFILE.jcl": "test"` to `EXPECTED_CHANGES`. Rerun and expect FAIL, because the expected-changes list no longer matches. Revert.

- [ ] **Step 7: Run the whole jackal suite and commit**

Run: `cd jackal && uv run --no-sync python -m pytest -q`
Expected: all previously passing tests pass, the acceptance tests are `xfailed`, and there are no errors.

```bash
git add jackal/tests/acceptance
git commit -m "test(jackal): freeze what today's code reads from every CardDemo job"
```

---

### Task 8: Close unit 1

**Files:**
- Modify: `issues/issues.jsonl` (via `bd`)
- Modify: `docs/roadmaps/jackal.md`

- [ ] **Step 1: Update the roadmap**

In `docs/roadmaps/jackal.md`, add this row under the parse rows:

```
| JCL object model per the 2026-10-10 blueprint: parsed model and expansion, pinned by an acceptance suite | `red-dragon-forge-2cy.9`, `red-dragon-forge-2cy.10` | not started |
```

- [ ] **Step 2: Close the issue and export**

```bash
bd close red-dragon-forge-2cy.8 --reason "Acceptance suite (strict xfail) and CardDemo snapshot committed"
bd export -o issues/issues.jsonl
```

- [ ] **Step 3: Commit and push**

```bash
git add docs/roadmaps/jackal.md issues/issues.jsonl
git commit -m "docs(jackal): roadmap rows for the JCL object model; close unit 1"
git push
```
