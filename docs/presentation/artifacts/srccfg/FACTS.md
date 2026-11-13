# Source CFG (cobble srccfg) — facts (captured 2026-09-14, re-captured 2026-10-07; queries re-captured 2026-11-13)

Regenerate: `make cobble srccfg` in `docs/presentation` (srccfg.sh needs `cobble/out-parsed` from `cobble-parse-corpus` and the combine's `cobble/out-presentation/combined/targets.jsonl`, which cobble.sh writes).
Design: `cobble/docs/superpowers/specs/2026-09-04-src-cfg-reaching-conditions-design.md`.

## What it is
- A per-program control-flow graph built by walking cobble's cached ASG — no JVM, no compile, no corpus source (design doc "Nothing is compiled").
- Carries each test as a TEST node with a TRUE and a FALSE edge, **flow-sensitive def-use** (writers/readers per node) and **cross-program expansion** through `EXEC CICS LINK`/`XCTL` and COBOL `CALL`, seeded at one program (design doc "What this builds").
- CLIs (`cobble/pyproject.toml`): `cobble-srccfg-build` (closure), `cobble-srccfg-query {provenance|coassign}`, `cobble-srccfg-dot`, `cobble-srccfg-webgl`. Reaching conditions are `cobble-experimental-reaching-conditions` (`docs/reference/cobble/horn.md`), which reads the program's ASG.
- Why it exists (design doc "Why", measured on a production corpus): the older MOVE-only dependency graph has no control dependence, so a backward closure over one hub field reached 24,459 nodes (17% of the graph) and fields appearing only in conditions were absent.

## What ran (CardDemo)
- `cobble-srccfg-build COSGN00C --dynamic-call-targets <combine targets.jsonl>` → closure of **22 programs, 6,996 CFG nodes, 9,249 edges within programs, 71 calls between them** (`summary.json`). COPAUS0C, COTRTLIC, COTRTUPC and CEEDAYS are external stubs (no source in the ASG cache). WebGL render reports 6,996 nodes / 9,320 edges, i.e. the within-program edges plus the call rows (`webgl-COSGN00C.txt`, `cfg-COSGN00C-webgl.png`).
- Without dynamic targets (2026-09-14 capture) the same closure was 3 programs and 365 nodes: COSGN00C + COADM01C + COMEN01C through sign-on's two literal `XCTL`s. The slides now show the dynamic closure only.
- `cobble-srccfg-build COACTVWC` (no dynamic targets: it is only queried within itself) → 408 nodes / 497 edges (`summary.json`).
- COSGN00C closure build 7.08s wall, COACTVWC 0.90s, both including `uv` start-up (`build-*.txt`).
- `cfg-COSGN00C-webgl.png`: headless-Chrome screenshot of `cfg-COSGN00C-webgl.html` (gitignored), by `capture/screenshot.sh`.
- `COSGN00C-READ-USER-SEC-FILE.png`: the READ-USER-SEC-FILE paragraph of the DOT output, filtered by the capture script (the full closure DOT is `cfg-COSGN00C.dot`).

## Queries
- **reaching conditions** (`reaching-conditions-COSGN00C-xctl.txt`, `cobble-experimental-reaching-conditions` on `cobble/out-parsed/COSGN00C.json`, 2026-11-13): **1 way** each to `XCTL COADM01C` and `XCTL COMEN01C`, nothing dropped. The decisions are `EIBCALEN == 0` FALSE, `EIBAID == DFHENTER` TRUE, `ERR-FLG-ON (WS-ERR-FLG == 'Y')` FALSE, `WS-RESP-CD == 0` TRUE, `SEC-USR-PWD == WS-USER-PWD` TRUE, and `CDEMO-USRTYP-ADMIN (CDEMO-USER-TYPE == 'A')` TRUE for the admin menu, FALSE for the user menu. The four blank-input tests (`USERIDI`/`PASSWDI` against `SPACES`/`LOW-VALUES`) are "if it runs: FALSE", and three `%HANDLER[ANY] RAISED` tests "never runs on this way". The line numbers in the file are of the ASG's expanded source, not the `.cbl`. The unchecked `guards` query this replaces (2026-10-07 capture, removed) listed 5 paths to each menu; 4 of them took a blank-input test TRUE, which sets the error flag the way needs FALSE.
- **provenance** (`provenance-COSGN00C-CDEMO-USER-ID.txt`, `--max-depth 2`, on a closure rebuilt 2026-11-13 into a scratch directory, the committed `cfg-*.jsonl` predating the current CFG row schema): backward and forward in one walk; output repeats per program in the closure. Each step is its node and verb, with no conditions. CDEMO-USER-ID is written at `PROCESS-ENTER-KEY/2` from USERIDI and at `READ-USER-SEC-FILE/1.when.0.0.then.2` from WS-USER-ID; truncation shows as `(truncated at depth 2)`.
- **coassign** (`coassign-COACTVWC-CC-ACCT-ID.txt`, same rebuild): 3 candidates at tier SAME_PARAGRAPH (WS-EDIT-ACCT-FLAG, WS-INPUT-FLAG, WS-RETURN-MSG).

## Honest limitations
- **Fixed before this capture**: `EVALUATE WS-RESP-CD WHEN 0` used to render as a bare `0` and `EVALUATE EIBAID WHEN DFHENTER` as `DFHENTER`, dropping the subject (`forge-dhz`, commit 7b347da1). The tests and DOT diamonds now read `WS-RESP-CD == 0`, `WS-RESP-CD == 13`, `EIBAID == DFHENTER`.
- Ways are capped at 64 per node; the output says so when cut.
- Every Z3 query runs under a 180-second limit. On sign-on each takes under a second; on COACTUPC's account REWRITE the first way's check ran to the limit, and the output then marks the way "solver gave up".
- Dynamic XCTL targets are expanded from the combine's `targets.jsonl`, candidates included, so the sign-on closure over-approximates what sign-on can reach.
