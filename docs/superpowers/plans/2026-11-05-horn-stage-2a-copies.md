# Horn clause lowering, stage 2a: exact copies within one task — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A field-to-field `MOVE` becomes an equality between bytes, so a question can ask whether one field holds another's bytes at a program point.

**Architecture:** The byte model of `2026-11-05-horn-byte-extents.md` gains a fourth byte effect, "copied from source byte k", taken from the fixpoint's `copy_start`. Tracked bytes grow from the test operands to also cover the fields a question names and, transitively, the source bytes of copies into tracked bytes. A question's condition may compare a field with another field or with a byte range of one.

**Tech Stack:** Python 3.13, z3-solver (Spacer), cobble's fixpoint transfer.

**Spec:** `docs/superpowers/specs/cobble/2026-11-04-horn-clause-lowering-design.md`, stage 2. Stage 2 is split, with the user, 2026-11-05: 2a is copies within one task (this plan); 2b is the conversation (`RETURN TRANSID`, `XCTL`, commarea mapping, `VALUE` initial state) and carries the `CONF-PAY-YES` gate.

## Decisions

Taken with the user, 2026-11-05:
- **The key gate is restated.** The spec asks "is the account rewritten to the key the user typed?". A CICS `REWRITE` rewrites the record its `READ UPDATE` held, chosen by `RIDFLD`; the `READ … INTO(ACCOUNT-RECORD)` overwrites `ACCT-ID` with the file's bytes. So the gate asks: at `READ-ACCTDAT-FILE/0` (COBIL00C.cbl:345, `RIDFLD(ACCT-ID) UPDATE`), does `ACCT-ID` hold the bytes of `ACTIDINI` (the screen field, copied at :170)? This needs no model of file keys.
- **The balance gate needs no snapshot.** `PERFORM WRITE-TRANSACT-FILE` (:233) runs before `COMPUTE ACCT-CURR-BAL` (:234), so at `WRITE-TRANSACT-FILE/0` the balance is still the value read. The copy `MOVE ACCT-CURR-BAL TO TRAN-AMT` (:224) is `S9(10)V99` into `S9(9)V99`: the fixpoint's `copy_start` is byte 1006 of the 12 bytes at 1005, so `TRAN-AMT` is bytes 2–12 of `ACCT-CURR-BAL`. The gate asks for that byte range, and also whether the balance's leading digit can be non-zero at the write: the spec's "always the balance that was read" is answered "equal except its top digit", not "yes".

Builder's calls, recorded here:
- **A copy reads the state before its statement**, as the fixpoint's `_move_writes` computes every target's value from the incoming state.
- **A copy is used only when it is exact:** not weak, target precision `EXACT`, `copy_start` set, exactly one source, and that source's origin is storage. Any other write keeps today's treatment.
- **A target byte with no source byte** (a receiver longer than its sender, or a `JUSTIFIED RIGHT` landing before the source's first byte) is freed, not set to the pad byte. Precision, not soundness.
- **A copied byte whose source byte is not tracked is freed.** After the closure every copy
  source that feeds a tracked byte is tracked, so this arises only for bytes outside the source
  extent, already freed by the rule above.
- **Questions name the fields they need at lowering time** (`lower(program, watched)`), because the state's segments are fixed when the rules are built.
- **Field-to-field and range comparisons in questions are byte equality**, for any PIC and usage. A numeric field compared with a literal is refused, as today: a numeric literal compares by value, not by bytes.

## Global Constraints

- Datalog constructions are neither consulted nor a prerequisite (`.importlinter` `horn-not-datalog`); z3 stays inside `cobble.experimental.horn` (`z3-only-in-horn`); nothing imports the horn package (`horn-is-a-leaf`).
- An `unsat` answer stays valid: anything not encoded exactly is unconstrained (spec, "Soundness rule").
- Each gate question becomes a CardDemo test in `cobble/tests/carddemo/test_horn.py`, citing source lines and the expected answer in its docstring; the solver time of each goes in this plan's Results.
- One commit for the whole plan (standing preference: no per-task hooked commits).

## Review Focus

1. A `MOVE` with several targets where one target overlaps the source: every target must take the source's bytes as they were before the statement.
2. A `JUSTIFIED RIGHT` receiver longer than its sender: the leading target bytes have no source byte and must be free, not copied from bytes before the source.
3. A copy whose source is subscripted or reference-modified with a computed start: the fixpoint gives no `copy_start`, and the target must be freed.
4. A copy chain `A → B → C` where only `C` is watched: `A` and `B` must be tracked by the closure, or `C` is wrongly free.
5. A watched name that is ambiguous or undeclared: refused at lowering with `ValueError`, not silently untracked.

Lines 1, 2 and 4 have unit tests in Task 1. Lines 3 and 5 are covered by Task 1's refusal and freeing tests.

---

### Task 1: copies in the encoding, watched fields, field and range conditions

**Files:**
- Create: `cobble/cobble/experimental/horn/copies.py`
- Modify: `cobble/cobble/experimental/horn/storage.py` (`storage_of`, `Storage.whole`)
- Modify: `cobble/cobble/experimental/horn/effects.py` (`Copied`, `_applied`)
- Modify: `cobble/cobble/experimental/horn/lower.py` (`lower`, `_runs`/`_run_key`, `_piece`)
- Modify: `cobble/cobble/experimental/horn/condition.py` (`Part`)
- Modify: `cobble/cobble/experimental/horn/reaches.py` (`_condition`)
- Test: `cobble/tests/experimental/horn/test_lower.py`

**Interfaces:**
- Produces:
  - `copies.Copy(target: FieldExtent, source: FieldExtent, start: int)`, frozen; `start` is the source byte (absolute, in `source.region`) landing on `target.start`. `Copy.source_of(offset: int) -> int` gives the source byte for a target byte, or -1 when it falls outside `source`.
  - `copies.copy_of(write: Write) -> tuple[Copy, ...]`: one `Copy` for an exact copy (Decisions), else `()`.
  - `copies.program_copies(program: Program) -> tuple[Copy, ...]`: every node's copies, from `writes_of(statement, node, program.index, EMPTY)` over `program.statements`.
  - `Storage.whole(name: str) -> tuple[FieldExtent, ...]`: the extent of the one cell `name` denotes with no subscript, any PIC, or `()`.
  - `storage_of(program: Program, watched: Sequence[str]) -> Storage`: test operands (as today) plus each watched field's extent, closed under copies: for every copy whose target overlaps the tracked bytes, the source bytes of the overlapping target bytes are tracked too, until nothing changes. A watched name with no `whole` extent raises `ValueError(f"{name} is not one field")`.
  - `effects.Copied(region: RegionId, offset: int)`, frozen, joins `Byte = Kept | Freed | Copied | int`.
  - `lower(program: Program, watched: Sequence[str] = ()) -> HornSystem`.
  - `condition.Part(field: str, start: int, length: int)`, frozen; `start` is 1-based as in COBOL reference modification. `Condition.field: str | Part` and `Condition.value: str | Part`; a `Part` compared with a literal compares bytes with the literal's bytes, for any PIC.

- [ ] **Step 1: Write the failing tests** in `test_lower.py`, using the existing helpers (`_asg`, `_x`, `_move`, `_move_literal`, `_test`, `X_OUT`, `FIELDS`). `_ask` gains `watched: Sequence[str] = ()` passed to `lower`.

```python
def test_a_copy_carries_the_source_bytes_along_a_chain() -> None:
    """MOVE 'AB' TO A; MOVE A TO B; MOVE B TO C; MOVE 'CD' TO A. Only C is watched;
    the closure tracks A and B, and the later write to A leaves C alone."""
    data = (_x("A", "X(2)"), _x("B", "X(2)"), _x("C", "X(2)"), *FIELDS)
    program = [("MAIN", [_move_literal("'AB'", "A"), _move("A", "B"), _move("B", "C"),
                         _move_literal("'CD'", "A"), X_OUT])]

    assert _ask(program, data, "X-OUT", [Condition("C", Op.NE, "'AB'")], watched=("C",)) == Answer.UNSAT
    assert _ask(program, data, "X-OUT", [Condition("C", Op.EQ, "'AB'")], watched=("C",)) == Answer.SAT
    assert _ask(program, data, "X-OUT", [Condition("C", Op.NE, "A")], watched=("C", "A")) == Answer.SAT


def test_a_truncating_numeric_copy_holds_the_senders_low_order_bytes() -> None:
    """MOVE N3 TO N2, PIC 9(3) into 9(2): the fixpoint's copy_start is N3's second
    byte, so N2 equals bytes 2-3 of N3 and need not equal bytes 1-2."""
    data = (_x("N3", "9(3)"), _x("N2", "9(2)"), *FIELDS)
    program = [("MAIN", [_move("N3", "N2"), X_OUT])]

    assert _ask(program, data, "X-OUT", [Condition("N2", Op.NE, Part("N3", 2, 2))], watched=("N2", "N3")) == Answer.UNSAT
    assert _ask(program, data, "X-OUT", [Condition("N2", Op.NE, Part("N3", 1, 2))], watched=("N2", "N3")) == Answer.SAT


def test_every_target_of_one_move_takes_the_source_as_it_was() -> None:
    """MOVE A TO A2 B, where A2 overlaps A (Review Focus 1)."""


def test_a_justified_receiver_longer_than_its_sender_frees_its_leading_bytes() -> None:
    """MOVE S TO R, S PIC X(1), R PIC X(3) JUSTIFIED RIGHT: R's last byte is S;
    its first two have no source byte and are free (Review Focus 2)."""


def test_a_copy_from_a_computed_subscript_frees_the_target() -> None:
    """MOVE T(I) TO B: no copy_start, so B is free (Review Focus 3)."""


def test_a_watched_name_that_is_not_one_field_is_refused() -> None:
    """lower(program, ("NOPE",)) raises ValueError("NOPE is not one field") (Review Focus 5)."""
```

The stubbed tests are written out in full by the implementer, each with an `UNSAT` assertion
that fails without the feature and a `SAT` assertion that fails if a copy is taken too far:
- Test 3: `A` is an `X(3)` group with an `X(2)` child `A2` at offset 1; `MOVE 'ABC' TO A`,
  then `MOVE A TO A2 B` with `B PIC X(3)`. `B != 'ABC'` is `UNSAT`.
- Test 4: `P PIC X(2)` declared just before `S PIC X(1)`, and `R PIC X(3) JUSTIFIED RIGHT`.
  `MOVE 'PP' TO P`, `MOVE 'Y' TO S`, `MOVE S TO R`. `S != Part("R", 3, 1)` is `UNSAT`;
  `R == 'QQY'` is `SAT` (it would be `UNSAT` if R's leading bytes were copied from P).
- Test 5: an `OCCURS 3` table `T` of `X(2)`, subscripted by `I`, as in the existing part-field
  test. `MOVE 'AB' TO B`, `MOVE T(I) TO B`. `B != 'AB'` is `SAT`.
- Test 6: `lower(program_of(...), ("NOPE",))` raises `ValueError("NOPE is not one field")`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd cobble && uv run --no-sync pytest tests/experimental/horn/test_lower.py -q`
Expected: the six new tests FAIL: first on the missing `Part` and `watched`, then, once those exist, `SAT` where `UNSAT` is asserted; the existing tests still pass.

- [ ] **Step 3: Implement** the Interfaces above.
  - `effects._applied`: a definite value sets bytes, as today; otherwise a `copy_of(write)` sets each target byte in a segment to `Copied(source.region, source_of(offset))` when that source byte is tracked (`storage.locate` of the one-byte extent ≥ 0) and inside `source`, else `Freed(n)`; otherwise `Freed(n)`.
  - `lower._run_key`: consecutive `Copied` bytes form one run when their source offsets rise by one and lie in one segment; `_piece` turns a run into `Segment.slice` over that source segment's `now` variable.
  - `reaches._condition`: a `Part` or a value naming a field compares bytes (`Storage.whole` on both sides; a `Part` is `start - 1` to `start - 1 + length` within the field, refused with `ValueError` when outside it or when the two sides differ in length); a literal value keeps today's path through `comparison`.
  - The existing callers of `storage_of` and `lower` (tests included) move to the new signatures.

- [ ] **Step 4: Run them to verify they pass**

Run: `cd cobble && uv run --no-sync pytest tests/experimental/horn -q`
Expected: all pass.

- [ ] **Step 5: Mutation check.** Break `Copy.source_of` to ignore `start` (use `source.start`), and drop the closure loop; each break fails at least one new test. Restore.

### Task 2: COBIL00C gates

**Files:**
- Modify: `cobble/tests/carddemo/test_horn.py`
- Modify: `docs/reference/cobble/horn.md`
- Modify: this plan (Results)

**Interfaces:**
- Consumes: `lower(program, watched)`, `Condition`, `Part` from Task 1.

- [ ] **Step 1: Write the gate tests.** `_lowered(run, program, watched=())`; the `billpay` fixture watches `("TRAN-AMT", "ACCT-CURR-BAL", "ACCT-ID", "ACTIDINI")`. New points `WRITE_TRANSACT = Point(BILLPAY, "WRITE-TRANSACT-FILE/0")`, `READ_ACCOUNT = Point(BILLPAY, "READ-ACCTDAT-FILE/0")`.

```python
def test_billpay_writes_the_balance_it_read_less_its_leading_digit(billpay):
    """COBIL00C.cbl:224 MOVE ACCT-CURR-BAL (S9(10)V99) TO TRAN-AMT (S9(9)V99), :233
    PERFORM WRITE-TRANSACT-FILE before :234 COMPUTE ACCT-CURR-BAL. TRAN-AMT is
    bytes 2-12 of the balance as read, and the balance's leading digit may be
    non-zero there: the amount equals the balance except its top digit, so they
    differ for a balance of 1,000,000,000.00 or more."""
    assert _ask(billpay, WRITE_TRANSACT, (Condition("TRAN-AMT", Op.NE, Part("ACCT-CURR-BAL", 2, 11)),)) == Answer.UNSAT
    assert _ask(billpay, WRITE_TRANSACT, (Condition("TRAN-AMT", Op.EQ, Part("ACCT-CURR-BAL", 2, 11)),)) == Answer.SAT
    assert _ask(billpay, WRITE_TRANSACT, (Condition(Part("ACCT-CURR-BAL", 1, 1), Op.NE, "'0'"),)) == Answer.SAT


def test_billpay_reads_for_update_the_account_the_user_typed(billpay):
    """COBIL00C.cbl:170 MOVE ACTIDINI OF COBIL0AI TO ACCT-ID XREF-ACCT-ID; both
    callers of READ-ACCTDAT-FILE (:177, :184) follow it; :345 EXEC CICS READ
    RIDFLD(ACCT-ID) UPDATE."""
    assert _ask(billpay, READ_ACCOUNT, (Condition("ACCT-ID", Op.NE, "ACTIDINI"),)) == Answer.UNSAT
    assert _ask(billpay, READ_ACCOUNT, (Condition("ACCT-ID", Op.EQ, "ACTIDINI"),)) == Answer.SAT
```

- [ ] **Step 2: Run** `cd cobble && uv run --no-sync pytest tests/carddemo/test_horn.py -q --log-cli-level=INFO`
Expected: every test passes, including the existing sign-on and bill-pay gates with the larger bill-pay state. Record each new question's time, and the bill-pay segment, byte and rule counts from the lowering's log line, under Results.

- [ ] **Step 3: Docs.** `horn.md`: tracked bytes include watched fields and copy sources; a copy sets bytes equal to its source's; questions may compare fields and `Part`s; the stage list names 2a done and 2b next.

- [ ] **Step 4: Commit** (one commit, hooks are the gate):

```bash
git add cobble/cobble/experimental/horn cobble/tests/experimental/horn/test_lower.py \
  cobble/tests/carddemo/test_horn.py docs/reference/cobble/horn.md \
  docs/superpowers/plans/2026-11-05-horn-stage-2a-copies.md
git commit -m "feat(cobble): Horn clause lowering, stage 2a -- exact copies"
```

## Results

2026-11-05, z3-solver 5.3.3. Every answer matched.

Sign-on lowers to 8 segments (37 bytes; the closure adds one byte) and 122 rules. Bill pay,
watching `TRAN-AMT`, `ACCT-CURR-BAL`, `ACCT-ID` and `ACTIDINI`, lowers to 18 segments (125
bytes, from 50) and 328 rules. Times from one run of the CardDemo Horn tests:

| question | answer | time |
|---|---|---|
| sign-on, all eight stage 0–1 gates | as before | 0.005–0.26 s |
| bill pay `:211` / with `CONFIRMI` neither `'Y'` nor `'y'` | `sat` / `unsat` | 19.8 s / 9.0 s |
| bill pay `:211` with `ACTIDINI` SPACES / LOW-VALUES | `unsat` / `unsat` | 16.1 s / 9.7 s |
| bill pay REWRITE with `CONFIRMI = 'Y'` and `WS-ERR-FLG = 'N'` / `'Y'` | `unsat` / `sat` | 7.2 s / 18.6 s |
| `WRITE-TRANSACT-FILE/0`: `TRAN-AMT` ≠ / = bytes 2–12 of `ACCT-CURR-BAL` | `unsat` / `sat` | 0.05 s / 4.9 s |
| `WRITE-TRANSACT-FILE/0`: leading byte of `ACCT-CURR-BAL` ≠ `'0'` | `sat` | 8.0 s |
| `READ-ACCTDAT-FILE/0`: `ACCT-ID` ≠ / = `ACTIDINI` | `unsat` / `sat` | 0.08 s / 0.12 s |

The larger state slows the stage 0–1 bill-pay questions three to four times (they were 1.6–5 s
on 50 bytes); the copy questions themselves are fast.

Deviations, decided during execution:
- `Part` is allowed on the left of a condition too, so the balance gate can also ask whether the
  balance's leading digit can be non-zero at the write. Without it a passing gate reads as
  "always equal"; the answer is "equal except the top digit".
- The copy's sources are read from the state before the statement, so a multi-target `MOVE`
  needed no sequential composition inside the node (the fixpoint does the same).

Revised after the final review, 2026-11-05, with the user:
- A move into a number keeps only each byte's digit half (option B). IBM's `NUMPROC`, `ZONEDATA`
  and `INVDATA` repair zones and signs on such moves, and red-dragon re-encodes every receiver
  with zone `F` and sign `C` or `D`; a byte copy was wrong under both. The fixpoint's `Write`
  gains `digits` (receiver numeric, sender not a group), the Horn state a `Digit` byte (fresh
  zone over the source's digit half), and questions a `Digits` operand. Both bill-pay gates ask
  digit questions; the byte question `TRAN-AMT` ≠ bytes 2–12 of `ACCT-CURR-BAL` is now `sat`.
  More fidelity later only constrains the free zones, so every `unsat` here stays `unsat`.
- A copy whose source shares a byte with its target is not exact: COBOL leaves the result
  undefined, and a byte-at-a-time copy differs from one read before the statement.
- `SIGN LEADING` and `SIGN SEPARATE` reach the fixpoint's cells (separate commit); a signed move
  between a leading and a trailing sign records no landing.
- A copy from a variable-length reference modification is not exact (the source must be
  `EXACT`).
- Not done: a literal longer than the `Part` it is compared with reports "not a tracked field".

After the revision the CardDemo Horn tests, all thirteen, ran in 289 s (163 s before it,
including the fixture's corpus setup); per-question times were not taken again.
