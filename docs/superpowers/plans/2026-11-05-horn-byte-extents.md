# Horn clause lowering: byte extents instead of names

**Spec:** `docs/superpowers/specs/cobble/2026-11-04-horn-clause-lowering-design.md` (its "state
representation" is left to the builder). **Follows:** the review of stages 0–1
(`2026-11-05-horn-clause-lowering-stages-0-1.md`), which reproduced seven wrong `unsat` answers,
all from tracking names: a test on `F(1:1)` read as a test on `F`, a statement writing bytes its
CFG node does not list, two writes to one field in one statement, a qualified 88 resolved to the
wrong parent, name case, an unresolved `PERFORM`, `JUSTIFIED RIGHT`.

## Decisions

Taken with the user, 2026-11-05: the state is bytes, not names. A gap costs precision, never
soundness.

- **Tracked bytes.** Every byte a test can be encoded on: the extent of each operand of a plain
  `==`/`!=` atom (`Atom.plain`, cobble 59c07f55) whose field resolves to exactly one exact,
  alphanumeric extent in the program's layout. Overlapping and touching extents merge into one
  segment per region; a segment is one bit-vector, 8 bits per byte. Names the program does not
  declare have no extent, so they are never tracked.
- **Tests.** A plain atom compares the bytes of its left operand with a literal's bytes, a
  figurative's byte repeated, or the bytes of a right operand of the same length. Literal bytes
  are the fixpoint's (`fitted`, UTF-8), so a test and a write of the same literal agree. Anything
  else constrains nothing.
- **Writes.** What a node writes is the fixpoint's own: `program_statements` (condition sets,
  record areas, unmodelled writes) and the transfer's `writes_of`, read in order.
  - A definite write whose value is exactly one byte string sets those bytes.
  - A definite write from a figurative literal (`MOVE SPACES`) sets the figurative's byte,
    repeated. The fixpoint records the literal as the write's origin but no value; deriving the
    value there would raise the fixpoint's cost (+6% dequeues on the cost fixtures), so it is not
    done there.
  - Any other write frees the bytes it overlaps: weak, clamped, a copy, an unknown value, or a
    definite write into a `JUSTIFIED` cell (the fixpoint's literal value ignores justification,
    red-dragon-forge-r676).
  - Every name the CFG node lists as written also frees the bytes it resolves to, unless a
    definite write above covers them. This catches a statement whose writes the transfer misses.
  - A statement the transfer does not handle, and that is not on the list of statements that
    write nothing (IF, EVALUATE, PERFORM, GO TO, CONTINUE, DISPLAY, EXIT, STOP RUN, GOBACK,
    OPEN, CLOSE, SORT, MERGE, …), frees every tracked byte.
- **Control flow** is unchanged from stage 0, with one addition: the `FLOW` edge the CFG keeps past
  a `PERFORM` (an unresolved range, or one whose end nothing reaches) frees every tracked byte.
- **Questions.** `Condition(field, op, value)` resolves `field` through the same layout; one whose
  bytes are not tracked is refused with `ValueError`.
- **Inputs.** The lowering reads the ASG only; `extents.jsonl` is no longer an input.

## Tests

- Each of the seven reproductions becomes a unit test asserting the correct answer.
- The stage 0–1 unit tests keep their answers.
- The eight sign-on gates keep their answers; their times are recorded below.
- The bill-pay guard questions from the probe (`:211`, and the REWRITE with `CONFIRMI = 'Y'` and
  `WS-ERR-FLG = 'N'`) become CardDemo gates.

## Results

2026-11-05, z3-solver 5.3.3. Sign-on lowers to 8 segments (36 bytes) and 122 rules; bill pay to
10 segments (50 bytes) and 328 rules. Every answer matched; times from a 60 s-limited run of each
question on its own:

| question | answer | time |
|---|---|---|
| sign-on reaches the user menu / admin menu | `sat` / `sat` | 0.01 s each |
| sign-on sends an admin to the user menu / a user to the admin menu | `unsat` / `unsat` | under 0.01 s |
| sign-on transfers with a blank / low-values user id | `unsat` / `unsat` | 0.28 s / 0.21 s |
| sign-on transfers with a blank / low-values password | `unsat` / `unsat` | 0.23 s / 0.24 s |
| bill pay reaches `:211` | `sat` | 1.62 s |
| bill pay reaches `:211` with `CONFIRMI` neither `'Y'` nor `'y'` | `unsat` | 2.94 s |
| bill pay reaches `:211` with `ACTIDINI` SPACES / LOW-VALUES | `unsat` / `unsat` | 2.62 s / 4.97 s |
| bill pay REWRITE with `CONFIRMI = 'Y'` and `WS-ERR-FLG = 'N'` / `'Y'` | `unsat` / `sat` | 3.72 s / 4.41 s |

Deviations, decided during execution:
- Figurative values are taken from the write's literal origin in the Horn package, not given to
  the fixpoint: there they raised the cost fixtures' dequeues by 6% (20490 to 21777 on
  SYNPERFA), a cost change that is the user's to make.
- FILE STATUS fields are freed at every file statement. Neither the CFG nor the transfer records
  that write, and a test such as `IF WS-FS = '00'` after a READ would otherwise read a stale
  value.
- The CFG-name fallback earns its place on CardDemo: in 40 online programs it frees bytes the
  transfer misses at 34 writes, among them `EXEC CICS FORMATTIME` outputs.
