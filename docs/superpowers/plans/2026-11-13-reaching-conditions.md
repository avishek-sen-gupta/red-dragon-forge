# Reaching Conditions Checked by Z3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `cobble-srccfg-query guards` with `cobble-experimental-reaching-conditions`, which lists a node's possible ways (control-dependence chains) checked by Horn/Spacer, with each route test classified.

**Architecture:** Inside `cobble/experimental/horn/`. The state gains outcome marks (last outcome of a test) and entry marks (the call site that last entered a range). A way is enumerated from per-context control dependence, checked with one `reaches` query, and its route tests with two each. The old walk in `srccfg/dataflow.py` and everything only it served is deleted.

**Tech Stack:** Python 3.13, z3-solver (Spacer), networkx, pytest, uv.

**Spec:** `docs/superpowers/specs/cobble/2026-11-13-reaching-conditions-design.md`

## Global Constraints

- The code lives in `cobble/cobble/experimental/horn/`. The `.importlinter` contracts `horn-is-a-leaf`, `z3-only-in-horn` and `horn-not-datalog` stay unchanged.
- The command is `cobble-experimental-reaching-conditions --asg ASG.json --node NODE_ID`.
- A way is dropped only on `UNSAT`. `UNKNOWN` is listed, marked "solver gave up".
- Every Spacer query runs under a 180-second limit, a constant (`QUERY_TIMEOUT_MS = 180_000`), not a flag.
- The way cap is a constant (`MAX_WAYS = 64`). A cut list says so in the output.
- Route-test verdicts and their output labels are exactly `either way`, `if it runs`, and `never runs on this way`.
- Tests inside paragraphs performed on a route are route tests at any depth.
- Run everything from `cobble/` with `uv run --no-sync`, and without `bridge-env.sh`.
- No comments beyond one-line module or class headers. Dataclasses are frozen. No `Any`, no `object`. Pyright is strict.

## Review Focus

1. **A node no route reaches** (dead code, or behind a STOP RUN). Expect "0 ways", not a crash or an empty block. Covered in Task 4.
2. **A test whose atom is not plain** (subscripted, or with reference modification). The encoding constrains nothing for it. Its decision is SAT both ways and it must not raise. Covered in Task 4.
3. **A node inside a range performed from a call site inside another range** (nested PERFORMs). The way carries both call sites and both entry marks. Covered in Task 2.
4. **A node id the program does not have.** The command exits 1 with the id in the error and no traceback. Covered in Task 5.
5. **A test that is both a decision of one way and a route test of another.** Each way classifies it independently. Covered in Task 4.

---

### Task 1: Outcome marks, entry marks, and the query time limit

**Files:**
- Modify: `cobble/cobble/experimental/horn/storage.py`
- Modify: `cobble/cobble/experimental/horn/condition.py`
- Modify: `cobble/cobble/experimental/horn/lower.py`
- Modify: `cobble/cobble/experimental/horn/reaches.py`
- Modify: `cobble/cobble/experimental/horn/solve.py`
- Create: `cobble/cobble/experimental/horn/outcome.py`
- Test: `cobble/tests/experimental/horn/test_lower.py`

**Interfaces:**
- Produces:
  - `class Outcome(Enum)` in `outcome.py`, with values `UNRUN = 0`, `TRUE = 1`, `FALSE = 2`.
  - In `condition.py`:
    - `@dataclass(frozen=True) class Took: test: str; outcome: Outcome`. Here `test` is a TEST node id, and the condition holds when that test's last outcome before the point is `outcome`.
    - `@dataclass(frozen=True) class Entered: range: Context; call: str`. It holds when the last PERFORM into `range` was the node `call`.
  - In `storage_of(...)`: new keyword parameters `outcomes: Sequence[str] = ()` (TEST node ids) and `entries: Sequence[Context] = ()`. `Storage` gains the fields `outcomes: tuple[str, ...]` and `entries: tuple[Context, ...]`, one byte each, laid out after the existing marks. Its accessors are `Storage.outcome(test, state) -> z3.BitVecRef` and `Storage.entry(context, state) -> z3.BitVecRef`.
  - `lower(program, watched=(), marks=(), kept=EVERY_TEST, outcomes=(), entries=())`.
  - `reaches(system, point, conditions: Sequence[Condition | Visited | Took | Entered], clock)`.
  - An entry mark's value is 1 plus the index of the call site in `sorted(PERFORM node ids whose PERFORM edge enters the range)`. It is 0 before any entry.
  - `QUERY_TIMEOUT_MS = 180_000` in `solve.py`, passed to the Fixedpoint as `timeout`.

- [ ] **Step 1: Write the failing tests** in `test_lower.py`, using the file's `_asg`, `_test`, `_perform`, `_move_literal` and `_clock` helpers.

```python
def test_an_outcome_mark_holds_the_last_outcome_of_its_test() -> None:
    # MAIN: IF F = 'Y' MOVE 'x' TO X-OUT.  X-OUT's writer is reached only after F = 'Y' TRUE.
    program = program_of(_asg([("MAIN", [_test("F", "'Y'", [X_OUT])])], FIELDS))
    test = next(n.id for n in program.cfg.nodes if n.kind is NodeKind.TEST)
    writer = next(n.id for n in program.cfg.nodes if "X-OUT" in n.writes)
    system = lower(program, outcomes=(test,))
    ask = lambda o: reaches(system, Point("PROGA", writer), (Took(test, o),), _clock()).answer
    assert (ask(Outcome.TRUE), ask(Outcome.FALSE), ask(Outcome.UNRUN)) == (
        Answer.SAT, Answer.UNSAT, Answer.UNSAT,
    )


def test_an_entry_mark_names_the_call_site_that_entered_the_range() -> None:
    # MAIN: IF F = 'Y' PERFORM SUB ELSE PERFORM SUB.  SUB: IF F = 'Y' MOVE 'x' TO X-OUT.
    # Entered through the ELSE call, F is not 'Y', so SUB's write cannot run.
    program = program_of(_asg(
        [("MAIN", [_if(_ref("F"), "'Y'", [_perform("SUB")], [_perform("SUB")]), STOP]),
         ("SUB", [_test("F", "'Y'", [X_OUT])])],
        FIELDS,
    ))
    then_call, else_call = _calls_by_branch(program)  # the PERFORM on the TRUE edge, then on the FALSE edge
    sub = performed(program.cfg, perform_edge(program.cfg, then_call)[0])
    writer = next(n.id for n in program.cfg.nodes if "X-OUT" in n.writes)
    system = lower(program, entries=(sub,))
    ask = lambda call: reaches(system, Point("PROGA", writer), (Entered(sub, call),), _clock()).answer
    assert (ask(then_call), ask(else_call)) == (Answer.SAT, Answer.UNSAT)
```

`_calls_by_branch` is a test helper. It follows the MAIN TEST node's TRUE and FALSE edges to the first PERFORM node on each. The ids must not be hard-coded.

- [ ] **Step 2: Run, and verify both fail.**
Run: `uv run --no-sync python -m pytest tests/experimental/horn/test_lower.py -k "outcome_mark or entry_mark" -v`
Expected: FAIL. `Took` and `Entered` can't be imported.

- [ ] **Step 3: Implement.**
  - **Outcome marks:** in `_extras`, a TRUE or FALSE edge out of a test listed in `storage.outcomes` sets that test's byte to 1 or 2. Every other edge keeps it.
  - **Entry marks:** in `_call`, the rule entering a range listed in `storage.entries` sets its byte to the call site's value. The callee's entry state and current state are both the caller's state with that one byte changed, so the summary carries it out.
  - **`reaches`:** `_asked` compares the byte with the outcome's value or the call site's value.
  - **`_check_marks`:** extend it to raise `ValueError` for an outcome that isn't a TEST node id, and for an entry that isn't one of `contexts(cfg)`.
  - **`solve`:** sets `timeout=QUERY_TIMEOUT_MS`. There is no unit test for the timeout. A query that deterministically exceeds a limit is not available, and the limit is a constant by the spec.

- [ ] **Step 4: Run the Horn suite, and verify it passes.**
Run: `uv run --no-sync python -m pytest tests/experimental/horn -v`
Expected: PASS, including the existing tests.

- [ ] **Step 5: Commit** together with Task 2. Each hooked commit takes minutes, so commits are batched per the project's memory "one commit per feature". The batch commit is in Task 4.

---

### Task 2: Ways, from control dependence

**Files:**
- Create: `cobble/cobble/experimental/horn/followed.py`
- Create: `cobble/cobble/experimental/horn/ways.py`
- Modify: `cobble/cobble/experimental/horn/lower.py`, so that `_never_back` and the never-PGMIDERR drop call `followed`.
- Test: `cobble/tests/experimental/horn/test_ways.py`

**Interfaces:**
- Consumes: `Outcome` (Task 1), and `Context`, `contexts`, `steps`, `members`, `perform_edge`, `performed` from `context.py`.
- Produces:
  - `followed(program: Program, edge: Edge) -> bool` in `followed.py`. It returns False for the FLOW edge past a PERFORM that cannot come back (today's `_never_back` rule) and for an edge into a PGMIDERR-only handler from a command that `never_pgmiderr` says cannot raise it. `lower` keeps its conversation-only `_installed` guard as it is.
  - In `ways.py`:
    - `@dataclass(frozen=True) class Decision: test: str; outcome: Outcome`
    - `@dataclass(frozen=True) class Way: decisions: tuple[Decision, ...]; calls: tuple[tuple[Context, str], ...]`. `calls` lists each range the way enters and the PERFORM node it enters through, outermost first.
    - `@dataclass(frozen=True) class Ways: ways: tuple[Way, ...]; cut: bool`
    - `MAX_WAYS = 64`
    - `ways_to(program: Program, node: str) -> Ways`

Control dependence is computed per context with networkx post-dominators. The graph is reversed, and a synthetic exit is joined from the context's end and from every node with no followed successor. Edges are `steps(cfg, context, n)` filtered by `followed`, plus the PERFORM-to-resume pair that `members` adds. A way is a chain of `(test, outcome)` from the context entry to `node`. For a node in a range, each call site's way is prefixed, one way per call site, recursively.

There is one extra rule for a PERFORM on the chain whose range has a node that ends the task. The decisions in that range that its end is control dependent on are inserted after the PERFORM.

Enumeration stops at `MAX_WAYS` with `cut=True`.

- [ ] **Step 1: Write the failing tests**, one per behaviour. Each asserts the full `Ways` value, with node ids looked up by what the node writes.
  - `test_a_rejoining_if_is_not_a_decision`: `IF F='Y' MOVE..` then a write to X-OUT after the rejoin gives `Ways((Way((), ()),), False)`.
  - `test_nested_ifs_give_one_way_through_both_decisions`: `IF F='Y' IF G='Z' X_OUT` gives one way, `(F-test TRUE, G-test TRUE)`.
  - `test_a_range_performed_from_two_call_sites_gives_two_ways`: two ways, which differ in `calls` and in the decision guarding each call.
  - `test_nested_performs_carry_both_call_sites` (Review Focus 3): `calls` has two entries, outermost first.
  - `test_a_perform_that_can_end_the_task_adds_its_return_decisions`: `SUB: IF F='Y' STOP RUN.` and `MAIN: PERFORM SUB, MOVE 'x' TO X-OUT` give one way, `(F-test FALSE)`.
  - `test_the_cap_cuts_and_says_so`: a program with 7 sequential `IF`s, each `GO TO`-ing into the node's paragraph, gives 128 > 64 chains. The result is `len(ways)==64` and `cut is True`.
  - `test_an_unreachable_node_has_no_ways` (Review Focus 1): a write after `STOP RUN` gives `Ways((), False)`.

- [ ] **Step 2: Run, and verify they fail.**
Run: `uv run --no-sync python -m pytest tests/experimental/horn/test_ways.py -v`
Expected: FAIL. `ways_to` can't be imported.

- [ ] **Step 3: Implement `followed`, then `ways_to`.** Switch `lower` to `followed`, and change nothing else in its behaviour.

- [ ] **Step 4: Run, and verify everything passes.**
Run: `uv run --no-sync python -m pytest tests/experimental/horn -v`
Expected: PASS.

---

### Task 3: Route tests

**Files:**
- Create: `cobble/cobble/experimental/horn/route.py`
- Test: `cobble/tests/experimental/horn/test_ways.py`

**Interfaces:**
- Consumes: `Way`, `Decision`, `ways_to` (Task 2), and `followed`.
- Produces: `route_tests(program: Program, way: Way, node: str) -> tuple[str, ...]`. It returns the TEST node ids on some followed route between consecutive points of the way: the context entry, each decision's target, each call site, and `node`. Tests inside ranges performed on those routes are included at any depth. The way's own decisions are excluded. The result is sorted by node id.

- [ ] **Step 1: Write the failing tests.**
  - `test_route_tests_include_a_rejoining_if`: the F-test of a rejoining `IF` before the node gives `("<F-test id>",)`.
  - `test_route_tests_reach_into_performed_paragraphs`: `MAIN: PERFORM SUB, X_OUT` with `SUB: IF G='Z' MOVE...` gives the G-test.
  - `test_route_tests_exclude_the_ways_decisions`.

- [ ] **Step 2: Run, and verify they fail.**
Run: `uv run --no-sync python -m pytest tests/experimental/horn/test_ways.py -k route -v`
Expected: FAIL. The import of `route_tests` fails.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run, and verify they pass.** Same command. Expected: PASS.

---

### Task 4: Checking ways and classifying route tests

**Files:**
- Create: `cobble/cobble/experimental/horn/reaching_conditions.py`
- Test: `cobble/tests/experimental/horn/test_reaching_conditions.py`

**Interfaces:**
- Consumes: Tasks 1–3, `leading_to`, `lower`, `reaches`.
- Produces:
  - `class RouteVerdict(Enum)`: `EITHER_WAY`, `IF_IT_RUNS`, `NEVER_RUNS`.
  - `@dataclass(frozen=True) class RouteTest: test: str; verdict: RouteVerdict; outcome: Outcome`. `outcome` is the outcome the test takes if it runs, and is `Outcome.UNRUN` unless the verdict is `IF_IT_RUNS`.
  - `@dataclass(frozen=True) class CheckedWay: way: Way; answer: Answer; route: tuple[RouteTest, ...]`
  - `@dataclass(frozen=True) class Report: program: str; node: str; ways: tuple[CheckedWay, ...]; dropped: int; cut: bool`
  - `reaching_conditions(program: Program, node: str, clock: Callable[[], float]) -> Report`

For each way:
- lower with `kept=leading_to(cfg, node)`, `outcomes` set to the way's decision tests plus its route tests, and `entries` set to the way's ranges;
- ask `reaches` at `node` with `Took` for each decision and `Entered` for each call;
- drop the way on `UNSAT`, and count it in `dropped`;
- for a kept way, ask each route test twice, adding `Took(t, TRUE)` and then `Took(t, FALSE)`, and classify the test:
  - both answers not `UNSAT`: `EITHER_WAY`;
  - exactly one `UNSAT`: `IF_IT_RUNS`, with the other outcome;
  - both `UNSAT`: `NEVER_RUNS`.

`reaching_conditions` raises `ValueError(f"{node} is not a node of {program}")` for an unknown node id.

- [ ] **Step 1: Write the failing tests**, one per behaviour. Each asserts the whole `Report`, built from ids looked up by writes.
  - `test_a_way_with_contradictory_tests_is_dropped`: `IF F='A' IF F='B' X_OUT` gives `ways=()` and `dropped=1`.
  - `test_a_flag_set_in_a_performed_paragraph_decides_a_later_test`:
    - `MAIN: PERFORM CHK, IF G='N' X_OUT`, with `CHK: IF F=SPACES MOVE 'Y' TO G`;
    - `G` has `VALUE 'N'`, which `lower` ignores, so the program writes `MOVE 'N' TO G` first;
    - expected: one way, `(G-test TRUE)`, with route `(RouteTest(F-test, IF_IT_RUNS, FALSE),)`.
  - `test_a_rejoining_if_on_another_field_is_either_way`.
  - `test_an_if_repeated_on_an_unchanged_field_is_if_it_runs`: `IF F='A' X ... END-IF, IF F='A' X_OUT`. The node is the second write; the first test gives `IF_IT_RUNS TRUE`.
  - `test_a_test_nested_in_an_impossible_branch_never_runs`.
  - `test_a_loops_last_outcome_decides`: `PERFORM UNTIL F='Y'` sets F inside, then `X_OUT` after the loop. The loop test's decision is TRUE and the way is SAT.
  - `test_a_test_on_an_unplain_atom_is_either_way` (Review Focus 2): a subscripted test gives `EITHER_WAY` and doesn't raise.
  - `test_each_way_classifies_a_shared_test_independently` (Review Focus 5).

- [ ] **Step 2: Run, and verify they fail.**
Run: `uv run --no-sync python -m pytest tests/experimental/horn/test_reaching_conditions.py -v`
Expected: FAIL on the import.

- [ ] **Step 3: Implement `reaching_conditions`.** Log one line per query at INFO: the way's index, the query, the answer and the seconds.

- [ ] **Step 4: Run the Horn suite, and verify it passes.**
Run: `uv run --no-sync python -m pytest tests/experimental/horn -v`
Expected: PASS.

- [ ] **Step 5: Commit Tasks 1–4** as one hooked commit, `feat(cobble): reaching conditions checked by Z3 (marks, ways, route tests)`. Add `.talismanrc` entries for incidental flags, which have standing approval. Don't use `--no-verify`.

---

### Task 5: The command, the CardDemo gates, and the Horn docs

**Files:**
- Create: `cobble/cobble/experimental/horn/reaching_conditions_cli.py`
- Modify: `cobble/pyproject.toml`, adding `cobble-experimental-reaching-conditions = "cobble.experimental.horn.reaching_conditions_cli:main"`
- Test: `cobble/tests/experimental/horn/test_reaching_conditions_cli.py`
- Test: `cobble/tests/carddemo/test_reaching_conditions.py`
- Modify: `docs/reference/cobble/horn.md`, `docs/reference/cobble/config.md`, `cobble/skills/cobble-artifacts/SKILL.md`, and the untracked `.claude/skills/cobble-artifacts/SKILL.md` identically.

**Interfaces:**
- Consumes: `reaching_conditions`, `Report` (Task 4), and `first_program_at` (`cobble/parsing/asg_cache.py`).
- Produces:
  - `main(argv: Sequence[str] = ()) -> int`, with the arguments `--asg PATH` and `--node ID`.
  - `render(program: Program, report: Report) -> tuple[str, ...]`, the text lines in the spec's Output format.

A test is written as `f"{atom.text} ({span.line_start})"`, and a decision as that text followed by ` TRUE` or ` FALSE`.

The lines are:
- `PROG node (line): N ways`
- `  way K: ...`, with ` (solver gave up)` appended on `UNKNOWN`
- `    either way: ...`, `    if it runs: <test> OUTCOME, ...` and `    never runs on this way: ...`, each printed only when not empty
- `  dropped: N ways Z3 proved impossible`, printed when N > 0
- `  (cut at 64 ways: this list is incomplete)`, printed when cut

- [ ] **Step 1: Write the failing tests.**
  - `test_render_prints_every_section`: an exact list of lines for a hand-built `Report`.
  - `test_an_unknown_node_exits_1_naming_it` (Review Focus 4): write a synthetic ASG to `tmp_path` and run `main(["--asg", p, "--node", "NOPE"]) == 1`. With `caplog`, check that the message equals `"NOPE is not a node of PROGA"`.
  - CardDemo gate `test_signon_reaches_the_user_menu_one_way` in `tests/carddemo/test_reaching_conditions.py`, using `carddemo` and the `_program` pattern from `test_horn.py`. The node is the XCTL to `COMEN01C`, found by the node's span line 236 in COSGN00C. Expected, read from `COSGN00C.cbl`:
    - one way, with `dropped >= 0`;
    - decisions by `(span line, outcome)`, in order: `(79, FALSE)` for EIBCALEN = 0, the EIBAID WHEN DFHENTER test `TRUE`, `(138, FALSE)` for ERR-FLG-ON, the WS-RESP-CD WHEN 0 test `TRUE`, `(221, TRUE)` for SEC-USR-PWD = WS-USER-PWD, and `(230, FALSE)` for CDEMO-USRTYP-ADMIN;
    - the four blank-input tests at 118 and 123 are `IF_IT_RUNS FALSE` in its route. A blank input sets WS-ERR-FLG to 'Y', which the 138 decision excludes.

    The EVALUATE tests' span lines (DFHENTER, and WHEN 0) are taken from the CFG node, which may be the `WHEN` line or the `EVALUATE` line. Assert the line the CFG gives, and record it in the ledger.

    Mark it `slow` if it takes more than a minute.
  - `test_signon_reaches_the_admin_menu_one_way`: the same, with the XCTL to `COADM01C` at line 231 and `(230, TRUE)`.

- [ ] **Step 2: Run, and verify they fail.**
Run: `uv run --no-sync python -m pytest tests/experimental/horn/test_reaching_conditions_cli.py tests/carddemo/test_reaching_conditions.py -v`
Expected: FAIL on the import.

- [ ] **Step 3: Implement** `main` and `render`, and add the pyproject script. Run `uv sync --all-packages` so the script installs.

- [ ] **Step 4: Run, and verify they pass.** Same command. Expected: PASS, with any slow gate run explicitly.

- [ ] **Step 5: Update the docs.**
  - `horn.md`: outcome marks, entry marks, `Took`, `Entered`, the 180 s limit, and the command, with its output format and route verdicts.
  - `config.md`: add the command to the table.
  - Skill: replace the `guards` line with `cobble-experimental-reaching-conditions --asg <ASG> --node <ID>`, plus one line on reading its output.

- [ ] **Step 6: Commit** `feat(cobble): cobble-experimental-reaching-conditions command and CardDemo gates`.

---

### Task 6: Delete the old walk and repoint the presentation

**Files:**
- Modify: `cobble/cobble/dataflow/srccfg/dataflow.py`. Delete `reaching_conditions`, `Reaching`, `Walk`, `_Frame`, `_Sweep`, `_Spread`, `guards_of`, `guard_text`, `guard_set`, `MAX_PATHS`, `Guard`, and every private helper only they reach. Keep `with_handler_edges`, `writers_of`, `readers_of`, `base_field`, `condition_operands`, `entry_of`, and anything else still imported elsewhere.
- Modify: `cobble/cobble/dataflow/srccfg/query.py`:
  - remove the `guards` query, `GuardLines`, `_guard_lines`, `_guard_texts`, `guards_report`, `--max-paths`, and the CAP, SUBSET and RESUMED notes;
  - `provenance` prints `{node_id} {verb}` with no `when` clause;
  - drop the control-dependency block (`_guard_operands`, `_unresolved_guard`).
- Modify: `cobble/cobble/dataflow/srccfg/coassign.py`: remove `Tier.SAME_GUARD`, `guard_signature`, and the `reaching` parameter of `co_assigned` and of its helpers.
- Delete: `cobble/tests/dataflow/srccfg/test_reaching.py`.
- Modify tests:
  - `test_query.py` and `test_coassign.py`: drop the guards cases and update the expected provenance lines;
  - `test_desugar_terminator.py`: its 11 guard reads become edge assertions. "Reached by nothing" means no edge targets the node. "Does not reach its own end" means the end is not among `networkx.descendants` of the paragraph's label over `cfg.edges`;
  - `test_desugar_exit.py`: likewise;
  - `test_acceptance.py`: delete `test_reaching_conditions_terminate_on_every_member`, and rewrite `test_most_members_have_at_least_one_guarded_assignment` as "most members have an ASSIGN node with a TEST ancestor" over edges.
- Modify: `docs/reference/cobble/srccfg.md`, and `docs/presentation/` (`capture/srccfg.sh`, `artifacts/srccfg/guards-COSGN00C-xctl.txt`, which is renamed to `reaching-conditions-COSGN00C-xctl.txt`, `artifacts/srccfg/FACTS.md`, and the slide at `index.html` lines ~330–395).

**Interfaces:**
- Consumes: the command from Task 5.
- Produces: `co_assigned(cfg: Cfg, field: str, min_tier: Tier = Tier.SAME_PARAGRAPH) -> tuple[Candidate, ...]`.

- [ ] **Step 1: Rewrite the terminator, exit and acceptance assertions** against edges first, while the old walk still exists. Run them, and verify they pass on the current code.
Run: `uv run --no-sync python -m pytest tests/dataflow/srccfg/test_desugar_terminator.py tests/dataflow/srccfg/test_desugar_exit.py tests/dataflow/srccfg/test_acceptance.py -v`
Expected: PASS. The tests are now independent of the walk.

- [ ] **Step 2: Delete the walk and its consumers' guard code**, as listed above. Update `test_query.py` and `test_coassign.py` to the new outputs and signature.

- [ ] **Step 3: Run the srccfg suite, pyright and import-linter.**
Run: `uv run --no-sync python -m pytest tests/dataflow/srccfg -q && cd .. && uv run pyright && uv run lint-imports`
Expected: PASS, with 0 pyright errors and all contracts kept.
Then `rg -n "reaching_conditions|guards_of|guard_text|guard_set|srccfg-query guards" cobble ../docs ../cobble/skills` should list no stale reference. The new Horn module and the dated specs and plans are allowed.

- [ ] **Step 4: Repoint the presentation.**
  - In `capture/srccfg.sh`, replace the `guards` calls with the new command on the two sign-on XCTL nodes, reading the ASG from `cobble/out-parsed`.
  - Run the script.
  - Rewrite the slide text and the `FACTS.md` entry from the captured output only.
  - Check the slide page in Chromium, at 1280px and in light mode, with a scratchpad Playwright script, so you don't have to look for breakage yourself.

- [ ] **Step 5: Update `srccfg.md`:** remove `guards`, and describe `provenance` without conditions and `coassign` without the guard tier.

- [ ] **Step 6: Commit** `refactor(cobble): remove the unchecked reaching-conditions walk` as one hooked commit.
