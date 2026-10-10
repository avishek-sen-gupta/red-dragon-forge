# JCL object model, unit 2: the bridge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The JCL bridge reads every construct in the acceptance fixtures without losing or distorting any of it, and emits a JSON contract that mirrors the blueprint's parsed model; Python reads it through Pydantic wire models and still builds today's `jackal.model`.

**Architecture:** Two commits. First, lexer and grammar fixes in `jackal/jcl-bridge` for the five constructs that fail to parse today, each pinned by a Java test, with the old JSON contract unchanged. Second, `JclSerializer.JobBuilder` emits the new contract below; `jackal/jcl/wire.py` holds its Pydantic models; `bridge_parser.py` validates with `model_validate_json` and maps wire models onto today's model, so nothing past the deserializer changes yet.

**Tech Stack:** Java 17, ANTLR 4 (vendored mapa grammar), Gson, JUnit 4, Maven; Python 3.13, Pydantic 2, pytest.

**Spec:** `docs/superpowers/specs/2026-10-10-jackal-jcl-object-model-build-design.md` (§5, §6 "Wire models", §7 unit 2); blueprint `docs/superpowers/specs/2026-10-10-jackal-job-level-domain-model-design.md` §4.

## Global Constraints

- jackal parses JCL by grammar, never by regex: a new surface feature is a grammar production plus a serializer case.
- `vendor/red-dragon` is never modified. The grammar copy is `jackal/jcl-bridge/src/main/antlr4`.
- `make jar` does not rebuild on Java-only changes (`jackal-231`): rebuild with `cd jackal/jcl-bridge && mvn -q -DskipTests package` after every Java change, and run Java tests with `mvn -q test`.
- Text is a boundary: bridge JSON becomes Pydantic models via `model_validate_json`; no dict indexing past that line.
- No names from any external corpus in fixtures, tests or messages (guidelines/data-security.md).
- Talisman: anything it flags in this unit is asked about before `.talismanrc` changes; the earlier approval covers unit-1 files only.
- The CardDemo snapshot test stays green; every difference is listed in `EXPECTED_CHANGES` with its issue.

## Review Focus

1. A DCB model name with one qualifier that begins with a DCB subparameter name (`DCB=MODEX`): the new lexer rule needs a dot, so this form still fails; it must fail loudly, not misparse.
2. COND with only `EVEN` or `ONLY` inside parentheses (`COND=(EVEN)`): read as the mode, not as a test.
3. An IF expression mixing AND and OR without parentheses: evaluated left to right with equal precedence (JCL Reference), not AND-before-OR.
4. A PROC call with both `COND=` and `COND.P1=`, and an override DD after `//P2.X` with no qualifier: every override reaches the wire in statement order with its qualifier split out.
5. A symbol followed by two periods (`&HLQ..X`): exactly one period is dropped, never both.

## The wire contract

Every object below is a JSON object; Gson writes fields in insertion order, and order does not matter to the reader. `""` in a `label` means an unnamed step: JCL itself leaves the name field blank.

```
Document  = JobDoc | ProcDoc                      (by "kind")
JobDoc    = {kind:"job",  name, end_job_tests:[RcComparison], statements:[Statement]}
ProcDoc   = {kind:"proc", name, defaults:[SymbolValue], statements:[Statement]}

Statement = Program | ProcCall | IfBlock          (by "kind")
Program   = {kind:"program", label, pgm, parm:[Part], cond:Cond, dds:[Dd]}
ProcCall  = {kind:"proc_call", label, proc,
             symbol_overrides:[SymbolValue],
             parm_overrides:[{procstep, parm:[Part]}],
             cond_overrides:[{procstep, cond:Cond}],
             dd_overrides:[{procstep, dd:Dd}]}      procstep "" = unqualified
IfBlock   = {kind:"if", label, condition:Expr, then:[Statement], otherwise:[Statement]}

SymbolValue  = {name, value:[Part]}
Part         = {kind:"literal", text} | {kind:"symbol", name}
Cond         = {tests:[CondTest], mode:Mode}       Mode: NORMAL, EVEN or ONLY
CondTest     = {code:int, op:Op, target:Target}    Op: GT, GE, EQ, NE, LT or LE
RcComparison = {code:int, op}
Target       = {kind:"all_prior"} | {kind:"step", step} | {kind:"proc_step", call, step}

Dd     = {ddname, dsn:Dsn, disp:[str], in_stream:[str], sysout:bool, concatenated:[Member]}
Member = {dsn:Dsn, disp:[str], in_stream:[str]}
Dsn    = {kind:"name", value:[Part]} | {kind:"temp", name}        name without "&&"
       | {kind:"backref", target:Target, ddname}
       | {kind:"in_stream"} | {kind:"dummy"} | {kind:"none"}

Expr = {kind:"rc", target:Target, op, code:int}
     | {kind:"abend", target:Target} | {kind:"run", target:Target}
     | {kind:"abend_code", target:Target, abend:{kind:"system"|"user", code:int}}
     | {kind:"not", operand:Expr} | {kind:"and"|"or", operands:[Expr]}
```

Rules the bridge applies, each from the JCL Reference:

- A period directly after a symbol ends the symbol and is dropped: `&HLQ..X` is `[symbol HLQ, literal ".X"]`.
- `DSN=&&NAME` is `temp`; `DSN=NULLFILE` and `DD DUMMY` are `dummy`; `DD *` and `DD DATA` are `in_stream` with their cards; `SYSOUT=` with no DSN is `none` with `sysout: true`.
- `*.S1.DD` is a backref to `step S1`; `*.S1.P1.DD` to `proc_step S1/P1`.
- A COND step name `S1.P1` is `proc_step`; no step name is `all_prior`.
- IF: `NG` is `LE`, `NL` is `GE`; `ABEND = FALSE` and `RUN = FALSE` are `not`; `ABENDCC = Sxxx` is a system code read as hex, `Uxxxx` a user code read as decimal; `RC`, `ABEND`, `ABENDCC` without a step are `all_prior`. NOT binds tightest; AND and OR have equal precedence and are read left to right; a chain of one operator is one n-ary node.
- An unnamed DD after a named one is a member of it (`concatenated`), with its own DSN, DISP and cards.

Applying the unqualified-DD-override rule is the Python side's job (spec §5), in unit 3; this unit keeps qualifiers as they are.

## Mapping onto today's model (this unit only)

`bridge_parser.py` keeps today's results for everything CardDemo uses:

- `Program` → `Step(label, pgm, dds, conds, parm)`; a `Cond` whose mode is not `NORMAL` raises `ValueError` (today: `CondOp("EVEN")` raised).
- `ProcCall` → `Step(label, proc, dds, conds, parm, proc_parms)`: `dds` are the override DDs, with ddname `P2.OUT` when qualified; `conds`/`parm` are the unqualified `COND=`/`PARM=` overrides, if any; `proc_parms` are the symbol overrides.
- `IfBlock` → its `then` statements, then its `otherwise` statements, flattened as today.
- `Dd.concatenated` is dropped, as today. `temp` → `TempRef("&&" + name)`. `backref` to `proc_step` raises `ValueError` (jackal-lz8, as today). `in_stream`, `dummy`, `none` as today.
- `Target` on a COND test → `Cond.step` `"S1"`, `"S1.P1"` or `""`.

## File structure

- Modify `jackal/jcl-bridge/src/main/antlr4/org/jackal/jcl/JCLLexer.g4` — DCB dataset-name rules, `NOT` in IF mode, hidden JOB-card comma-newline.
- Modify `jackal/jcl-bridge/src/main/antlr4/org/jackal/jcl/JCLParser.g4` — compound JOB COND, empty PARM/COND value.
- Modify `jackal/jcl-bridge/src/main/java/org/jackal/jcl/JclSerializer.java` — the new contract.
- Create `jackal/jcl-bridge/src/test/java/org/jackal/jcl/ParseFixesTest.java`, `ContractTest.java`.
- Modify the existing Java tests that read the old contract.
- Create `jackal/jackal/jcl/wire.py`; rewrite `jackal/jackal/jcl/bridge_parser.py`.
- Modify the Python tests that hand-build bridge JSON (`jackal/tests/unit/test_jcl_bridge_deserialize.py`, `test_jcl_bridge_parser.py`, `test_parm.py`, `cobble/tests/...` where they do).
- Modify `jackal/tests/acceptance/carddemo_facts.py` (`EXPECTED_CHANGES`), `docs/reference/jackal/architecture.md`.

---

### Task 1: Lexer and grammar fixes

**Files:** the two `.g4` files; `ParseFixesTest.java`.

**Interfaces:** Consumes `JclSerializer.serialize(String) -> JsonObject` (old contract). Produces a grammar that accepts the five constructs.

- [ ] **Step 1: Write the failing Java test**

```java
package org.jackal.jcl;

import com.google.gson.JsonObject;
import org.junit.Test;
import static org.junit.Assert.assertEquals;

/** Constructs the grammar rejected, each of which lost the whole job. */
public class ParseFixesTest {

    private static JsonObject job(String... lines) {
        return JclSerializer.serialize(String.join("\n", lines) + "\n");
    }

    private static int steps(JsonObject job) {
        return job.getAsJsonArray("steps").size();
    }

    @Test
    public void aDcbModelNameStartingWithAKeywordParses() {
        assertEquals(2, steps(job(
                "//J JOB (A),CLASS=A",
                "//S1 EXEC PGM=X",
                "//A DD DSN=T.A,DCB=T.MODEL",
                "//B DD DSN=T.B,DCB=(CODES.X,RECFM=FB,LRECL=80)",
                "//C DD DSN=T.C,DCB=(DENX.Y)",
                "//S2 EXEC PGM=Y")));
    }

    @Test
    public void aJobCondWithTwoTestsParses() {
        assertEquals(2, job(
                "//J JOB (A),CLASS=A,COND=((8,LE),(12,EQ))",
                "//S1 EXEC PGM=X").getAsJsonArray("cond").size());
    }

    @Test
    public void anEmptyParmOrCondOverrideParses() {
        assertEquals(4, steps(job(
                "//J JOB (A),CLASS=A",
                "//S1 EXEC P,PARM.P1=''",
                "//S2 EXEC P,PARM.P1=,COND.P2=(4,LT)",
                "//S3 EXEC P,PARM=''",
                "//S4 EXEC P,COND=")));
    }

    @Test
    public void theWordNotInAnIfParses() {
        assertEquals(2, steps(job(
                "//J JOB (A),CLASS=A",
                "//S1 EXEC PGM=X",
                "//T1 IF NOT S1.ABEND THEN",
                "//S2 EXEC PGM=Y",
                "// ENDIF")));
    }

    @Test
    public void aQuotedOnlyPositionalFollowedByAContinuationParses() {
        assertEquals("J1", job(
                "//J1 JOB 'EXTRACT TRAN',",
                "//  CLASS=A",
                "//S1 EXEC PGM=X").get("name").getAsString());
    }
}
```

- [ ] **Step 2: Run it** — `cd jackal/jcl-bridge && mvn -q test -Dtest=ParseFixesTest`. Expected: five failures, each a `SyntaxErrorException` (and `NumberFormatException`/size mismatch for the JOB COND case).

- [ ] **Step 3: Lexer — DCB model names.** In both DCB lexer modes, after the newline rule, add a rule that reads a dotted dataset name as one value token. A dotted name is longer than any DCB subparameter name, so ANTLR's longest match prefers it; a subparameter never has a dot before its equals sign.

```antlr
DCB_DATASET_NAME
	: NM_PART? (DOT_DFLT+ NM_PART)+
	->type(KEYWORD_VALUE)
	;
```

(`DCB_PAREN_DATASET_NAME` is the same rule in `DCB_PAREN_MODE`.)

- [ ] **Step 4: Lexer — NOT.** In `IF_MODE`, `IF_NOT : NOT_SYMBOL_DFLT | (N O T) ->type(NOT_SYMBOL) ;` (it already precedes `IF_ALNUMNAT`, which wins ties otherwise).

- [ ] **Step 5: Lexer — JOB comma-newline.** `JOB_ACCT1_MODE_COMMA_NEWLINE` gains `channel(HIDDEN)`, as `JOBGROUP_ACCT1_COMMA_NEWLINE` has.

- [ ] **Step 6: Parser — JOB COND and empty overrides.**

```antlr
jobParmCOND : COND EQUAL (
    (LPAREN parenList (COMMA parenList)* RPAREN) |
    parenList
  ) ;

execParmPARM : EXEC_PARM EQUAL singleOrMultipleValue? ;
```

and in `execParmCOND` make the value after `EQUAL` optional. Then `buildJobCond` already collects leaf `parenList`s; it keeps working.

- [ ] **Step 7: Rebuild and run** — `mvn -q test` (the whole Java suite). Expected: green, including the five. If `PARM=''` still fails, dump tokens (scratchpad `Tok.java`) and rule on the smallest lexer change.

- [ ] **Step 8: Rebuild the JAR and run the Python suites** — `mvn -q -DskipTests package`, then `cd jackal && uv run --no-sync python -m pytest -q` and `cd cobble && uv run --no-sync python -m pytest -q`. Expected: jackal green with the acceptance xfails unchanged (they still fail on missing model names) and the CardDemo snapshot test green except where a job that was a parse error now parses: z76 turns `app-transaction-type-db2`'s job from unread to read. List it in `EXPECTED_CHANGES` against `red-dragon-forge-z76`.

- [ ] **Step 9: Commit** — `fix(jcl-bridge): DCB model names, compound JOB COND, empty overrides, NOT, quoted JOB continuation`. Close `2cy.2`, `2cy.14`, `z76` and note `2cy.11` (part 1) and `2cy.12` progress in the commit; export issues.

### Task 2: The new contract, end to end

**Files:** `JclSerializer.java`, `ContractTest.java`, existing Java tests; `wire.py`, `bridge_parser.py`; Python tests that hand-build JSON; `carddemo_facts.py`; `architecture.md`.

**Interfaces:**
- Consumes: the Task 1 grammar.
- Produces: `jackal.jcl.wire` — `JobDoc`, `ProcDoc`, `Document` (a discriminated union on `kind`), and every model named in the contract above, each a frozen Pydantic model; `bridge_parser.job_from_bridge_json(out: str) -> Job` and `JclBridgeParser.parse/parse_proc` unchanged in signature.

- [ ] **Step 1: Write `ContractTest.java`** — one test per contract rule, each asserting the exact JSON (compared with `JsonParser.parseString(expected)`) for a small JCL snippet: a program step with PARM, COND (tests + mode, `EVEN` between tests, `S1.P1` target); a PROC call with symbol, PARM (bare and qualified, empty), COND (bare and qualified) and DD (bare, qualified, bare after qualified) overrides; every DSN kind (name with a symbol and the dropped period, temp, both backref forms, `DD *`, `DD DATA` with cards, `DUMMY`, `NULLFILE`, `SYSOUT`); a three-member concatenation with an in-stream member; the `if/if.jcl` and `if/terms.jcl` structures; a PROC document with defaults; the JOB `end_job_tests`.

- [ ] **Step 2: Run it** — `mvn -q test -Dtest=ContractTest`. Expected: every test fails (old contract).

- [ ] **Step 3: Rewrite `JobBuilder`** — statements from the ordered children of `execJCL`/`procJCL` (`jclStep`, `ifStatement`, `elseStatement`, `endifStatement`), nested with a stack of open IF frames; `buildExecCond` replaced by a token walk that reads parenthesised groups as tests and bare `EVEN`/`ONLY` as the mode; IF expressions by recursive descent over the flat children of `ifStatement`; DDs folded per the contract, with `ddStatementConcatenation` children as members; value parts with the period rule.

- [ ] **Step 4: Run the whole Java suite** — `mvn -q test`. Expected: green, after updating the existing tests that read `steps`/`disp_words`/`cond` to the new field names (their assertions keep their meaning).

- [ ] **Step 5: Write `wire.py`** and rewrite `bridge_parser.py` on it, per "Mapping onto today's model". Rewrite the hand-built JSON in the Python unit tests to the new contract, keeping each assertion.

- [ ] **Step 6: Rebuild the JAR; run jackal, cobble and the root suite** — expected green; the CardDemo snapshot lists only intended changes (the dropped period changes the DSN text of jobs whose PROCs use `&HLQ..X` names; each is listed against this unit).

- [ ] **Step 7: Commit** — `feat(jcl-bridge): a JSON contract that mirrors the parsed model`, docs in the same commit; close `2cy.3`, `2cy.7`, `2cy.11`, `2cy.12`, `2cy.13` (bridge halves) with a note that the model halves land in units 3–4; export issues.
