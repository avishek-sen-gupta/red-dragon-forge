# Source CFG (cobble srccfg) — facts (captured 2026-09-14)

Regenerate: `bash docs/presentation/capture/srccfg.sh` (repo root; needs `cobble/out-parsed` from `make parse`).
Design: `cobble/docs/superpowers/specs/2026-09-04-src-cfg-reaching-conditions-design.md`.

## What it is
- A per-program control-flow graph built by walking cobble's cached ASG — no JVM, no compile, no corpus source (design doc "Nothing is compiled").
- Carries **reaching conditions** (the guards, with literals, that must hold to reach a node), **flow-sensitive def-use** (writers/readers per node) and **cross-program expansion** through `EXEC CICS LINK`/`XCTL` and COBOL `CALL`, seeded at one program (design doc "What this builds").
- CLIs (`cobble/pyproject.toml`): `cobble-srccfg-build` (closure), `cobble-srccfg-query {provenance|guards|coassign}`, `cobble-srccfg-dot`, `cobble-srccfg-webgl`.
- Why it exists (design doc "Why", measured on a production corpus): the older MOVE-only dependency graph has no control dependence, so a backward closure over one hub field reached 24,459 nodes (17% of the graph) and fields appearing only in guards were absent.

## What ran (CardDemo)
- `cobble-srccfg-build COSGN00C` → closure of 3 programs (`summary.json`): COSGN00C 104 nodes / 137 edges, COADM01C 124 / 174, COMEN01C 137 / 188 — expanded through sign-on's two `XCTL`s. WebGL render reports 365 nodes / 501 edges for the closure (`cfg-COSGN00C-webgl.html`).
- `cobble-srccfg-build COACTVWC` → 411 nodes / 523 edges; node kinds ASSIGN 180, TEST 86, NOP 71, LABEL 37, CALL 37. Its XCTL targets are held in variables, so the closure is the program alone.
- Each build ~1.4–1.9s wall including `uv` start-up (`build-*.txt`).
- `COSGN00C-READ-USER-SEC-FILE.png`: the READ-USER-SEC-FILE paragraph of the DOT output, filtered by the capture script (the full closure DOT is `cfg-COSGN00C.dot`).

## Queries
- **guards** (`guards-COSGN00C-xctl.txt`): 33 reaching paths each for `XCTL COADM01C` and `XCTL COMEN01C`. Path 0 of each differs only in the last conjunct: `CDEMO-USRTYP-ADMIN (CDEMO-USER-TYPE == A)` vs its negation, after `SEC-USR-PWD == WS-USER-PWD` and the non-blank USERIDI/PASSWDI checks.
- **provenance** (`provenance-COSGN00C-CDEMO-USER-ID.txt`, `--max-depth 2`): backward and forward in one walk. CDEMO-USER-ID is written at `PROCESS-ENTER-KEY/2` under the listed guards; USERIDI, PASSWDI, EIBCALEN, EIBAID, DFHENTER are reported as sources written nowhere in the member; `%HANDLER[ANY]` as a synthetic origin.
- **coassign** (`coassign-COACTVWC-CC-ACCT-ID.txt`): 3 candidates at tier SAME_PARAGRAPH (FLG-ACCTFILTER-ISVALID, INPUT-OK, NO-SEARCH-CRITERIA-RECEIVED), with the caveat that guards at two nodes are a subset of the real ones so no tier-3 match is established.

## Honest limitations
- **Fixed before this capture**: `EVALUATE WS-RESP-CD WHEN 0` used to render as a bare `0` and `EVALUATE EIBAID WHEN DFHENTER` as `DFHENTER`, dropping the subject (`forge-dhz`, commit 7b347da1). The guards and DOT diamonds now read `WS-RESP-CD == 0`, `WS-RESP-CD == 13`, `EIBAID == DFHENTER`.
- Guard lists are capped; the tool prints `(guard cap hit: this list is incomplete)` rather than presenting a partial list as complete (`query.py` `CAP_NOTE`).
- Paths repeat `NOT (%HANDLER[ANY] RAISED)` conjuncts — the synthetic handler state is re-tested per CICS call; verbose but not wrong.
- Dynamic XCTL targets (variables) are not expanded, so COACTVWC's and COMEN01C's fan-out is not in a closure.
- Known scale issue on large production members: reaching-conditions does not finish in 10 minutes (`red-dragon-forge-z8r`).
