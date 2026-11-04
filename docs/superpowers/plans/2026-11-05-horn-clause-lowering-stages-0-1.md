# Horn clause lowering, stages 0 and 1: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lower one COBOL program's CFG to constrained Horn clauses, then answer "can this point
be reached with these field values" with Z3's Spacer. The encoding covers control flow and test
atoms (stage 0), then flag assignments (stage 1). Each stage is gated by CardDemo sign-on
questions.

**Architecture:** A new package, `cobble/experimental/horn/`. It reads one program's ASG, which
gives the CFG through `program_cfg`, the statements through `statement_index` and the 88-levels
through `condition_index`. It also reads that program's `extents.jsonl` rows. From these it
builds z3 Horn rules:
- one relation per (context, node), where a context is the top level or one PERFORM range;
- one summary relation per range, so PERFORM returns match.

A goal is a point plus field conditions. The answer is `sat`, `unsat` or `unknown`.

**Tech stack:** Python 3.13, the `z3-solver` package (the user's choice, 2026-11-05), pytest,
and cobble's srccfg and extents readers.

**Spec:** `docs/superpowers/specs/cobble/2026-11-04-horn-clause-lowering-design.md`

## Global Constraints

- The lowering neither reads the Datalog `.facts` files or rules nor needs the Datalog stage to
  have run. An `.importlinter` contract forbids `cobble.experimental.horn` from importing
  `cobble.experimental.datalog`.
- Anything not encoded exactly becomes an unconstrained value, so `unsat` stays valid. This
  covers an unresolved atom, an untracked field, a non-literal write, a computed subscript and
  every input.
- `unknown` is a gate failure, reported as `unknown`.
- Each gate question's answer comes from the CardDemo source, cited by file and line in the
  test's docstring, and is written before the code that answers it.
- No execution, and no red-dragon IR: `cobble-no-interpreter` stands.
- Repo rules: pyright strict with zero errors, python-fp-lint, Black, no comments except
  one-line module and class headers, frozen dataclasses, no `None` defaults, no `Any`.
- Hooked commits only, never `--no-verify`, and no attribution trailers. One commit per stage
  (Tasks 1–4, then Task 5).

## Review Focus

1. **A write to a group that contains a tracked flag must free the flag.** `MOVE X TO REC`,
   where `REC` holds the flag, leaves the flag unknown. Test: Task 3,
   `test_a_group_write_frees_the_flags_inside_it`.
2. **A paragraph PERFORMed from two places returns to the place that called it.** Test:
   Task 3, `test_a_perform_returns_only_to_its_own_caller`.
3. **Inside a `PERFORM A THRU B` range, control falls from A into B but does not fall out of
   B's end.** Test: Task 3, `test_a_thru_range_falls_through_inside_and_stops_at_its_end`.
4. **A name declared twice is not tracked.** Its tests are unconstrained, so the answer stays
   sound. Test: Task 3, `test_a_name_declared_twice_is_not_tracked`.
5. **A GO TO out of a performed range never returns.** Test: Task 3,
   `test_a_goto_out_of_a_range_does_not_return_to_the_perform`.

---

### Task 1: `guards` names the program in each block

**Files:**
- Modify: `cobble/cobble/dataflow/srccfg/query.py` (`guards_report`, the heading line)
- Modify: `cobble/tests/dataflow/srccfg/test_query.py`
  (`test_the_guards_report_prints_one_line_per_path`)
- Modify: `docs/reference/cobble/srccfg.md` (the `guards` output description)

**Interfaces:** Produces the heading `f"{cfg.program} {node_id}: {n} path(s)"`. Nothing
downstream parses it.

- [ ] **Step 1:** In `test_the_guards_report_prints_one_line_per_path`, change the expected
  first line to start with `PROGA ` (the synthetic program's id) before the node id.
- [ ] **Step 2:** Run
  `cd cobble && uv run --no-sync pytest tests/dataflow/srccfg/test_query.py -q`.
  Expected: that test fails on the heading.
- [ ] **Step 3:** Prefix the heading in `guards_report` with `cfg.program`.
- [ ] **Step 4:** Re-run the step 2 command. Expected: pass.
- [ ] **Step 5:** Update `srccfg.md` to say that each block is headed by its program, and that
  a CFG file holds every program the seed reaches.

### Task 2: the z3 dependency, the package, and its boundary

**Files:**
- Modify: `cobble/pyproject.toml` (add `"z3-solver>=4.13"` to `dependencies`), then run
  `uv lock`
- Modify: `.importlinter` (new contract)
- Create: `cobble/cobble/experimental/horn/__init__.py`
- Create: `cobble/cobble/experimental/horn/answer.py`
- Create: `cobble/cobble/experimental/horn/verdict.py`
- Create: `cobble/cobble/experimental/horn/solve.py`
- Test: `cobble/tests/experimental/horn/test_solve.py`

**Interfaces:**
- Produces `class Answer(Enum)` with members `SAT`, `UNSAT` and `UNKNOWN`.
- Produces `@dataclass(frozen=True) class Verdict` with fields `answer: Answer` and
  `seconds: float`.
- Produces `def solve(rules: Sequence[z3.BoolRef], relations: Sequence[z3.FuncDeclRef], goal:
  z3.BoolRef, clock: Callable[[], float]) -> Verdict`. It runs a
  `z3.Fixedpoint()` with `engine="spacer"`, registers the relations, adds the rules, and
  queries the goal. z3 `sat` means the goal is reachable; it maps to `Answer.SAT`.

- [ ] **Step 1: Write the failing tests.** Both use the loop from the spec discussion:
  `at_loop(0)`, then `at_loop(n+1) ← at_loop(n) ∧ n < 10`, then
  `at_w(n) ← at_loop(n) ∧ n >= 10`. A fake clock returns 1.0 and then 3.5.
  - `test_an_unreachable_goal_is_unsat`: the goal `at_w(n) ∧ n != 10` gives
    `Verdict(Answer.UNSAT, 2.5)`.
  - `test_a_reachable_goal_is_sat`: the goal `at_w(n) ∧ n == 10` gives
    `Verdict(Answer.SAT, 2.5)`.
- [ ] **Step 2:** Run `cd cobble && uv run --no-sync pytest tests/experimental/horn -q`.
  Expected: an import error.
- [ ] **Step 3:** Add the dependency, the package, `Answer`, `Verdict` and `solve`. Add this
  contract to `.importlinter`:
  ```
  [importlinter:contract:horn-not-datalog]
  name = The Horn lowering does not read the Datalog export
  type = forbidden
  source_modules =
      cobble.experimental.horn
  forbidden_modules =
      cobble.experimental.datalog
  ```
- [ ] **Step 4:** Run `uv run --no-sync pyright cobble/cobble/experimental/horn` from the repo
  root. Expected: 0 errors.
  - **Stop and consult the user** if z3's types produce errors. Do not add ignores.
- [ ] **Step 5:** Re-run the step 2 command and `uv run --no-sync lint-imports`. Expected:
  both pass.

### Task 3: stage 0, lowering control flow and test atoms

**Files:**
- Create: `cobble/cobble/experimental/horn/point.py`
- Create: `cobble/cobble/experimental/horn/tracked.py`
- Create: `cobble/cobble/experimental/horn/program.py`
- Create: `cobble/cobble/experimental/horn/context.py`
- Create: `cobble/cobble/experimental/horn/atoms.py`
- Create: `cobble/cobble/experimental/horn/lower.py`
- Create: `cobble/cobble/experimental/horn/condition.py`
- Create: `cobble/cobble/experimental/horn/reaches.py`
- Test: `cobble/tests/experimental/horn/test_lower.py`, using the `asg_of` and `program_of`
  fixtures copied from `cobble/tests/dataflow/srccfg/conftest.py`. The synthetic programs
  supply hand-written `ExtentLine` rows.

**Interfaces:**
- `@dataclass(frozen=True) class Point`: `program: str`, `node: str`.
- `@dataclass(frozen=True) class Tracked`: `name: str`, `length: int`, `extent: FieldExtent`.
- `def tracked_fields(cfg: Cfg, extents: Sequence[ExtentLine]) -> tuple[Tracked, ...]`.
- `@dataclass(frozen=True) class Program`: `cfg: Cfg`,
  `statements: Mapping[str, CobolStatementType]`, `conditions: Mapping[str, EightyEight]`,
  `extents: tuple[ExtentLine, ...]`.
- `def program_of(asg: CobolASG, extents: Sequence[ExtentLine]) -> Program`. It builds the CFG
  with `program_cfg`, then takes `statement_index` and `condition_index`, and keeps only the
  `extents` rows of `asg`'s program.
- `@dataclass(frozen=True) class HornSystem`: `rules: tuple[z3.BoolRef, ...]`,
  `relations: tuple[z3.FuncDeclRef, ...]`, `at: Mapping[Point, tuple[z3.FuncDeclRef, ...]]`
  (one relation per context the node is in), `fields: tuple[Tracked, ...]`.
- `def lower(program: Program) -> HornSystem`.
- `class Op(Enum)`: `EQ`, `NE`. `@dataclass(frozen=True) class Condition`: `field: str`,
  `op: Op`, `value: str`. The value is written as COBOL writes it: `"'A'"`, `"SPACES"`,
  `"LOW-VALUES"`.
- `def reaches(system: HornSystem, point: Point, conditions: Sequence[Condition], clock:
  Callable[[], float]) -> Verdict`.

**Encoding (the algorithm, which the signatures don't determine):**
- **A tracked field** is a name with exactly one extent whose pic starts with `X` and whose
  usage is `DISPLAY`, appearing on either side of an `==` or `!=` atom. Its value is a z3
  `String` of length `length`.
- **An atom is encoded exactly** when its op is `==` or `!=`, its left side is tracked, and
  its right side is one of these:
  - a quoted literal no longer than the field, padded right with spaces;
  - `SPACE` or `SPACES`, giving `length` spaces;
  - `LOW-VALUE` or `LOW-VALUES`, giving `length` × `\x00`;
  - `HIGH-VALUE` or `HIGH-VALUES`, giving `length` × `\xff`;
  - a tracked field of the same length.

  Any other atom, unresolved atoms included, is a fresh boolean per edge.
- **A state** is the tuple of tracked values. Top-level relations take the current state. A
  range's relations take (entry state, current state).
- **Contexts.** The top level, plus one context per distinct `(PERFORM label target, node
  range_end)` seen on a PERFORM node. Each context's edges are the ones reachable from its
  entry, using the rules below. The top level's entry is `cfg.entry`, with a free initial
  state.
- **FLOW, FALLTHRU, GOTO, TRUE and FALSE edges `u → v`** give
  `at(ctx, v)(e, s') ← at(ctx, u)(e, s) ∧ effect_u(s, s') ∧ guard`. The guard is the atom
  for TRUE, its negation for FALSE, and true otherwise.
  - In stage 0, `effect_u` frees every tracked field whose extent overlaps any extent of a name
    in `u.writes`, and copies the rest. A written name with no extent row frees nothing.
- **RETURN edges** are never followed.
- **A FALLTHRU edge out of a range context's `range_end` node** is not followed in that
  context.
- **A PERFORM node `u`** whose PERFORM edge goes to label `L`, with `range_end` `E` and
  `resume` `R`, gives three clauses, with `C = (L, E)`:
  - `at(C, L)(s, s) ← at(ctx, u)(e, s)`;
  - `sum(C)(s, t) ← at(C, E)(s, t)`;
  - `at(ctx, R)(e, t) ← at(ctx, u)(e, s) ∧ sum(C)(s, t)`, only when `R` is non-empty.

  `u`'s other out-edges are followed as ordinary edges.
- **A node with no out-edges ends the task.** XCTL and CICS RETURN end in a `#dispatch` node
  with no successors.
- **`reaches`** adds `goal ← at(ctx, node)(…, s) ∧ conditions(s)` for every context the node is
  in. The conditions are encoded with the atom rules; a condition on an untracked field is
  refused with `ValueError`. Then it solves for `goal`.

- [ ] **Step 1: Write the failing tests**, one per behaviour, each asserting a whole `Verdict`
  answer.
  - `test_a_test_constrains_the_values_after_it`: `IF F = 'Y' … node X`. `reaches(X, F = 'N')`
    gives `UNSAT`, and `reaches(X, F = 'Y')` gives `SAT`.
  - `test_contradictory_tests_make_a_point_unreachable`: `IF F = 'Y'` nested inside
    `IF F = 'N'`. The inner node gives `UNSAT`.
  - `test_a_write_frees_the_field_it_overlaps`: `IF F = 'Y'`, then `MOVE G TO F`, then X.
    `reaches(X, F = 'N')` gives `SAT`.
  - `test_a_group_write_frees_the_flags_inside_it` (Review Focus 1).
  - `test_a_perform_returns_only_to_its_own_caller` (Review Focus 2). P tests F and does
    nothing else. It is performed after `IF F = 'Y'` at A and after `IF F = 'N'` at B. Asking
    for B's resume with `F = 'Y'` gives `UNSAT`.
  - `test_a_thru_range_falls_through_inside_and_stops_at_its_end` (Review Focus 3).
  - `test_a_name_declared_twice_is_not_tracked` (Review Focus 4). `reaches` on that name
    raises `ValueError`. A point after `IF D = 'Y'` with contradictory tests on D stays `SAT`.
  - `test_a_goto_out_of_a_range_does_not_return_to_the_perform` (Review Focus 5).
- [ ] **Step 2:** Run `cd cobble && uv run --no-sync pytest tests/experimental/horn -q`.
  Expected: failures on the missing modules.
- [ ] **Step 3:** Implement the modules to the interfaces and the encoding above.
- [ ] **Step 4:** Re-run the step 2 command. Expected: all pass.
- [ ] **Step 5:** Mutation check. Break the code in two ways and re-run, each time:
  - follow RETURN edges;
  - drop the frame freeing.

  Each break must make at least one test fail. Then restore.

### Task 4: the stage 0 gate on CardDemo, and the docs

**Files:**
- Modify: `cobble/tests/carddemo/conftest.py` (`CardDemoRun` gains `asg: Path` and
  `cobol: Path`, set from the fixture's `asg` and `config.cobol_dir`)
- Create: `cobble/tests/carddemo/test_horn.py`
- Create: `docs/reference/cobble/horn.md`
- Modify: `docs/README.md` (index line), `docs/reference/cobble/datalog.md` (one line: the Horn
  lowering does not read this export)

**Interfaces:** Consumes Task 3's `program_of`, `lower`, `reaches`, `Point` and `Condition`.
Loads the ASG with `first_program_at(cache_path(run.asg, run.cobol / "COSGN00C.cbl"))` inside
`cached_asg_dialect_parsers_registered()`. Reads the extents with
`ExtentLine.model_validate_json` over `run.extents`.

The gate questions, each answered from `vendor/carddemo/app/cbl/COSGN00C.cbl` before running.
Each test's docstring quotes the lines:

| test | point | conditions | answer | source |
|---|---|---|---|---|
| `test_signon_can_transfer_to_the_user_menu` | `READ-USER-SEC-FILE/1.when.0.0.then.5.else.0` | none | `SAT` | :230, :236–237 |
| `test_signon_can_transfer_to_the_admin_menu` | `READ-USER-SEC-FILE/1.when.0.0.then.5.then.0` | none | `SAT` | :230–232 |
| `test_signon_never_sends_an_admin_to_the_user_menu` | the user-menu XCTL | `CDEMO-USER-TYPE == 'A'` | `UNSAT` | :227, :230 |
| `test_signon_never_sends_a_user_to_the_admin_menu` | the admin-menu XCTL | `CDEMO-USER-TYPE != 'A'` | `UNSAT` | :227, :230 |

- [ ] **Step 1:** Write the four tests. Each also logs `verdict.seconds` at INFO.
- [ ] **Step 2:** Run
  `cd cobble && . ../bridge-env.sh && uv run --no-sync pytest tests/carddemo/test_horn.py -q --log-cli-level=INFO`.
  Expected: all four pass, with their times logged.
  - **Stop and consult the user** on any `UNKNOWN`, any failure, or a time over 60 s. This is
    the spike's measurement.
- [ ] **Step 3:** Write `horn.md`. It covers:
  - what the lowering reads, and that it does not read the Datalog export;
  - the encoding rules from Task 3 and what becomes unconstrained;
  - the three answers;
  - how to ask a question (`reaches`);
  - no test counts.
- [ ] **Step 4:** Record each gate's answer and time under "Results" at the end of this plan.
- [ ] **Step 5:** Commit stage 0: Tasks 1–4, the corrected spec, and this plan. Use the message
  `feat(cobble): Horn clause lowering, stage 0 -- control flow and test atoms`. Then push.

### Task 5: stage 1, flag assignments

**Files:**
- Create: `cobble/cobble/experimental/horn/effects.py`
- Modify: `cobble/cobble/experimental/horn/lower.py` (use the effects in place of
  free-only effects)
- Modify: `cobble/tests/experimental/horn/test_lower.py`
- Modify: `cobble/tests/carddemo/test_horn.py`
- Modify: `docs/reference/cobble/horn.md`

**Interfaces:**
- `class Exact` (frozen): `field: str`, `value: str`.
- `def exact_writes(node: Node, statement: CobolStatementType, conditions: Mapping[str,
  EightyEight], fields: Sequence[Tracked]) -> tuple[Exact, ...]`. It returns the assignments
  stage 1 encodes exactly at that node. Every other write the node lists is still freed by
  overlap.

Exact cases, and nothing else:
- **`SET c TO TRUE`**, where `c` is in `conditions`, its parent is tracked, and the 88 has
  exactly one value and no ranges. The parent gets that value, padded to the parent's length.
  `SET … TO FALSE` frees the parent: CardDemo has no `SET … TO FALSE`.
- **`MOVE` from a quoted literal or a figurative** into a tracked target with no reference
  modification and no subscripts. The value is the literal truncated to the target's length,
  or padded right with spaces. A figurative fills the length.

Steps:

- [ ] **Step 1: Write the failing unit tests.**
  - `test_a_literal_move_sets_the_flag_exactly`: `MOVE 'Y' TO F`, then X.
    `reaches(X, F = 'N')` gives `UNSAT`.
  - `test_set_to_true_assigns_the_condition_value`: `SET F-ON TO TRUE`, where 88 `F-ON` is
    `VALUE 'Y'`. Then `reaches(X, F = 'N')` gives `UNSAT`.
  - `test_a_moved_literal_is_padded_to_the_field`: `MOVE 'Y' TO F3`, where F3 is `PIC X(3)`.
    `reaches(X, F3 = 'Y  ')` gives `SAT`, and `F3 = 'YYY'` gives `UNSAT`.
- [ ] **Step 2: Write the failing CardDemo gates**, from `COSGN00C.cbl` :118–119, :123–124 and
  :138–139. A blank or low-values user id or password sets `WS-ERR-FLG` to `'Y'`, and the read
  that leads to the XCTL runs only when the flag is off. Each test reaches the user-menu XCTL
  with the condition shown, and expects `UNSAT`:
  - `test_signon_never_transfers_with_a_blank_user_id`: `USERIDI == SPACES`
  - `test_signon_never_transfers_with_a_low_values_user_id`: `USERIDI == LOW-VALUES`
  - `test_signon_never_transfers_with_a_blank_password`: `PASSWDI == SPACES`
  - `test_signon_never_transfers_with_a_low_values_password`: `PASSWDI == LOW-VALUES`
- [ ] **Step 3:** Run
  `cd cobble && . ../bridge-env.sh && uv run --no-sync pytest tests/experimental/horn tests/carddemo/test_horn.py -q --log-cli-level=INFO`.
  Expected: the seven new tests fail, giving `SAT` where `UNSAT` is expected, and the stage 0
  tests pass.
- [ ] **Step 4:** Implement `exact_writes`, and use it in `lower`.
- [ ] **Step 5:** Re-run the step 3 command. Expected: all pass. **Stop and consult** on any
  `UNKNOWN` or failure. Do not loosen a gate.
- [ ] **Step 6:** Mutation check. Pad on the left instead of the right, then make `SET` free
  the parent. Each break must fail a test. Then restore.
- [ ] **Step 7:** Update `horn.md`'s exact-encoding list. Record the results below.
- [ ] **Step 8:** Commit stage 1 with the message
  `feat(cobble): Horn clause lowering, stage 1 -- flag assignments`. Then push.

## Results

Stage 0, 2026-11-05, z3-solver 5.3.3. COSGN00C lowers to 11 tracked fields, 6 contexts, 107
relations and 122 rules.

| gate | answer | solver time |
|---|---|---|
| `test_signon_can_transfer_to_the_user_menu` | `SAT` | 0.035 s |
| `test_signon_can_transfer_to_the_admin_menu` | `SAT` | 0.029 s |
| `test_signon_never_sends_an_admin_to_the_user_menu` | `UNSAT` | 0.007 s |
| `test_signon_never_sends_a_user_to_the_admin_menu` | `UNSAT` | 0.006 s |

Deviations, decided during execution:
- z3 ships no type stubs, and pyright reads its constructors as unions of every term. With the
  user's agreement, `terms.py` wraps the constructors the lowering uses, each checking the term's
  class at the boundary.
- `Tracked.extent` is cobble's `ByteRange`, which is program-scoped and has `overlaps`.
- The GO TO test: `srccfg/build.py` keeps the edge past a PERFORM whose range end nothing
  reaches, so a range that only does `GO TO` leaves the resume reachable by the CFG's own account.
  The test's range instead does `GO TO` only when `F = 'Y'`, and the resume is `UNSAT` with
  `F = 'Y'` and `SAT` with `F = 'N'`.

Stage 1, 2026-11-05. With z3 strings, the four blank-input gates gave no answer within 60 s, and
one ran 30 minutes before it was stopped. With the user's agreement, the state became
bit-vectors, and names the extents stage synthesised for undeclared uses stopped being tracked
(`EIBAID`, `EIBCALEN` and `%HANDLER[ANY]` had been tracked as `PIC X(10)`). COSGN00C then has 8
tracked fields.

| gate | answer | solver time |
|---|---|---|
| `test_signon_can_transfer_to_the_user_menu` | `SAT` | 0.007 s |
| `test_signon_can_transfer_to_the_admin_menu` | `SAT` | 0.006 s |
| `test_signon_never_sends_an_admin_to_the_user_menu` | `UNSAT` | 0.005 s |
| `test_signon_never_sends_a_user_to_the_admin_menu` | `UNSAT` | 0.005 s |
| `test_signon_never_transfers_with_a_blank_user_id` | `UNSAT` | 0.243 s |
| `test_signon_never_transfers_with_a_low_values_user_id` | `UNSAT` | 0.282 s |
| `test_signon_never_transfers_with_a_blank_password` | `UNSAT` | 0.218 s |
| `test_signon_never_transfers_with_a_low_values_password` | `UNSAT` | 0.245 s |

Deviations, decided during execution:
- Stage 0 was unsound for SET: a SET node writes the 88 name, which has no extents row, so the
  parent kept its value. A written 88 now frees, or exactly assigns, its parent.
  `test_a_set_the_encoding_cannot_follow_frees_the_parent` pins it.
- `exact_writes` takes no `node`: nothing in it used the node.
- `ZERO`, `ZEROS` and `ZEROES` join the figuratives.
- Two unit tests compare `F` once, since a field never compared is not tracked.
