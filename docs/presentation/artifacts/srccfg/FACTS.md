# Source CFG (cobble srccfg) — facts (captured 2026-09-14, re-captured 2026-10-07)

Regenerate: `make cobble srccfg` in `docs/presentation` (srccfg.sh needs `cobble/out-parsed` from `cobble-parse-corpus` and the combine's `cobble/out-presentation/combined/targets.jsonl`, which cobble.sh writes).
Design: `cobble/docs/superpowers/specs/2026-09-04-src-cfg-reaching-conditions-design.md`.

## What it is
- A per-program control-flow graph built by walking cobble's cached ASG — no JVM, no compile, no corpus source (design doc "Nothing is compiled").
- Carries **reaching conditions** (the guards, with literals, that must hold to reach a node), **flow-sensitive def-use** (writers/readers per node) and **cross-program expansion** through `EXEC CICS LINK`/`XCTL` and COBOL `CALL`, seeded at one program (design doc "What this builds").
- CLIs (`cobble/pyproject.toml`): `cobble-srccfg-build` (closure), `cobble-srccfg-query {provenance|guards|coassign}`, `cobble-srccfg-dot`, `cobble-srccfg-webgl`.
- Why it exists (design doc "Why", measured on a production corpus): the older MOVE-only dependency graph has no control dependence, so a backward closure over one hub field reached 24,459 nodes (17% of the graph) and fields appearing only in guards were absent.

## What ran (CardDemo)
- `cobble-srccfg-build COSGN00C --dynamic-call-targets <combine targets.jsonl>` → closure of **22 programs, 6,996 CFG nodes, 9,249 edges within programs, 71 calls between them** (`summary.json`). COPAUS0C, COTRTLIC, COTRTUPC and CEEDAYS are external stubs (no source in the ASG cache). WebGL render reports 6,996 nodes / 9,320 edges, i.e. the within-program edges plus the call rows (`webgl-COSGN00C.txt`, `cfg-COSGN00C-webgl.png`).
- Without dynamic targets (2026-09-14 capture) the same closure was 3 programs and 365 nodes: COSGN00C + COADM01C + COMEN01C through sign-on's two literal `XCTL`s. The slides now show the dynamic closure only.
- `cobble-srccfg-build COACTVWC` (no dynamic targets: it is only queried within itself) → 408 nodes / 497 edges (`summary.json`).
- COSGN00C closure build 7.08s wall, COACTVWC 0.90s, both including `uv` start-up (`build-*.txt`).
- `cfg-COSGN00C-webgl.png`: headless-Chrome screenshot of `cfg-COSGN00C-webgl.html` (gitignored), by `capture/screenshot.sh`.
- `COSGN00C-READ-USER-SEC-FILE.png`: the READ-USER-SEC-FILE paragraph of the DOT output, filtered by the capture script (the full closure DOT is `cfg-COSGN00C.dot`).

## Queries
- **guards** (`guards-COSGN00C-xctl.txt`): 5 reaching paths each for `XCTL COADM01C` and `XCTL COMEN01C` (33 in the 2026-09-14 capture; the drop comes from cobble changes, not from the dynamic targets: a closure without them gives 5 too). Over the 22-program closure the query also prints "unreachable from <program> entry" for each of the other 21 programs. Path 0 of each differs only in the last conjunct: `CDEMO-USRTYP-ADMIN (CDEMO-USER-TYPE == A)` vs its negation, after `SEC-USR-PWD == WS-USER-PWD` and the non-blank USERIDI/PASSWDI checks.
- **provenance** (`provenance-COSGN00C-CDEMO-USER-ID.txt`, `--max-depth 2`): backward and forward in one walk; output repeats per program in the closure. The guard cap is no longer hit for COSGN00C; truncation shows as `(truncated at depth 2)`. CDEMO-USER-ID is written at `PROCESS-ENTER-KEY/2` under the listed guards; USERIDI, PASSWDI, EIBCALEN, EIBAID, DFHENTER are reported as sources written nowhere in the member; `%HANDLER[ANY]` as a synthetic origin.
- **coassign** (`coassign-COACTVWC-CC-ACCT-ID.txt`): 3 candidates at tier SAME_PARAGRAPH (FLG-ACCTFILTER-ISVALID, INPUT-OK, NO-SEARCH-CRITERIA-RECEIVED), with the caveat that guards at two nodes are a subset of the real ones so no tier-3 match is established.

## Honest limitations
- **Fixed before this capture**: `EVALUATE WS-RESP-CD WHEN 0` used to render as a bare `0` and `EVALUATE EIBAID WHEN DFHENTER` as `DFHENTER`, dropping the subject (`forge-dhz`, commit 7b347da1). The guards and DOT diamonds now read `WS-RESP-CD == 0`, `WS-RESP-CD == 13`, `EIBAID == DFHENTER`.
- Guard lists are capped; the tool prints `(guard cap hit: this list is incomplete)` rather than presenting a partial list as complete (`query.py` `CAP_NOTE`).
- Paths repeat `NOT (%HANDLER[ANY] RAISED)` conjuncts — the synthetic handler state is re-tested per CICS call; verbose but not wrong.
- Dynamic XCTL targets are expanded from the combine's `targets.jsonl`, candidates included, so the sign-on closure over-approximates what sign-on can reach.
- Known scale issue on large production members: reaching-conditions does not finish in 10 minutes (`red-dragon-forge-z8r`).
