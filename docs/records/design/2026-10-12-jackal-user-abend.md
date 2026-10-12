# jackal: A COBOL User Abend through CEE3ABD — Decision Record

**Date:** 2026-10-12
**Status:** accepted (jackal-1o2.19; settles decision D4 of the 2026-10-10 domain-model spec, §16)
**Issues:** jackal-1o2.19

How a COBOL program ends its step with a user abend by calling Language Environment's CEE3ABD.

## Sources

| Key | Document |
|---|---|
| LE | [z/OS 3.1 Language Environment Programming Reference](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/ceea300_v3r1.pdf) — "CEE3ABD—Terminate enclave with an abend", pp. 111–112 |

## Decisions

**U1. CEE3ABD is a COBOL stub that jackal links like any CALLed program.** LE p. 111: "CEE3ABD
requests that Language Environment terminate the enclave with an abend … There is no return from
this service". The syntax is `CEE3ABD(abcode, clean-up)`. jackal ships `jackal/le_stubs/CEE3ABD.cbl`,
last on the CALL search path. The stub records `abcode` in its own WORKING-STORAGE and ends the
run unit with `STOP RUN`. red-dragon has no notion of an abend, and needs none (user direction,
2026-10-12: do the work in CEE3ABD itself, and have it leave a trace at a known location).
`clean-up` controls dumps, condition handlers and exits, which jackal does not model.

**U2. jackal reads the trace from the finished VM.** The stub's field starts at -1, which means
"not called". After a completed run, a different value in CEE3ABD's WORKING-STORAGE makes the
step `Abended(UserAbend(code))`. jackal reaches that storage through red-dragon's lowering
conventions: the `__prog_CEE3ABD` global, then the program object's `ws_handle`. A generic VM
API cannot find one COBOL program's storage without knowing how COBOL is lowered. The user
accepted reading those internals (2026-10-12). `test_user_abend` is the guard: a rename upstream
fails it.

**U3. A bare `CALL 'CEE3ABD'` abends U0000.** IBM documents only the two-parameter call. With no
parameters, the stub reads an unbound argument as 0. Abending with code 0 is **jackal's own**
outcome. CardDemo writes this form in its `9999-ABEND-PROGRAM` paragraphs, where the intent is
to abend.

**U4. A user abend is an abend like any other.** It is the outcome `IF ABENDCC=Unnnn` tests, and
the one that flushes later steps that test nothing about abends. It renders as `Unnnn`. jackal
now has one `SystemAbend` and one `UserAbend` type, shared by outcomes and IF tests. Before
this, the outcome side carried its own copy of `SystemAbend`.

ILBOABN0, the older COBOL abend routine, is in no IBM manual consulted here and in no corpus
jackal has seen, so it is not modelled.
