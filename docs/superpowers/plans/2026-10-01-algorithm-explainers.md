# Algorithm explainers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four interactive HTML pages under `docs/explainers/` that teach fixpoints, reaching definitions, byte-extent aliasing and value sets to a general engineer, each checked against cobble's real answer.

**Architecture:** Static pages with no build step and no network. A shared `stepper.js` drives a step-through widget, and each page carries a small model of its technique. Each page embeds one JSON block holding its COBOL program and expected answer. A cobble test parses that program with the real ProLeap bridge, runs the fixpoint stage, and asserts cobble's answer equals the expected one. Each page checks its own model against the same block on load.

**Tech Stack:** HTML, CSS, plain JavaScript (classic scripts, not modules); Python 3.13, pytest, pydantic for the test.

**Spec:** `docs/superpowers/specs/2026-10-01-algorithm-explainers-design.md`

## Global Constraints

- **Pages open from disk.**
  - No server, bundler or framework, and no network: no CDN scripts or fonts.
  - Classic `<script src>` only; browsers refuse ES modules over `file://`.
- **Look and layout.**
  - Palette taken from `docs/presentation/theme.css`.
  - Dark and light schemes through `prefers-color-scheme`.
  - No horizontal scrolling at 390 px width.
- **Comments.** No comments beyond a one-line header per file, in JS, CSS and Python alike.
- **Invented examples only.** Program and field names are generic; nothing comes from any corpus under analysis.
- **The answer each page checks is cobble's real answer.** The values below were produced by running the pipeline on these exact programs on 2026-10-01. If a test disagrees, investigate: never edit `expected` to make it pass.
- **The test** lives in `cobble/tests/explainers/test_explainers.py`. It needs the ProLeap bridge JAR, found and skipped the same way as `cobble/tests/dataflow/fields/test_fields_synthetic.py` (`make jar` builds it).
- **Gate:**
  - `make fmt`;
  - `uv run pyright` on touched Python files (zero errors);
  - `pre-commit run python-fp-lint-check --hook-stage manual --files <touched .py>`;
  - `cd cobble && uv run --no-sync python -m pytest tests/explainers -q`.
- **Talisman** flags short words like "key" and "pass" inside identifiers. Reword rather than touch `.talismanrc`.

## Review Focus

1. **A page whose model drifts from its expected answer.** The page must show the red banner, not silently render a different final state. Pinned in Task 1's by-hand check: edit one expected value and reload.
2. **A page with no example block, or a malformed one.** The test must fail naming the page, not skip it. Pinned in Task 1.
3. **Phone width and light mode.** These are checked by hand per page; nothing automated covers them.
4. **The byte-extents imprecision.** Cobble reports the earlier group write as a definer of a read it no longer feeds. The page must teach this as a sound over-approximation, not hide it (Task 3).
5. **A stale `index.html`.** A page on disk that the index does not link, or a link to a missing page. Pinned by `test_the_index_links_exactly_the_pages_on_disk` (Task 1).

---

### Task 1: Shared assets, the check, and the fixpoints page

**Files:**
- Create: `docs/explainers/explainer.css`, `docs/explainers/stepper.js`, `docs/explainers/index.html`, `docs/explainers/fixpoints.html`
- Create: `cobble/tests/explainers/test_explainers.py`
- Modify: `README.md` (one line after the package-boundaries paragraph, before `## Quick start`: "How the field dataflow works, for engineers new to it: [`docs/explainers/`](docs/explainers/index.html).")

**Interfaces:**
- Produces:
  - `stepper.js` defines the global `Stepper.mount(container: HTMLElement, steps: Step[], render: (step, index) => string)`, where `Step` is a page-defined object with at least `{note: string}`.
  - It also defines `Stepper.verify(actual: object, expected: object)`. That inserts a red banner at the top of `<main>` when the two differ, comparing `JSON.stringify` of their canonical forms: arrays sorted, object keys sorted.
  - The example block shape (below), which every later task fills in.

**The example block.** Exactly one per page:

```html
<script type="application/json" id="example">
{"member": "FIXLOOP", "program": "<COBOL source, \n-separated>",
 "expected": {"checks": ["flows"], "flows": [["FIXLOOP.WS-A", "FIXLOOP.WS-B"], ...]}}
</script>
```

`expected.checks` names which of three answers are asserted (at least one):
- `"flows"`: `[[source_id, target_id], ...]`, compared as a set;
- `"defs"`: `[{"node", "extent", "definers": [...]}, ...]`, compared as a set of rows, with definers in order;
- `"targets"`: `[{"node", "expression", "candidates": [...], "reasons": [...]}, ...]`, compared as a set of rows.

- [ ] **Step 1: Write the failing test.** `cobble/tests/explainers/test_explainers.py`:

```python
"""Every explainer page teaches the answer cobble actually reaches on its example."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import pytest
from cobble.dataflow.fields.emit_extents import emit
from cobble.dataflow.fixpoint import rows
from cobble.dataflow.fixpoint.build_corpus import cli
from cobble.knowledge_graph.graph_file import read_graph
from cobble.parsing.parse_corpus import Job, parse_one
from pydantic import BaseModel, ConfigDict, Field

FORGE = Path(__file__).resolve().parents[3]
EXPLAINERS = FORGE / "docs" / "explainers"
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"
OPENING = '<script type="application/json" id="example">'
CLOSING = "</script>"
PAGES = ("fixpoints.html",)


class Check(StrEnum):
    FLOWS = "flows"
    DEFS = "defs"
    TARGETS = "targets"


class _Defs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node: str
    extent: str
    definers: tuple[str, ...]


class _Target(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node: str
    expression: str
    candidates: tuple[str, ...]
    reasons: tuple[str, ...]


class _Expected(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    checks: tuple[Check, ...] = Field(min_length=1)
    flows: tuple[tuple[str, str], ...] = ()
    defs: tuple[_Defs, ...] = ()
    targets: tuple[_Target, ...] = ()


class _Example(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    member: str
    program: str
    expected: _Expected


def _example(page: str) -> _Example:
    html = (EXPLAINERS / page).read_text(encoding="utf-8")
    assert html.count(OPENING) == 1, f"{page} needs exactly one example block"
    return _Example.model_validate_json(html.partition(OPENING)[2].partition(CLOSING)[0])


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


def _analysed(example: _Example, workspace: Path) -> Path:
    source = workspace / f"{example.member}.cbl"
    source.write_text(example.program, encoding="utf-8")
    cache = workspace / "parsed"
    cache.mkdir()
    parsed = parse_one(
        Job(source, cache / f"{example.member}.json"), str(_bridge_jar()), (), ("cpy",)
    )
    assert parsed.ok, parsed.error
    extents = workspace / "extents.jsonl"
    assert emit(cache, extents, (), max_workers=1) == 0
    out = workspace / "out"
    cli(
        ["--asg-dir", str(cache), "--out-dir", str(out), "--extents", str(extents),
         "--member", example.member, "--max-workers", "1", "--min-coverage", "0"]
    )
    return out


def _flows(out: Path) -> frozenset[tuple[str, str]]:
    _, edges = read_graph(out / "graph.jsonl")
    return frozenset((edge.source, edge.target) for edge in edges)


def _defs(out: Path) -> frozenset[_Defs]:
    return frozenset(
        _Defs(
            node=rows.text(row, "node"),
            extent=rows.text(row, "extent"),
            definers=rows.strings(row, "definers"),
        )
        for row in rows.read(out / "defs.jsonl")
    )


def _targets(out: Path) -> frozenset[_Target]:
    return frozenset(
        _Target(
            node=rows.text(row, "node"),
            expression=rows.text(row, "expression"),
            candidates=rows.strings(row, "candidates"),
            reasons=rows.strings(row, "reasons"),
        )
        for row in rows.read(out / "targets.jsonl")
    )


@pytest.mark.parametrize("page", PAGES)
def test_the_page_teaches_cobbles_answer(page: str, tmp_path: Path) -> None:
    expected = _example(page).expected
    out = _analysed(_example(page), tmp_path)

    if Check.FLOWS in expected.checks:
        assert _flows(out) == frozenset(expected.flows)
    if Check.DEFS in expected.checks:
        assert _defs(out) == frozenset(expected.defs)
    if Check.TARGETS in expected.checks:
        assert _targets(out) == frozenset(expected.targets)


def test_the_index_links_exactly_the_pages_on_disk() -> None:
    on_disk = {path.name for path in EXPLAINERS.glob("*.html")} - {"index.html"}
    index = (EXPLAINERS / "index.html").read_text(encoding="utf-8")
    linked = {page for page in on_disk if f'href="{page}"' in index}
    assert (on_disk, linked) == (set(PAGES), set(PAGES))
```

  - **The fixed-literal extraction** (`OPENING`/`CLOSING` with `partition`) is the parse boundary. A page with no block, or two, fails naming the page (Review Focus 2). Malformed JSON fails in `model_validate_json`.
  - **`checks` has `min_length=1`,** so a block that asserts nothing is rejected at validation, not passed vacuously.
  - **Each later task appends its page to `PAGES`.**

- [ ] **Step 2: Run it and see it fail.** `cd cobble && uv run --no-sync python -m pytest tests/explainers -q`. Expected: both tests fail. `test_the_page_teaches_cobbles_answer[fixpoints.html]` fails with `FileNotFoundError` for `docs/explainers/fixpoints.html`, and the index test fails with `FileNotFoundError` for `index.html`.

- [ ] **Step 3: Write the shared assets.**
  - **`explainer.css`:**
    - the presentation palette as `:root` custom properties, redefined under `@media (prefers-color-scheme: light)`;
    - a readable measure (`max-width: 46rem`) for prose;
    - `.stepper` styles: a controls row, a step counter, and a `.note` line for each step's one-sentence explanation;
    - `.banner-error` in red;
    - `pre.cobol` in the monospace stack, scrolling within itself rather than the page at narrow widths.
  - **`stepper.js`:** `Stepper.mount` renders Back / Next / Play / Reset buttons and a "step i of n" counter into `container`. It calls `render(steps[i], i)` into a body element and shows `steps[i].note`; Play advances every 900 ms until the last step. `Stepper.verify` compares canonical JSON and, on a mismatch, prepends `<div class="banner-error">This page's model disagrees with its stated answer: …</div>` showing both values.
  - **`index.html`:** a title, one paragraph saying what the pages are for and who they're for, and an ordered list of the four topics. Each topic has a one-sentence description, and links only to pages that exist; later tasks add theirs.

- [ ] **Step 4: Write `fixpoints.html`** with the seven sections from the spec, in order. Its example block:

```json
{"member": "FIXLOOP",
 "program": "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. FIXLOOP.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01  WS-A                 PIC X(4) VALUE 'AAAA'.\n       01  WS-B                 PIC X(4).\n       01  WS-C                 PIC X(4).\n       01  WS-N                 PIC 9(2) VALUE 0.\n       PROCEDURE DIVISION.\n       MAIN-PARA.\n           PERFORM LOOP-PARA UNTIL WS-N > 3.\n           MOVE WS-B TO WS-C.\n           STOP RUN.\n       LOOP-PARA.\n           MOVE WS-A TO WS-B.\n           ADD 1 TO WS-N.\n",
 "expected": {"checks": ["flows"],
   "flows": [["FIXLOOP.WS-A", "FIXLOOP.WS-B"], ["FIXLOOP.WS-B", "FIXLOOP.WS-C"],
             ["FIXLOOP.WS-N", "FIXLOOP.WS-N"]]}}
```

  The page displays `program` in a `pre.cobol` read from this block, not a second copy. Its model, in the page's own `<script>`:
  - **The CFG:** `MAIN-PARA/0` (the PERFORM test), a loop body of `LOOP-PARA/0` and `LOOP-PARA/1` with a back edge to the test, then `MAIN-PARA/1` and `MAIN-PARA/2`.
  - **The state:** for each field, the set of fields whose bytes it may hold.
  - **Transfer:**
    - `MOVE x TO y` sets `y`'s sources to `{x}`;
    - `ADD 1 TO n` makes `n`'s sources `{n}`;
    - a merge unions.
  - **Two runs:** one with a FIFO worklist and one taking the earliest node in reverse postorder. A toggle chooses which one the stepper shows. Each step's `note` says which node was taken, what changed, and what was re-queued.
  - **The final state's flows,** read back as `[source, target]` pairs over the program's fields, go to `Stepper.verify` against `expected.flows`. Both runs must verify, and the page shows the two runs' step counts side by side.
  - **"What goes wrong"** states, without exact numbers beyond these: on a 2,064-node CardDemo program, cobble's change from FIFO to reverse-postorder order cut visits from about 107,000 to about 20,000 with an identical answer. A walk stopped early yields a subset of the flows, never a wrong one.
  - **"In cobble"** links `../../cobble/cobble/dataflow/fixpoint/fixpoint.py` and `../../cobble/cobble/dataflow/fields/state.py`.

- [ ] **Step 5: Run the test.** Expected: 2 passed.
- [ ] **Step 6: Mutation check.** Change `"FIXLOOP.WS-C"` to `"FIXLOOP.WS-D"` in the block: the test fails. Restore. Delete the `id="example"` attribute: the page test fails with "fixpoints.html needs exactly one example block". Restore. Remove the index link: the index test fails. Restore.
- [ ] **Step 7: By hand.** Open `docs/explainers/fixpoints.html` from disk:
  - step through both orders to the end, with no banner;
  - edit one expected flow, reload, see the red banner, then revert;
  - check dark and light schemes, and a 390 px window.
- [ ] **Step 8: README link,** as listed under Files.
- [ ] **Step 9: Gate and commit:** `docs(explainers): the shared stepper and the fixpoints page`.

---

### Task 2: Reaching definitions (`reaching-definitions.html`)

**Files:** Create `docs/explainers/reaching-definitions.html`; modify `docs/explainers/index.html`, `cobble/tests/explainers/test_explainers.py`.

**Interfaces:** Consumes `Stepper.mount` and `Stepper.verify`, and the example block shape (Task 1).

- [ ] **Step 1: Write the page with its example block:**

```json
{"member": "REACHDEF",
 "program": "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. REACHDEF.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01  WS-FLAG              PIC X.\n       01  WS-A                 PIC X(4).\n       01  WS-B                 PIC X(4).\n       01  WS-C                 PIC X(4).\n       PROCEDURE DIVISION.\n       MAIN-PARA.\n           IF WS-FLAG = 'Y'\n               MOVE 'YES ' TO WS-A\n           ELSE\n               MOVE 'NO  ' TO WS-A\n           END-IF.\n           MOVE WS-A TO WS-B.\n           MOVE 'DONE' TO WS-A.\n           MOVE WS-A TO WS-C.\n           STOP RUN.\n",
 "expected": {"checks": ["defs"],
   "defs": [
     {"node": "MAIN-PARA/1", "extent": "WS-A@working_storage[1:5]",
      "definers": ["MAIN-PARA/0.else.0", "MAIN-PARA/0.then.0"]},
     {"node": "MAIN-PARA/3", "extent": "WS-A@working_storage[1:5]",
      "definers": ["MAIN-PARA/2"]}]}}
```

  Its model:
  - The node ids follow cobble's naming, which the page explains: paragraph/statement index, with `.then.n` and `.else.n` for the arms of an `IF`.
  - For each node it tracks the set of definitions of `WS-A` reaching it.
    - **gen:** a write to `WS-A` adds its own node and kills the others, since it covers `WS-A` fully.
    - **merge:** the end of the `IF` unions both arms.
  - Steps go statement by statement. Each `note` names the gen and kill.
  - The final per-read definers go to `Stepper.verify`.
  - "What goes wrong" covers strong versus weak updates (only a certain, full overwrite may kill) and loops that bring a definition back round. It links to the fixpoints page.
  - "In cobble" links `fixpoint.py` (`_definers`) and `side_tables.py` (`defs_row`).

- [ ] **Step 2: Register the page.** Add it to `index.html` and append it to `PAGES` in `test_explainers.py`.
- [ ] **Step 3: Run the test**, the mutation check (reorder the first row's definers, and the test must fail), and the by-hand check as in Task 1.
- [ ] **Step 4: Gate and commit:** `docs(explainers): reaching definitions`.

---

### Task 3: Byte-extent aliasing (`byte-extents.html`)

**Files:** Create `docs/explainers/byte-extents.html`; modify `docs/explainers/index.html`, `cobble/tests/explainers/test_explainers.py`.

- [ ] **Step 1: Write the page with its example block:**

```json
{"member": "BYTEEXT",
 "program": "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. BYTEEXT.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01  REC.\n           05  WS-A             PIC X(4).\n           05  WS-B             PIC X(4).\n       01  WHOLE REDEFINES REC  PIC X(8).\n       01  OUT-A                PIC X(4).\n       01  OUT-B                PIC X(4).\n       01  OUT-ALL              PIC X(8).\n       PROCEDURE DIVISION.\n       MAIN-PARA.\n           MOVE 'AAAABBBB' TO REC.\n           MOVE 'XXXX' TO WS-A.\n           MOVE WS-A TO OUT-A.\n           MOVE WS-B TO OUT-B.\n           MOVE WHOLE TO OUT-ALL.\n           STOP RUN.\n",
 "expected": {"checks": ["flows", "defs"],
   "flows": [["BYTEEXT.LITERAL", "BYTEEXT.REC"], ["BYTEEXT.LITERAL", "BYTEEXT.WS-A"],
             ["BYTEEXT.WHOLE", "BYTEEXT.OUT-ALL"], ["BYTEEXT.WS-A", "BYTEEXT.OUT-A"],
             ["BYTEEXT.WS-B", "BYTEEXT.OUT-B"]],
   "defs": [
     {"node": "MAIN-PARA/2", "extent": "WS-A@working_storage[0:4]",
      "definers": ["MAIN-PARA/0", "MAIN-PARA/1"]},
     {"node": "MAIN-PARA/3", "extent": "WS-B@working_storage[4:8]",
      "definers": ["MAIN-PARA/0"]},
     {"node": "MAIN-PARA/4", "extent": "WHOLE@working_storage[0:8]",
      "definers": ["MAIN-PARA/0", "MAIN-PARA/1"]}]}}
```

  The model draws bytes 0–8 of working storage as a strip labelled with `REC`, `WS-A`, `WS-B` and `WHOLE`. Each write paints the bytes it covers with its node. Each read lists the writes whose painted range overlaps it.
  - **Definitions are kept per write and its range,** as cobble keeps them. A later write removes an earlier definition only when it covers that definition's *whole* range.
  - **Consequence:** `MAIN-PARA/1` writes bytes 0–4 and does not cover `MAIN-PARA/0`'s 0–8. So the read of `WS-A` lists both writes, although only `MAIN-PARA/1` fed it.
  - **How the page teaches it:** "What goes wrong" presents this as the deliberate imprecision it is (Review Focus 4). It is sound, because it never misses a definer, and cheap, because the write would otherwise have to split the group's definition into pieces. The page states it in those terms and shows the precise answer next to cobble's.
  - Final flows and definers go to `Stepper.verify`.
  - "In cobble" links `cobble/cobble/dataflow/fields/extent.py` and `vendor/red-dragon/cobol_memory/field_extent.py` (`may_alias`, `must_cover`).

- [ ] **Step 2: Register the page.** Add it to `index.html` and append it to `PAGES` in `test_explainers.py`.
- [ ] **Step 3: Run the test**, the mutation check (drop `MAIN-PARA/0` from the first row, and the test must fail), and the by-hand check.
- [ ] **Step 4: Gate and commit:** `docs(explainers): byte-extent aliasing`.

---

### Task 4: Value sets and dynamic calls (`value-sets.html`)

**Files:** Create `docs/explainers/value-sets.html`; modify `docs/explainers/index.html`, `cobble/tests/explainers/test_explainers.py`.

- [ ] **Step 1: Write the page with its example block:**

```json
{"member": "VALSETS",
 "program": "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. VALSETS.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01  WS-FLAG              PIC X.\n       01  WS-PGM               PIC X(8).\n       01  WS-OTHER             PIC X(8).\n       PROCEDURE DIVISION.\n       MAIN-PARA.\n           IF WS-FLAG = 'Y'\n               MOVE 'PROGB' TO WS-PGM\n           ELSE\n               MOVE 'PROGC' TO WS-PGM\n           END-IF.\n           CALL WS-PGM.\n           CALL WS-OTHER.\n           STOP RUN.\n",
 "expected": {"checks": ["targets"],
   "targets": [
     {"node": "MAIN-PARA/1", "expression": "WS-PGM",
      "candidates": ["PROGB", "PROGC"], "reasons": []},
     {"node": "MAIN-PARA/2", "expression": "WS-OTHER",
      "candidates": [], "reasons": ["uninitialised"]}]}}
```

  The model tracks, for each field, a value set: a set of byte strings plus a set of reasons the set may be incomplete.
  - A `MOVE` of a literal sets `{literal}` with no reasons.
  - A field never written holds `{}` with reason `uninitialised`.
  - A merge unions both the values and the reasons.
  - At each `CALL`, the candidates are the value set's strings, trimmed of trailing spaces.
  - Steps show `WS-PGM`'s set growing through the `IF`, and each call's resolution.
  - Final targets go to `Stepper.verify`.
  - "What goes wrong" explains:
    - the reasons: `uninitialised`; `over-budget` past 32 values; `incomplete-walk` when a walk stops early;
    - the proven / candidate / unresolved rule: one candidate with no reasons is proven; anything else is a candidate or an unresolved edge.
    - It links back to the fixpoints page for why a stopped walk gives a subset.
  - "In cobble" links `cobble/cobble/dataflow/fields/values.py`, `cobble/cobble/dataflow/fixpoint/targets.py` and `cobble/cobble/build_graph.py` (`_row_target`).

- [ ] **Step 2: Register the page.** Add it to `index.html`, completing the list, and append it to `PAGES` in `test_explainers.py`.
- [ ] **Step 3: Run the test**, the mutation check (change `uninitialised`, and the test must fail), and the by-hand check.
- [ ] **Step 4: Gate (`make test-all` before this last commit) and commit:** `docs(explainers): value sets and dynamic calls`.
