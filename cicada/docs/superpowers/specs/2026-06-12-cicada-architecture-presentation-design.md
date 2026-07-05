# Cicada Architecture Presentation — Design Spec

**Date:** 2026-06-12
**Format:** RevealJS, self-contained HTML
**Output path:** `docs/cicada-architecture.html`
**Audience:** Engineering peers (familiar with interpreters and runtimes)
**Use:** Both live talk and standalone reference
**Centrepiece:** Transaction dispatcher
**Constraint:** No code snippets

---

## Approach

Pipeline-first (Approach A): establish the full data-flow before zooming into the dispatcher. The audience sees where each piece sits before the deep-dive begins.

---

## Slide plan (14 slides)

### Slide 1 — Title
- Title: *Cicada — CICS Emulation for the RedDragon VM*
- Subtitle: pseudo-conversational transactions, VSAM file control, BMS screen handling
- Repo link

### Slide 2 — What is Cicada?
- One diagram: real unmodified COBOL programs → Cicada layer → RedDragon VM
- Three bullet points: pseudo-conversational dispatch, VSAM KSDS file control, BMS screen handling
- Key constraint: no edits to the VM core

### Slide 3 — Pipeline overview (two rows)

**Row A — BMS toolchain (runs once at setup):**
`.bms` source files → `hlasm_export` (HLASM assembler) → `bms_copybook_gen` → symbolic COBOL copybooks (`.cpy`)

**Row B — Per-program execution pipeline:**
Raw COBOL + copybooks → `inject_dfheiblk` → ProLeap parser → DFHRESP pre-pass → `CicsLoweringStrategy` (lower to IR) → `run_cics` (VM) → `_advance_routing` (dispatch)

Arrows show Row A feeding copybooks into Row B.
Colour-coding: BMS (green), preprocess (orange), parse (grey), lower (blue), dispatch (purple).

### Slide 4 — Preprocessor: inject_dfheiblk
- Why: every CICS program reads EIB fields (EIBAID, EIBCALEN, EIBTRNID, …); they must exist in WORKING-STORAGE before the parser runs.
- What: inserts `COPY DFHEIBLK.` immediately after the `WORKING-STORAGE SECTION.` header.
- Visual: before/after source blocks (text only, no syntax highlighting).

### Slide 5 — Preprocessor: DFHRESP pre-pass
- Two-stage story:
  - **Text pass:** maps condition-name strings → numeric codes (NORMAL=0, ERROR=1, NOTFND=13, …; unknown → sentinel 9999).
  - **Expression-tree pass:** walks the AST and replaces every `{kind:dfhresp}` node with the resolved numeric literal.
- Why it's a separate pass: the main parser would otherwise choke on bare condition names in IF expressions.

### Slide 6 — Lowering to IR: CicsLoweringStrategy
- `CicsLoweringStrategy` is injected into `CobolFrontend` — not subclassed.
- Verb families table (4 rows):

| Family | Verbs |
|--------|-------|
| Flow control | RETURN, RETURN TRANSID, XCTL, ABEND |
| Screen / BMS | SEND MAP, RECEIVE MAP |
| VSAM point ops | READ, WRITE, REWRITE, DELETE |
| VSAM browse | STARTBR, READNEXT, ENDBR |

All verbs lower to `CallFunction` IR targeting registered builtins.

### Slide 7 — Lowering to IR: operand resolution
- Diagram: EXEC CICS operand → `emit_operand_value` → two paths:
  - data-name → `LoadRegion` IR → register
  - literal → `Const` IR → register
- Both paths converge at the builtin `CallFunction`.
- RESP writeback: a side-channel after the call writes the response code back to the named data item.

### Slide 8 — CicsContext — what enters each turn
Visual table:

| Field | Type | Meaning |
|-------|------|---------|
| `transid` | 4-char string | determines which program runs |
| `commarea` | bytes | session state carried between turns |
| `eibaid` | 1-char string | attention key (DFHENTER, PF keys, CLEAR) |

Diagram: terminal sends (AID key + screen fields) → `InputEvent` → `CicsContext` assembled → `run_cics`.

### Slide 9 — DispatchResult — what exits each turn
Four-row outcome table:

| Kind | Meaning |
|------|---------|
| `RETURN` | task ends; no successor |
| `RETURN_TRANSID` | next turn; new transid + commarea; waits for terminal input |
| `XCTL` | transfer to named program; same transid; no terminal round-trip |
| `ABEND` | abnormal end; abcode (TRNI / PGMI / …); terminal |

### Slide 10 — _advance_routing: routing table
Decision flowchart with three branches from `DispatchResult.kind`:

- **RETURN_TRANSID:** look up `result.transid` in `transid_to_program` → found: continue with new transid + program + commarea / not found: ABEND TRNI
- **XCTL:** look up `result.program` in `program_cache` → found: continue with same transid + new program + commarea / not found: ABEND PGMI
- **RETURN / ABEND:** pass through unchanged → terminal state

### Slide 11 — CicsRegion state machine
State diagram:

```
IDLE ──start()──▶ RUNNING ──RETURN_TRANSID──▶ WAITING_FOR_INPUT
                     ▲                                │
                     └──────step(input_event)─────────┘
                     │
                     ├──XCTL──▶ RUNNING (same state, new program)
                     │
                     └──RETURN / ABEND──▶ TERMINAL
```

Key invariant: `step()` on a done region raises `RuntimeError`.

### Slide 12 — Pseudo-conversational turn sequence
Horizontal timeline using CardDemo sign-on as the example:

- **Turn 1:** transid=CC00 → COSGN00C → SEND MAP (login screen) → RETURN_TRANSID CC00
- *(user types credentials + ENTER)*
- **Turn 2:** transid=CC00 → COSGN00C → RECEIVE MAP → validate → XCTL COMEN01C
- *(immediate — no terminal round-trip)*
- **Turn 3:** transid=CC00 (carried) → COMEN01C → SEND MAP (main menu) → RETURN_TRANSID CC00
- *(user selects option → next turn)*

Callout: commarea carries session state; transid is the "return address".

### Slide 13 — CardDemo walkthrough
Real CSD excerpt (annotated, not raw text): CC00→COSGN00C, CA00→COMEN01C, ACNT→COACTUPC.
Shows how `parse_csd()` builds the `transid_to_program` map that feeds `_advance_routing`.

### Slide 14 — Key invariants
Three invariants in large type:

1. No edits to the RedDragon VM core — every CICS behaviour reaches the VM via `CallFunction` IR to registered builtins.
2. `CicsLoweringStrategy` is injection, not subclassing — the same extension point any language frontend uses.
3. `_advance_routing` is the single source of truth for routing; both `CicsRegion` and the blocking loop call it.

---

## Visual style

- Dark theme (dark navy background, colour-coded by pipeline stage)
- No syntax-highlighted code blocks
- Diagrams: flow boxes for pipelines, tables for reference slides, state diagram for CicsRegion
- RevealJS `hash: true` for direct-link navigation (self-contained reference use)
- Slide numbers on
- Font: system sans-serif stack; monospace only for identifiers

---

## File layout

```
docs/
  cicada-architecture.html   # self-contained RevealJS (CDN links + inline data)
  superpowers/
    specs/
      2026-06-12-cicada-architecture-presentation-design.md   # this file
```
