# TN3270 Green-Screen Terminal for Cicada — Design

**Date:** 2026-09-17
**Status:** Approved design, pending implementation plan

## Goal

Drive unmodified CICS programs (first target: CardDemo) from a real 3270 green screen. Cicada
becomes a TN3270 host; a stock emulator (x3270, c3270, wc3270, Vista) connects and is the
screen. The emulator owns operator interaction — field protection, tabbing, MDT, PF/PA/CLEAR —
so Cicada only encodes screens and decodes attention records.

**Headless driving stays first-class, permanently.** Every screen-fidelity feature lives in
protocol-neutral runtime code (`TerminalScreen`, `RegionDriver`) and is asserted headlessly;
TN3270 is one adapter over the existing channel seam, never the path headless tests take.

## Scope

- **In:** one terminal, one connection at a time; pseudo-conversational programs; 3278 model 2
  (24x80); basic TN3270 (RFC 1576) with extended attributes for `-E` terminal types.
- **Later (own epic):** conversational programs (`SEND`/`RECEIVE` loops in one task, e.g.
  zBANK) via a `ConversationalDriver` over `ConversationalRegion`. The design keeps the seam
  for it; nothing here builds it.
- **Out:** multiple concurrent terminals, TN3270E, SEND CONTROL, bare SEND FROM, SEND TEXT
  data-name resolution, alternate screen sizes.

## Current state

- `CicsRegion` (`cicada/cics/dispatcher.py`) runs one task per `start`/`step`; SEND MAP puts
  `{"map", "fields": {BASE: text}}` on a `ScreenChannel`; RECEIVE MAP gets an
  `InputEvent(eibaid, fields)` from an `InputChannel` (`cicada/cics/terminal.py`).
- SEND MAP ignores MAPSET, MAPONLY, DATAONLY, ERASE, CURSOR, FREEKB (forge-qh5) and the
  symbolic map's `L`/`F`/`A`/`C`/`H` bytes. RECEIVE MAP sets no `F` byte, leaves unreceived
  fields untouched, never sets EIBCPOSN.
- Two BMS models: `bms_copybook_gen` (cicada; drops POS, INITIAL, COLOR, HILIGHT, unlabelled
  captions) and `cobble/cobble/bms_render.py` (`ScreenMap`/`ScreenField`, keeps them, reaches
  into `bms_metadata` private helpers).
- No screen buffer, datastream, or cursor model exists.

## Architecture

```
            ┌───────────── cicada runtime (protocol-neutral) ─────────────┐
 BMS .bms ─▶│ MapCatalog ─▶ SEND MAP builtin ─▶ payload ─▶ TerminalScreen │
            │                RECEIVE MAP builtin ◀─ InputEvent            │
            │ RegionDriver: PseudoConversationalDriver (ConversationalDriver later)
            └──────────────▲──────────────────────────────▲───────────────┘
                           │                              │
                 headless tests / scripts        cics.tn3270 adapter
                                                 (encoder, decoder, telnet,
                                                  TerminalSession, CLI)
                                                          │
                                                   x3270 / s3270
```

### 1. Layout model (extend `bms_copybook_gen`)

One BMS model for the workspace.

- `BmsField` gains `row`, `col` (1-based; POS as `(line,col)` or zero-based buffer offset,
  resolved against map SIZE), `initial` (quotes stripped, doubled quotes un-escaped),
  `color`, `hilight`, `justify`.
- Unlabelled DFHMDF entries (captions) are kept with an empty label; the copybook generator
  skips them instead of the parser dropping them. Generated copybooks are byte-identical.
- `BmsMap` gains `size`, `ctrl` (FREEKB/FRSET/ALARM/PRINT flags) and `cursloc`.
- `cobble/cobble/bms_render.py` moves onto this model; its `ScreenField`/`ScreenMap` and the
  private `bms_metadata` imports are deleted. Cobble already imports `bms_copybook_gen`, which
  the `.importlinter` static surface allows.
- `MapCatalog`, indexed by `(mapset, map)`, loads `.bms` via `hlasm_export` once at region
  start. Lookup without a mapset succeeds only when the map name is unique; otherwise it is a
  loud error.

### 2. SEND MAP payload

Additive, JSON-serialisable; existing `screen["fields"][X]` assertions keep passing.

```
{"map": str, "mapset": str,
 "mode": "full" | "dataonly" | "maponly",
 "erase": bool, "freekb": bool, "alarm": bool,
 "cursor": {"kind": "none"} | {"kind": "offset", "at": int}
         | {"kind": "symbolic", "field": str},
 "fields": {BASE: text},
 "attrs":  {BASE: {"attr": int, "color": int, "hilight": int}}}
```

- Lowering now carries MAPSET, MAPONLY, DATAONLY, ERASE, CURSOR (with or without value),
  FREEKB, ALARM (closes the SEND MAP half of forge-qh5).
- `attrs` lists only fields whose `A`/`C`/`H` byte is non-NUL (program override of the layout).
- Cursor: `CURSOR(n)` → offset; bare `CURSOR` with a field whose `L` is `-1` → symbolic;
  otherwise none. Map CURSLOC/IC remain the layout default.
- MAPONLY reads no symbolic storage; DATAONLY sends only fields with non-NUL data.

**Cursor in the domain** is a closed union, never `None`:
`Cursor(offset: int) | SymbolicCursor(field: str) | NoCursor`. The payload's tagged dict is
parsed into it at the channel boundary.

### 3. `TerminalScreen`

Pure 24x80 model in cicada, no I/O.

- `apply(payload, layout)`: ERASE clears the buffer; `maponly` writes layout fields with
  INITIAL; `dataonly` writes sent data and attribute overrides onto existing fields; `full`
  does both. FRSET resets MDTs; a field with FSET gets MDT on.
- Field table per field: start address, attribute byte (protection, numeric, intensity/DRK,
  MDT), extended colour/highlight, content, base name (empty for captions).
- Cursor resolved to an offset: explicit offset, symbolic field start, map IC/CURSLOC, else 0.
- Readers: `text()` (24 lines, DRK blanked), `row(n)`, `field(base)`, `cursor`.
- `bms_render` can render from a `TerminalScreen` for docs; headless tests assert real
  positions through it.

### 4. RECEIVE MAP fidelity

- `InputEvent` gains `cursor: Cursor | NoCursor`, default `NoCursor`. Existing callers are
  unchanged; fields they omit are unmodified.
- For every base in the map: received → value into `<f>I` (numeric de-edit as today),
  `<f>L` = length, `<f>F` = `X'80'` when received empty (modified-then-cleared), else `X'00'`;
  not received → `<f>I` low-values, `<f>L` = 0, `<f>F` = `X'00'`.
- EIBCPOSN set from `Cursor`; left 0 for `NoCursor`.
- Applies equally to the blocking builtin and the conversational apply-input builtin (shared
  `_apply_input`).

### 5. `RegionDriver`

```
start() -> Turn
respond(event: InputEvent) -> Turn
Turn = AwaitingInput(screens) | Ended(screens, outcome)
outcome = Returned | Abended(abcode)
```

- `PseudoConversationalDriver` wraps `CicsRegion`: steps through XCTL without an event,
  stops at RETURN_TRANSID with `AwaitingInput`, passes events only on entry and after
  RETURN_TRANSID, drains the screen channel into `screens`. It encodes the rule headless tests
  currently apply by hand; new headless tests use it, existing ones may migrate.
- `ConversationalDriver` (later epic) satisfies the same protocol over `ConversationalRegion`.

### 6. `cics.tn3270` adapter

**Negotiation** — basic TN3270: `DO TERMINAL-TYPE` → `SB TERMINAL-TYPE SEND`; accept
`IBM-3278-2` or `IBM-3278-2-E`; `DO/WILL BINARY`, `DO/WILL EOR`; `WONT TN3270E` so emulators
fall back. Other models are refused with a clear message. `-E` enables SFE/extended attributes.

**Encoder** — `TerminalScreen` → record: command Erase/Write (`0xF5`) when the payload erased,
else Write (`0xF1`); WCC (reset MDT, unlock input for FREEKB, alarm); per field SBA + SF
(or SFE with colour/highlight on `-E`) + cp037 data; IC at the cursor; 12-bit buffer
addresses; `0xFF` doubled; `IAC EOR` terminator.

**Decoder** — record → `InputEvent`: AID byte, 2-byte cursor address → `Cursor`, then SBA +
data per modified field, mapped to base names through the screen's field table. Short-read
AIDs (PA1–3, CLEAR) carry no data; CLEAR also blanks the local `TerminalScreen`.

**`TerminalSession`** — blocking sockets, one connection:
1. negotiate;
2. `start()` the configured initial transid, or show a blank unformatted screen;
3. loop: apply each screen to `TerminalScreen`, encode, send; read an AID record, `respond`;
4. on `Ended`: no-task state; next ENTER parses the first word of the unformatted screen as a
   transid and starts it; `Abended` shows a one-line message with the abcode first.

**CLI** — `cicada-tn3270 --config carddemo.toml --port 3270`. TOML: source and copybook dirs,
BMS dir, transid→program table, VSAM seed, initial transid. Region construction reuses
`cics.bootstrap`.

**Import rules** — `cics.tn3270` is added to cobble's `cobble-no-runtime` forbidden list; a new
`forbidden` contract stops `cics.builtins`, `cics.dispatcher` and the `TerminalScreen`/driver
modules from importing `cics.tn3270`.

## Testing

TDD throughout; headless proof precedes wire proof.

- **Unit (no JVM):** layout parsing (POS forms, SIZE, INITIAL, captions, byte-identical
  copybooks); `TerminalScreen` merge rules, overrides, cursor resolution, MDT; encoder and
  decoder byte-exact against hand-built records, plus encode→decode round-trip; negotiation
  against a scripted socket pair; `PseudoConversationalDriver` turn logic with a fake region.
- **Headless integration (`carddemo_e2e`):** existing CardDemo tests pass unchanged; new tests
  drive through `PseudoConversationalDriver` + `TerminalScreen` and assert positioned text
  (sign-on captions, cursor on USERID), RECEIVE `L`/`F` bytes and EIBCPOSN.
- **Wire e2e (`tn3270_e2e`):** server on an ephemeral port, driven by `s3270`
  (`Connect`, `String`, `Tab`, `Enter`, `PF(3)`, `Ascii`): sign-on → menu → account view → PF3.
  Missing `s3270` fails loudly, matching the `carddemo_e2e` toolchain rule; README documents
  the install.
- `uv run lint-imports` covers the new contracts.

## Quality gates

Pyright and python-fp-lint are blocking pre-commit hooks. All new code passes both. Existing
code touched by this work (`bms_copybook_gen`, `cics/builtins/screen.py`, `cics/strategy.py`,
`cics/dispatcher.py`, `cobble/cobble/bms_render.py`, …) has its prior violations fixed in the
same change. Only code that genuinely must mutate — expected candidates are the socket loop
in `TerminalSession` and byte-buffer assembly in the encoder — may move to a small dedicated
module excluded via `fp.json`; that is the exception, justified per module, not the default.
`TerminalScreen.apply` returns a new screen rather than mutating.

`fp.json` currently excludes all of `cicada/cics/`. This work narrows that entry: each cicada
file touched leaves the exclusion (replaced by explicit per-file entries for untouched files),
gets its violations fixed, and only genuinely mutating modules stay excluded, each with its
own `exclude_why`.

## Docs and memory

- Replace the `cics-headless-only` beads memory: headless and TN3270 are both supported;
  headless remains first-class (`cics-headless-first-class`).
- Update `docs/presentation/artifacts/cics/FACTS.md` and the presentation's "no 3270
  datastream" limitation.
- Cicada README: `cicada-tn3270` usage, config, emulator connection.

## Order of work

One epic, sequential beads. Steps 1–5 improve headless fidelity on their own.

1. Layout model extension; cobble `bms_render` onto it.
2. SEND MAP payload: MAPSET, modes, attrs, cursor union.
3. `TerminalScreen`.
4. RECEIVE MAP fidelity: `L`/`F`, unreceived fields, EIBCPOSN.
5. `RegionDriver` + headless CardDemo tests on it.
6. Encoder and decoder.
7. Negotiation + `TerminalSession`.
8. CLI, config, s3270 e2e.
9. Docs and memory.

Follow-up epic: `ConversationalDriver` for conversational programs.
