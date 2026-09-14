# CICS online (cicada) — unmodified CardDemo flow: facts

Regenerate: `uv run --no-sync python docs/presentation/capture/cics_flow.py` (repo root), then
from `cobble/`: `uv run --no-sync python -m cobble.bms_render --config config/carddemo.toml --values ../docs/presentation/artifacts/cics/0*.json --format html|text --out-dir ../docs/presentation/artifacts/cics`.

## What ran
- Four unmodified CardDemo programs, compiled from `vendor/carddemo/app/cbl/`: COSGN00C, COMEN01C, COACTVWC, COCRDLIC — one shared CICS `CoprocessorSpec` (`cicada/cics/coprocessor.py` `build_cics_spec`, `cicada/cics/bootstrap.py` `compile_cics_program`). Compile times (s): 1.51 / 2.04 / 3.64 / 4.75 (`turns.jsonl` line 1).
- Symbolic map copybooks generated from `vendor/carddemo/app/bms/*.bms` via `hlasm_export` (`cicada/cics/bms/generate.py`), not the shipped `cpy-bms`.
- Transid→program: CC00→COSGN00C, CM00→COMEN01C, CAVW→COACTVWC, CCLI→COCRDLIC, as in `vendor/carddemo/app/csd/CARDDEMO.CSD`.
- VSAM seeded from CardDemo's shipped EBCDIC files (`vendor/carddemo/app/data/EBCDIC/`), unaltered: USRSEC (80B), ACCTDAT (300B), CUSTDAT (500B), CCXREF + CXACAIX alt-index on ACCT-ID @25 (50B), CARDDAT + CARDAIX alt-index @16 (150B) (`capture/cics_flow.py` `DATASETS`; seeding `cicada/cics/vsam/seed.py`).
- Driven turn by turn via `CicsRegion.start/step` (`cicada/cics/dispatcher.py`); routing (XCTL vs RETURN TRANSID) deduced from each `DispatchResult`, not scripted. Credentials USER0001/PASSWORD are that user's row in the shipped USRSEC data.
- Screens are the SEND MAP payloads written unchanged (`{"map","fields"}`, `cicada/cics/builtins/screen.py:114`); map names already equal DFHMDI names — no `--map` override needed.

## Turns (`turns.jsonl`; wall-clock per turn, excludes compile)
| # | Transid / program | Input | Result | Screen | VSAM | s |
|---|---|---|---|---|---|---|
| 1 | CC00 COSGN00C | none (EIBCALEN 0) | RETURN TRANSID CC00 | 01-COSGN0A | — | 0.027 |
| 2 | CC00 COSGN00C | ENTER USERID/PASSWD | XCTL COMEN01C | — | READ USRSEC `USER0001` NORMAL | 0.020 |
| 3 | CC00 COMEN01C | (XCTL, same task) | RETURN TRANSID CM00 | 02-COMEN1A (11 options) | — | 0.297 |
| 4 | CM00 COMEN01C | ENTER OPTION 01 | XCTL COACTVWC | — | — | 0.046 |
| 5 | CM00 COACTVWC | (XCTL) | RETURN TRANSID CAVW | 03-CACTVWA (empty prompt) | — | 0.071 |
| 6 | CAVW COACTVWC | ENTER ACCTSID 00000000001 | RETURN TRANSID CAVW | 04-CACTVWA (account + customer) | READ CXACAIX `00000000001` → READ ACCTDAT `00000000001` → READ CUSTDAT `000000001`, all NORMAL | 0.106 |
| 7 | CAVW COACTVWC | PF3 | XCTL COMEN01C | — | — | 0.055 |
| 8 | CAVW COMEN01C | (XCTL) | RETURN TRANSID CM00 | 05-COMEN1A | — | 0.076 |
| 9 | CM00 COMEN01C | ENTER OPTION 03 | XCTL COCRDLIC | — | — | 0.041 |
| 10 | CM00 COCRDLIC | (XCTL) | RETURN TRANSID CCLI | 06-CCRDLIA (page 1, 7 cards) | STARTBR CARDDAT, 8× READNEXT, ENDBR, all NORMAL | 0.159 |

- Script exhausted; exit 0; no ABEND. Full flow sign-on → menu → account view → PF3 → menu → card list.
- Account view values trace to data: balance `00000001940{` → `+194.00`, credit limit `00000020200{` → `+2,020.00` (signed zoned decimal → edit picture); names Immanuel/Madeline/Kessler, FICO 274 from CUSTDAT record 1 (`data/ASCII/custdata.txt` line 1).
- Card list rows are the first 7 CARDDAT keys in key order (`data/ASCII/carddata.txt`); 8th READNEXT is COCRDLIC's look-ahead for a next page.
- VSAM calls observed by wrapping `VsamEngine` in the capture script (`RecordingVsamEngine`); product code untouched.

## Supported EXEC CICS verb surface (`cicada/cics/strategy.py`)
- Program control: RETURN (±TRANSID/COMMAREA), XCTL, LINK, ABEND; START, RETRIEVE (`builtins/flow.py`, `builtins/interval.py`).
- BMS: SEND MAP, RECEIVE MAP, SEND TEXT (`_BMS_VERBS`, `builtins/screen.py`).
- File control: READ, WRITE, REWRITE, DELETE; STARTBR, READNEXT, READPREV, ENDBR (`_VSAM_POINT_VERBS`, `_VSAM_BROWSE_VERBS`, `builtins/vsam.py`).
- System: ASSIGN, ASKTIME, FORMATTIME, INQUIRE, WRITEQ TD, HANDLE ABEND, HANDLE CONDITION / IGNORE CONDITION, RESP/NOHANDLE → EIBRESP (`_SYS_VERBS`, `builtins/system.py`).
- Explicit no-ops: HANDLE AID, UNLOCK (single-task emulation) (`strategy.py:73-79`). Any other verb lowers to `__cics_abend_unsupported` — a loud ABEND, not a silent skip (`strategy.py:1302-1316`).

## Limitations (honest)
- **Wrong value on screen 04:** SSN renders `209-73-888`; CUST-SSN in the data is `020973888`, and COACTVWC builds it with `STRING CUST-SSN(1:3) '-' CUST-SSN(4:2) '-' CUST-SSN(6:4)` (`COACTVWC.cbl:496-504`), so the correct value is `020-97-3888`. Reference modification on this `PIC 9(09)` field appears to be shifted by one position. Not investigated or fixed here (a RedDragon issue).
- Rendered screens show field values only. Cursor position, attribute overrides (the programs' `…C/…H/…A` moves) and DATAONLY/MAPONLY are not in the payload, so they are not shown (`cobble/cobble/bms_render.py` docstring).
- `CURDATE`/`CURTIME` are the capture run's wall clock; APPLID/SYSID/USERID/PASSWD print as LOW-VALUES (NUL) in the JSON, blank on screen.
- The region pads each follow-on COMMAREA to 400 bytes (`min_commarea_len=400`, `dispatcher.py:305-311`) so EIBCALEN covers CARDDEMO-COMMAREA — a harness setting, same as the in-repo test.
- On PF3 (turn 7) COACTVWC exits without RECEIVE MAP; the driver discards the unconsumed input event (`input_left_unconsumed: true`). Real CICS discards it the same way.
- `CicsRegion` runs one terminal and one task at a time, with no real 3270 datastream: input arrives as `InputEvent(eibaid, fields)` (`dispatcher.py:34-39`).
- Timings are for the interpreted VM on a dev laptop, excluding JVM parse/compile. They are illustrative, not benchmarks.
- Not exercised here: card view/update, transaction list, and admin menu. The in-repo tests cover account update REWRITE and transaction add WRITE (`cicada/tests/integration/cics/test_carddemo_signon_real.py`) using synthetic seed records.
