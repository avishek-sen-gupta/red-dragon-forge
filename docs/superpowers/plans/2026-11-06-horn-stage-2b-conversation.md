# Horn stage 2b: the conversation

**Goal:** answer a question that spans CICS tasks: can card update rewrite a card in a chain of
commareas where its change checks never passed?

**Spec:** `docs/superpowers/specs/cobble/2026-11-04-horn-clause-lowering-design.md`, stage 2.

## Decisions

Taken with the user, 2026-11-05/06:

- The gate is card update's REWRITE (`COCRDUPC.cbl:988-990`, `:1478`), with bill pay's one-press
  payment as the control. The spec's bill pay gate ("the confirmation arrives in a later task")
  does not hold: one Enter carrying the account id and `Y` pays (`COBIL00C.cbl:173-176`,
  `:210-235`).
- Screen input is free. A protected field coming back unchanged is the terminal's doing, not the
  program's, and is not modelled.
- The user handed the remaining calls over; they are recorded below as rulings.

## Rulings

- **Which programs.** The target and the programs that transfer straight into it (card list,
  menu), from `links.jsonl`. A transfer from any other program hands over unknown bytes. Cost if
  wrong: a spurious `sat` that a wider set would remove; never a wrong `unsat`.
- **Marks are unknown where a chain of commareas begins**, a cold start included. `Visited(p,
  False)` then asks about the chain, not about the terminal's whole session, and stays sound for
  XCTL or RETURN without a commarea, which `links.jsonl` does not list.
- **VALUE clauses at every task start, in a conversation only.** CICS gives a transaction's
  program, and one entered by LINK or XCTL, a newly initialised copy of working storage; a
  program entered by CALL keeps its last state, so `lower` (one task, any entry) still reads no
  VALUE clause. Source: IBM, *CICS for iSeries Application Programming Guide* SC41-5454-02, and
  *CICS TS for z/OS 5.4 Developing CICS Applications* ("a separate copy of working storage every
  time an application program runs").
- **EIBCALEN** is a 16-bit slot when a program tests it against an integer and declares no field of
  that name: 0 on a cold start, the callee extent's length on a hand-over.
- **Numbers against integers by value**, with an invalid digit half opening both edges and a
  non-digit zone opening the FALSE edge, since compiler options may compare the bytes as they
  stand.
- **Found on the way, fixed:** a `PIC 9(n)` field counted as alphanumeric, because the check
  looked only at letters. Two numbers that test equal were then taken to hold equal bytes, which
  excludes runs whose zones differ: unsound. Now a picture must be a group or X and A only.
- **INSPECT frees only what it writes.** Its CFG node lists the TALLYING counters and, under
  REPLACING or CONVERTING, the item inspected, which is what COBOL lets it write. Before, it
  freed every tracked byte, so card update's state byte could become `'N'` in an INSPECT and the
  gate was `sat`.

- **Integer literals into numbers.** `SET CDEMO-PGM-ENTER TO TRUE` (an 88-level `VALUE 0` on a
  `PIC 9(01)` field) is a MOVE of the literal 0, which the fixpoint leaves unknown. The card list's
  hand-over then carried any context byte, and the gate was `sat` again. Such a move now sets
  the digits.
- **Kept tests as part of the question.** Every encoding of all the tests ran out of time (below).
  A question now names the fields whose tests it keeps (`NamedFields`); a test not kept
  constrains nothing, so the choice can cost a spurious `sat`, never a wrong `unsat`. Fields
  guessed from names inside cobble stay ruled out; fields named in the question are the
  question's.
- **The three-program gate is marked `slow`** and left out of the commit hook (user's call);
  `make test-all` runs it.

## Results

CardDemo run, Apple silicon. "No answer" means the run was stopped at the limit given.

| Encoding | Programs | Tracked bytes (card update) | Answer |
|---|---|---|---|
| every test | card update, card list, menu | about 1,100 | no answer in 58 min |
| every test | card update's own chain | about 1,100 | no answer in 25 min |
| tests on control fields picked by name (scratch only) | card update's own chain | 112 | `unsat`, 152 s |
| tests on the REWRITE's control dependences, one level of their writers | card update's own chain | 1,008 | no answer in 10 min |
| kept: EIBCALEN, CCUP-CHANGE-ACTION | card update's own chain | 3 | `unsat`, 1.3 s |
| kept: the eight `CARD_HANDOVER` fields | card update, card list, menu | 54 | `unsat`, 159 s alone; 41 s for the gate's three questions under pytest |

Following copies from the REWRITE's tests reaches nearly every byte, so slicing by the code does
not shrink the state; keeping the right few tests does.

**Choosing the fields.**

- A fresh agent, given only the three programs and the question, named the eight
  `CARD_HANDOVER` fields with a line of code for each, and they proved the gate on the first
  try.
- By hand, two rounds: the change-action byte and EIBCALEN, then `CDEMO-FROM-PROGRAM` and
  `CDEMO-PGM-CONTEXT` once a spurious run skipped the entry test (`COCRDUPC.cbl:388-390`).
- An automatic loop worked on card update's own chain: keep nothing, take Spacer's
  counterexample, replay it with every byte tracked as one loop-free query, and keep the tests
  the failed replay blames. It found `CCARD-AID`, `CCUP-CHANGE-ACTION` and `EIBCALEN` in four
  rounds (about 2.5 minutes). It does not ship:
  - Spacer returns a counterexample in the rules as given only with all its rule transforms off;
    otherwise most steps are rewritten rules and the start of the run is missing.
  - With eager inlining off, a solve that takes 0.6 s takes 316 s. On three programs, extracting
    the round-5 counterexample did not finish in 30 minutes.
  - The replay itself took about 10 s a round and accepted real runs (`2000-DECIDE-ACTION`
    reached after three rounds).

## After the gate: three more questions

Asked on the same encoding, with the fields to keep picked by hand.

- **Account update's REWRITE** (`COACTUPC.cbl`, `9600-WRITE-PROCESSING`) never runs in a chain
  where neither change check ran: `unsat` in 52 s over account update and the menu, keeping
  seven fields; `sat` in 1.8 s once both checks ran.
- **Card update rewrites the card it showed?** `sat`. On the confirm press the key comes from
  the screen again (`COCRDUPC.cbl:603`, `:1425`), never compared with `CCUP-OLD-CARDID`; the
  record check (`:1503-1508`) compares the card's data, not its number. The program relies on
  the field being protected (`:1183`). Read from the code; the run was not replayed.
- **A user deleted without an admin sign-on?** Not settled. Thirteen programs take in their
  commarea with `MOVE DFHCOMMAREA(1:EIBCALEN)`, which the encoding used to free; that move is
  now encoded. The commarea's user type is no witness: the transaction type list sets it to `U`
  during an admin session (`COTRTLIC.cbl:634`), so the question is asked with a mark on
  sign-on's XCTL to the admin menu. Each `sat` was checked by keeping only the rules on the
  relations the solver's own run used and asking again with every test and field: the
  confirmation runs on a subgraph taken from the solver, never one picked by hand.
  - The first run continued past `PERFORM RETURN-TO-PREV-SCREEN`, whose range ends in an XCTL.
    The CFG keeps that edge as a margin against its own mistakes; the lowering now drops it
    when every way out of the range ends the task.
  - The next runs start a user-admin program cold and take its dynamic XCTL to another
    admin program. Cold, the program names sign-on in `CDEMO-TO-PROGRAM`, but a link row lets a
    dynamic XCTL reach every program it lists whatever that field holds. The check rejected
    each route. Tying a hand-over to the program-name field is the next gap.
  - Reading the code suggests a real path: `CTLI` started with no commarea sets
    `CDEMO-USRTYP-ADMIN` itself (`COTRTLIC.cbl:115-120`) and its PF3 goes to the admin menu
    (`:603`). The solver has not confirmed it.
