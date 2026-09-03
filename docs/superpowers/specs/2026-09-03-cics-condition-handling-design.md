# CICS condition raising and HANDLE CONDITION dispatch

*2026-09-03 — design for forge-5by and red-dragon-pz9g.12*

## Why

`docs/analysis/2026-09-01-index-items-search-and-cics-verb-gaps.md` defect F is the
largest-radius gap it records: **2,679 `HANDLE CONDITION` occurrences across 1,599
of 2,137 programs — 75%**, plus `IGNORE CONDITION` at 820. Today both halves of
condition handling are missing.

Registration is discarded: `HANDLE CONDITION` maps to a builtin that logs at INFO
and drops the condition→label pairs. And nothing raises a condition in the first
place — `emit_resp_writeback` writes the code into `EIBRESP` and the `RESP(name)`
field and stops. No branch, no abend, no signal. `NOHANDLE` appears nowhere,
which is at least self-consistent: every verb already behaves as though it were
coded.

So a program whose entire error strategy is `HANDLE CONDITION MAPFAIL(...)`
proceeds *through* the failure, on stale data, silently. The corpus's error paths
are written that way throughout.

## Decisions

### Only the conditions the corpus handles are raised

The nine the corpus codes handlers for: `NOTOPEN`, `NOTFND`, `INVREQ`, `ERROR`,
`LENGERR`, `MAPFAIL`, `NOSPACE`, `DUPKEY`, `DUPREC`. Every verb keeps writing
`EIBRESP` exactly as it does now; only these gain the raise-and-transfer path.

Raising every condition a verb can produce is the uniform alternative and was
rejected for this slice: it turns on error paths nothing has exercised across every
implemented verb at once, and the conditions outside the nine stay exactly as
truthful as they are today rather than becoming newly wrong.

### An unhandled condition abends, as CICS does

A command coding neither `RESP` nor `NOHANDLE` that raises a condition with no
handler registered abends the task. That is what CICS does, and it is the point of
the exercise: today the program sails on with stale data and reports success.

**This will look like a regression.** Runs that pass today will start abending,
because they were passing on a lie. The analysis document predicted exactly this
and said to expect the noise and say so up front — so it is said here.

### `RESP` and `NOHANDLE` suppress raising

In CICS a command coding `RESP(x)` or `NOHANDLE` does not raise: the program has
undertaken to check inline. Both are compile-time facts about the statement's
options, so the raise tail is simply not emitted for those commands. This is what
keeps the blast radius to commands that asked for no such contract.

### Per-program table, with `IGNORE`; no `PUSH`/`POP`

A handler table reset at program entry, later registrations overriding earlier,
`IGNORE CONDITION` cancelling one, and no leakage between a caller and a `LINK`ed
or `XCTL`ed program.

`IGNORE` is not optional at 820 occurrences: it is the operation that CANCELS a
`HANDLE`, so omitting it would make a registered handler fire where the program had
explicitly turned it off — a new wrong answer of exactly the kind this work removes.

`PUSH HANDLE` / `POP HANDLE` are out. They did not appear in the corpus verb counts
at all.

### The table lives in WORKING-STORAGE, not in runtime holder state

The obvious implementation is a Python dict in a builtin closure, matching the
`result_holder` / `context_holder` / `td_queue` convention the runtime already uses.
It is rejected because the condition→label mapping would then be **invisible in the
generated IR**: the IR would show that a dispatch happens and which labels are
candidates, but not which condition currently maps to which. Program-entry reset and
call isolation would likewise be Python-side effects with no IR representation.

Putting the table in the program's own storage makes every part of the mechanism
ordinary visible IR — and it is what IBM's translator does, keeping the table in the
program's storage and emitting a computed `GO TO`.

Three things then come free rather than being built and trusted:

* **Override** — a later `HANDLE` is just a later write to the same slot.
* **Program-entry reset** — the `VALUE` clause; WORKING-STORAGE initialisation
  already does it.
* **`LINK` / `XCTL` isolation** — a separate program has separate WORKING-STORAGE,
  so a called program cannot leak handlers back to its caller. No save/restore
  machinery at all.

## Components

### The injected copybook

`cicada/cics/copybooks/DFHHANDLE.cpy`, injected by `apply_cics_prepass` immediately
after `DFHEIBLK` — the same technique, in the same place.

```cobol
      * Y marks a condition this runtime raises; the position is its DFHRESP
      * code, so slot 1 is NORMAL (0) and is never Y.
       01  DFH-RAISABLE-BYTES PIC X(37) VALUE
           'NNNNNNNNNNNNYYNNYNNNNNNNNNNNNNNNNNNNY'.
       01  DFH-RAISABLE-TAB REDEFINES DFH-RAISABLE-BYTES.
           05  DFH-RAISABLE OCCURS 37 TIMES PIC X.
       01  DFH-HANDLER-BYTES PIC X(74) VALUE LOW-VALUES.
       01  DFH-HANDLER-TAB REDEFINES DFH-HANDLER-BYTES.
           05  DFH-HANDLER OCCURS 37 TIMES PIC S9(4) COMP.
```

Two tables rather than one group with two fields per slot, because it keeps both
`VALUE` clauses writable and legible: the raisable set is a literal you can read
off against the DFHRESP numbering, and `LOW-VALUES` gives every handler slot the
binary zero that means "none". A single interleaved table would need one opaque
111-byte constant with binary zeros embedded in it.

Both are indexed by DFHRESP code; 37 slots covers `MAPFAIL` at 36. `DFH-RAISABLE`
is what enforces the scope decision — an out-of-scope condition can never reach the
dispatcher. The literal above is illustrative of the shape: the exact `Y` positions
must be set from the consolidated code table described below, not transcribed from
this document.

The `REDEFINES`-over-`VALUE` idiom is the one the corpus itself uses for message
tables, and red-dragon handles it (the analysis document's defect A reproduction
confirms the `FILLER`/`VALUE`/`REDEFINES`/`OCCURS` chain works).

### Lowering

| Statement | Emits |
|---|---|
| `HANDLE CONDITION NOTFND(PARA-X)` | write the compile-time index of `PARA-X` into `DFH-HANDLER(13)` |
| a later `HANDLE CONDITION NOTFND(PARA-Y)` | write `PARA-Y`'s index to the same slot |
| `IGNORE CONDITION NOTFND` | write 0 to that slot |
| program entry | nothing — the `VALUE` clause |
| `LINK` / `XCTL` | nothing — separate WORKING-STORAGE |

A `HANDLE CONDITION` inside a loop or an `IF` needs no special handling: it is a
write executed when reached, which is precisely why CICS calls handler activation a
runtime property.

### Label indices

A pre-pass over the program's parsed `HANDLE`/`IGNORE` statements assigns 1…N to
each distinct target paragraph; 0 means none. They appear in the IR as constants.
The pre-pass is needed because a `HANDLE CONDITION` may appear textually after a
command that must already branch to the dispatcher.

Paragraph labels are `CodeLabel(f"para_{name}")` — the convention
`lower_goto`/`_lower_computed_goto` already use, so a handler paragraph is directly
targetable.

### The raise tail

Emitted after `emit_resp_writeback` for a command that produces a resp AND codes
neither `RESP` nor `NOHANDLE`:

```
  r_flag = DFH-RAISABLE(EIBRESP + 1)
  if r_flag = 'Y'  ->  branch __cics_cond_dispatch
  (fall through, unchanged)
```

One comparison, not two: slot 1 is `EIBRESP` 0 (`NORMAL`) and is never `Y`, so the
success path needs no separate zero test.

### The dispatcher

One block per program, emitted after all labels are known. Its shape is
`_lower_computed_goto`'s (`vendor/red-dragon/interpreter/cobol/lower_arithmetic.py:1942`)
— a cascade of two-way branches, because `BranchIf` is strictly two-way
(`branch_targets[0]` true, `[1]` false; the VM ignores anything beyond index 1).

```
__cics_cond_dispatch:
  idx = DFH-HANDLER(EIBRESP + 1)
  if idx = 1 -> branch para_L1
  ...
  if idx = N -> branch para_LN
  call __cics_abend_unhandled(EIBRESP)
```

`red-dragon-pz9g.12` proposed a single `BranchIf` carrying all the handler labels,
"mirroring the IBM translator's `GO TO … DEPENDING ON`". The instinct was right and
the mechanism was not: the IR has no n-way branch. The cascade is how
`GO TO … DEPENDING ON` itself is lowered, so **no VM change is needed** — which
keeps cicada's "no edits to RedDragon's core engine" invariant intact.

The dispatcher is entered by a `Branch` and so takes no arguments: it reads
`EIBRESP` from WORKING-STORAGE, where `emit_resp_writeback` has already written it.

Because an unhandled condition abends, the dispatcher is emitted for **every**
program containing a fallible command, not only the 75% that register handlers. In
a program with no `HANDLE` at all the cascade is empty and control goes straight to
the abend.

### `__cics_abend_unhandled`

Maps the resp code to an abend code and records `DispatchResult(ABEND, ...)` in
`result_holder`, mirroring `make_abend_builtin` — the established way a builtin ends
a task.

**The abend code needs sourcing, not recall.** IBM assigns `AEIx` codes per
condition; this design does not state the mapping because it is not known here with
confidence. Until it is sourced from documentation, abend with one distinct code
that names the condition in its message rather than inventing letters that look
authoritative.

## Two findings that change the work

### The DFHRESP codes are scattered

There is no single source of truth for condition names and their codes. They are
spread across at least four modules, partially duplicated:

| Module | Codes |
|---|---|
| `cics/vsam/eibresp.py` | `NOTFND` 13, `DUPREC` 14, `IOERR` 17, `ENDFILE` 20, `DISABLED` 84 |
| `cics/builtins/system.py` | `NORMAL` 0, `PGMIDERR` 27 |
| `cics/builtins/interval.py` | `TERMIDERR` 11, `INVREQ` 16, `TRANSIDERR` 28, `ENDDATA` 29 |
| `cics/builtins/screen.py` | `INVREQ` 16, `MAPFAIL` 36 |

This feature needs one condition-name → code table — for the `DFH-RAISABLE`
literal, the slot each `HANDLE` writes, and the abend mapping — so it must consolidate these into one
table the rest then uses. That is a prerequisite, not a nice-to-have.

### `NOTOPEN` is never produced today

`cics/vsam/eibresp.py`'s "Decision A" deliberately maps `NOT_OPEN` (and
`FILE_NOT_FOUND`, `WRITE_NOT_PERMITTED`) to `IOERR`, reasoning that file state is an
FCT concern the adapter settles before calling a driver, so a driver-level
file-state condition means an internal inconsistency rather than a program-visible
condition.

That reasoning is sound on its own terms, but `NOTOPEN` was the **most-handled**
condition in the corpus scan — 20 occurrences, more than any other. So a program
whose error path is `HANDLE CONDITION NOTOPEN(...)` will register a handler that can
never fire, because nothing raises `NOTOPEN`.

Raising the other eight still makes 75% of programs' error paths live, so this does
not block the slice. But it means the single most-handled condition remains inert,
and that must be stated rather than discovered — either the adapter's decision is
revisited (a real file-state model, where a disabled or unopened file raises
`NOTOPEN`), or the gap is recorded so nobody concludes from a green suite that
`NOTOPEN` handling works.

## Testing

Asserting decoded data rather than that a branch ran, per the analysis document's
own rule.

* **The corpus idiom, end to end** — `HANDLE CONDITION NOTFND(PARA-ERR)` plus a
  `READ` that misses: control lands in `PARA-ERR`, proven by what that paragraph
  writes, not by a flag.
* **Override** — two `HANDLE`s for one condition; the second wins.
* **`IGNORE` cancels** — `HANDLE` then `IGNORE` then a failing command: execution
  continues past it rather than transferring.
* **Unhandled abends** — a failing command with no handler, asserting the concrete
  abend code.
* **`RESP` suppresses raising** — today's behaviour preserved exactly: `EIBRESP`
  set, execution continues, no transfer. Same for `NOHANDLE`.
* **`LINK` isolation** — a called program's `HANDLE` does not affect the caller's
  subsequent failing command.
* **Executed, not declared** — a `HANDLE` inside an `IF` that does not run leaves
  the condition unhandled.

## What this will break, and why that is the deliverable

cicada's suite drives real CardDemo programs. Any of them that currently proceeds
past a failing command will start abending once raising is on. Expect existing tests
to fail, and expect the triage of each — "the program was genuinely broken and the
runtime was hiding it" versus "our raising is wrong" — to be the substance of the
work rather than an afterthought to it.

A green suite after this lands means something different from a green suite before
it: previously it meant no test noticed a problem, and afterwards it means the error
paths actually execute.

## Out of scope

* `PUSH HANDLE` / `POP HANDLE`.
* `HANDLE AID`, which is keyed on `EIBAID` rather than `EIBRESP` and needs its own
  table (10 occurrences).
* Conditions outside the nine.
* `RESP2`.
* Revisiting the `NOTOPEN` → `IOERR` adapter decision, recorded above.
