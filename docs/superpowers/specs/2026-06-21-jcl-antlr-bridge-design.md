# jackal — JCL parser via ANTLR grammar behind a Java bridge — Design

**Status:** Designed (2026-06-21). Tracks `jackal-1o2.9` (foundation of epic `jackal-1o2`,
"broaden JCL execution coverage"). Spike completed (GO); awaiting user review of this spec.

## What this builds (plain terms)
Replace jackal's hand-written **Lark** JCL parser with a **mature, comprehensive ANTLR
grammar** (the MIT-licensed `cschneid-the-elder/mapa` JCL grammar), run in **Java behind a
subprocess bridge** — the same pattern red-dragon already uses to parse COBOL via
`proleap-bridge`. The bridge parses JCL and serializes a structured AST as JSON to stdout;
the Python side deserializes that JSON into jackal's **existing** frozen model
(`Job`/`Step`/`DD`). The hand-written Lark grammar is retired.

This is the *foundation* sub-project of the coverage epic: a thorough grammar makes
**parsing** a one-shot win, so every later feature (COND, GDG, PROC, DCB, …) becomes
**execution-semantics-only** work layered on an already-parsed model.

## Driver
jackal's Lark grammar covers only the slice v1/v2 needed (JOB/EXEC/DD/DISP/in-stream/
SYSOUT, with hand-rolled SYSIN extraction and a regex-free but narrow rule set). Growing it
feature-by-feature re-derives edge cases the mainframe world has already solved. The spike
(2026-06-21) proved mapa's grammar parses **38/38 CardDemo jobs with zero errors**, handles
**column sensitivity (cols 73–80) inside the lexer** (no 80-column pre-splitting), and parses
**in-stream/SYSIN natively** (no manual extraction). Adopting it — rather than hand-growing —
is the higher-leverage path.

## Decisions (settled during brainstorming)
- **Grammar:** `cschneid-the-elder/mapa` — `jcl/src/JCLLexer.g4` (5096L) + `JCLParser.g4`
  (1002L), start rule `startRule`, `tokenVocab=JCLLexer`. MIT, action-free (2 lexer-mode
  brace sites only). Rejected `grossvater/jcl-parser` (Apache-2.0 but action-heavy, needs a
  hand-written Java lexer, semantically thin).
- **Bridge ownership:** a **jackal-owned `jcl-bridge` Maven module inside the jackal repo**
  (built to a shaded JAR, a gitignored build product like proleap). Not extending
  red-dragon's vendored bridge (wrong ownership — JCL is jackal's concern, not the COBOL
  transpiler's). Not a standalone repo (single-consumer; needless release overhead).
- **Raw-parse-first:** run the main JCL grammar on raw source. mapa's separate **JCLPP**
  preprocessor (symbolic/INCLUDE expansion) is **out of scope here** — deferred to the PROC/
  symbolics sub-project (`jackal-1o2.2`) and INCLUDE/JCLLIB (`jackal-1o2.15`), where it earns
  its keep. The 38/38 clean spike result was on raw JCL.
- **Model unchanged:** the bridge produces jackal's *current* frozen model; `parse_jcl(text)
  -> Job` keeps its signature so callers/tests are unaffected.

## Scope

**In scope (`1o2.9`):**
- A `jcl-bridge` Maven module: vendored mapa `.g4` files (with attribution), ANTLR-generated
  parser, and a thin `JclSerializer` `main` that reads JCL (file arg or stdin), parses from
  `startRule`, and writes a projected JSON AST to stdout. Build → shaded JAR.
- A Python `JclBridgeParser` (`jackal/jcl/`) that invokes the JAR via subprocess (mirroring
  red-dragon's `RealSubprocessRunner` + `ProLeapCobolParser`), deserializes the JSON, and
  builds `Job`/`Step`/`DD`/`Disp`.
- The JSON serialization contract (below).
- Retiring `jackal/jcl/grammar.lark` and the Lark `Transformer`; keeping `parse_jcl`.
- Build wiring: a `make`/script target to build the JAR; an env var (`JCL_BRIDGE_JAR`) +
  CLI/config plumbing; the gated e2e and unit suite green on the new parser.
- **100% parse-behavior parity** with the retired Lark parser before merge.

**Out of scope (later sub-issues):**
- Executing any newly-parseable construct (COND/GDG/PROC/DCB/PARM/DUMMY/INCLUDE/…) — those
  are the other epic children; this task only makes them *parse* into the model.
- JCLPP preprocessing / symbolic substitution / INCLUDE expansion (→ `1o2.2`, `1o2.15`).
- Serializing the full mapa tree — we project to what jackal consumes today (forward-friendly).

## Architecture
```
parse_jcl(text)                                  ← unchanged public entry point
  └─ JclBridgeParser (jackal/jcl/, Python)
       └─ subprocess: java -jar jcl-bridge.jar  (stdin = raw JCL)
            └─ JclSerializer.main (Java)
                 └─ JCLLexer + JCLParser (mapa, ANTLR-generated)
                 └─ ParseTree → projected JSON  → stdout
       └─ JSON → Job / Step / DD / Disp (jackal.model)
```
Mirrors the COBOL path: `ProLeapCobolParser` → subprocess → proleap JAR → JSON → `CobolASG`.
Runtime needs `java` (already required for COBOL steps); only the *build* surface (Maven +
ANTLR) is new to jackal.

## Components
1. **`jcl-bridge/` (Maven module, Java).**
   - `pom.xml`: ANTLR4 plugin (generate lexer/parser from the vendored `.g4`), shade plugin
     (fat JAR with the ANTLR runtime).
   - `src/main/antlr4/.../JCLLexer.g4`, `JCLParser.g4`: vendored from mapa, **unmodified
     where possible**, with upstream `LICENSE`/provenance retained.
   - `JclSerializer.java`: `main` reads JCL from stdin (or a file arg), runs lexer+parser
     from `startRule`, walks the tree with a visitor that emits the **projected JSON**
     (below), prints to stdout. Parse errors → non-zero exit + diagnostic to stderr
     (fail loud).
2. **`jackal/jcl/bridge_parser.py` (Python).** `JclBridgeParser` (or fold into `parser.py`):
   invokes the JAR via an injected subprocess runner (test seam, mirroring red-dragon),
   parses stdout JSON, constructs the frozen model. Raises a clear `JclParseError` on
   non-zero exit / malformed JSON.
3. **`jackal/jcl/parser.py`.** `parse_jcl(text) -> Job` now delegates to `JclBridgeParser`.
   The Lark grammar + Transformer are deleted.
4. **Build/config.** A `make jcl-bridge` (or script) target builds the JAR; `JCL_BRIDGE_JAR`
   env var locates it (mirroring `PROLEAP_BRIDGE_JAR`); CLI/`JobRunner` plumb it through;
   `.gitignore` excludes the built JAR; conftest fixture asserts the JAR exists for tests
   that need it.

## JSON serialization contract (the crux)
The serializer **projects** mapa's rich tree down to exactly what jackal's model holds today,
keyed by stable names. Minimal v1 shape:
```json
{
  "name": "JOBNAME",
  "steps": [
    {
      "name": "STEP05",
      "pgm": "IDCAMS",
      "dds": [
        {
          "ddname": "SYSIN",
          "dsn": "",
          "disp": {"status": "SHR", "normal": "KEEP", "abnormal": "KEEP"},
          "in_stream": ["  DELETE ...", "  DEFINE ..."],
          "sysout": false
        }
      ]
    }
  ]
}
```
Rules:
- Map mapa rule nodes → these fields: `jobCard`→name; `execStatement`(PGM=)→step pgm;
  per-DD-parameter rules → `dsn`/`disp`/`sysout`; in-stream data nodes → `in_stream` lines.
- A step invoking a **PROC** (`EXEC PROC=`/`EXEC name`) — out of scope to *execute*, but the
  serializer should still emit the step with its pgm/proc name so parity holds for parsing;
  executing PROCs is `1o2.2`.
- **Forward-friendly:** later sub-issues ADD fields (`cond`, `dcb`, `parm`, `concatenations`,
  GDG/referback markers on `dsn`) without breaking v1 consumers. v1 emits only the modeled
  set; unmodeled constructs are omitted, not errored (they parse fine in Java; jackal just
  doesn't surface them yet).

## Error handling
- **Parse failure** in Java → `JclSerializer` exits non-zero with the ANTLR error(s) on
  stderr; Python raises `JclParseError` carrying that text. Fail loud — no silent fallback.
- **Missing/!built JAR** → clear error naming `JCL_BRIDGE_JAR` (mirror the COBOL bridge).
- **Malformed JSON** from the bridge → raise (a bridge bug must surface, not be swallowed).
- No `None` defaults; no defensive guards; the serializer projects deterministically.

## Testing (TDD)
- **Unit (Python):** `JclBridgeParser` deserializes representative JSON into the exact model
  — **reuse the existing `tests/unit/test_jcl_parser.py` cases** (same inputs, same expected
  `Job`/`Step`/`DD`) so parity is provable; a malformed-JSON / non-zero-exit case asserts
  `JclParseError`. Use the subprocess-runner seam to test deserialization without the JVM
  where possible, plus at least one real JAR-backed case.
- **Integration (gated, real JAR + CardDemo):** the existing `carddemo_e2e` test stays green
  on the new parser; **add a parse-parity sweep** that parses several CardDemo jobs
  (ACCTFILE, READACCT, TRANBKP, DEFGDGB) through the bridge and asserts the v2-modeled fields
  match what the Lark parser produced (or, post-deletion, asserts the expected structure).
- **Build test:** `make jcl-bridge` produces a JAR; a smoke test parses a one-line JOB.

## Binding constraints (carried from jackal v1/v2)
- **Real grammar, no regex parsing** — satisfied by ANTLR (a parser generator), as Lark was.
- **FP:** frozen model unchanged; functional core / imperative shell (subprocess in the shell).
- **No `None` defaults; no silent guards; fail loud.**
- **No external-codebase references in tracked artifacts** beyond the public AWS CardDemo
  sample (allowed) and the public MIT mapa grammar (attributed).
- TDD; Python 3.13+, uv, pytest, Black. Java/Maven added for the bridge module only.
- **Parity gate:** the new parser must reproduce 100% of current parse behavior (the full
  suite + the gated e2e green) before the Lark grammar is deleted/merged.

## Attribution / licensing
Vendoring mapa's `.g4` (MIT) requires retaining its `LICENSE` and a provenance note in
`jcl-bridge/`. Record the upstream repo + commit SHA pinned. MIT permits this with attribution.

## Risks & mitigations
- **JAR-build complexity / CI.** Mitigate: the JAR is a build product (like proleap);
  document the build target; pin the ANTLR version.
- **Serializer is the main new code surface.** Mitigate: keep the projection minimal (v1
  model only) and visitor-driven; add fields incrementally.
- **Grammar drift / unmodeled constructs.** mapa parses far more than jackal models; the
  projection deliberately ignores the surplus — safe, and the explicit growth path is "add a
  JSON field when a sub-issue needs it."
- **Subprocess-per-parse latency.** Already accepted for COBOL; JCL files are tiny.
- **Parity regressions.** The reuse-existing-tests + parity-sweep strategy is the safety net;
  do not delete the Lark grammar until parity is green.
