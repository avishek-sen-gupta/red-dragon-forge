# jackal: Invalid Packed-Decimal Data Is Not Detected — Decision Record

**Date:** 2026-10-12
**Status:** accepted — won't fix for now (jackal-1o2.19, decision D1's fault half)
**Issues:** jackal-1o2.19; red-dragon-forge-13p (deferred)

What jackal does when a COBOL program does arithmetic on a packed-decimal (COMP-3) field whose
bytes are not valid packed decimal, the case z/OS ends with a data exception, S0C7.

## Finding

A one-step program redefines `PIC X(3) VALUE 'ABC'` as `PIC S9(5) COMP-3` and adds it to a
counter. On z/OS the `ADD` abends S0C7. Under jackal the step ends `Completed(0)`, with the sum
22232.

red-dragon decodes packed decimal in the IR its COBOL lowering emits. It extracts each nibble
and weights it by its power of ten. No step checks that a digit nibble is 0–9 or that the sign
nibble is a sign. `'ABC'` is `C1 C2 C3` in EBCDIC. The digit nibbles C 1 C 2 C become 122232,
which truncates to 22232. Nothing downstream can tell this value from a valid one, so jackal
cannot detect the fault after the run.

## Comparison: GnuCOBOL 3.2

The same program, compiled with `cobc` 3.2.0 on Debian:

| Compile | Result |
|---|---|
| `cobc -x` (default) | `AFTER ADD +41424`, exit 0: no check, as in red-dragon (the different value is ASCII `41 42 43` rather than EBCDIC) |
| `cobc -x -debug` | `libcob: BADPACK.cbl:9: error: 'NUM' (Type: PACKED-DECIMAL) not numeric: '0x414243'`, exit 1 |
| `cobc -x -fec=ALL` | the same error, exit 1 |
| `cobc -x -fec=DATA-INCOMPATIBLE` | the same error, exit 1 |

GnuCOBOL detects invalid packed data only when the `EC-DATA-INCOMPATIBLE` exception check is
compiled in. The check is code the compiler emits before the field is used, not a property of
its runtime.

## Decision

**P1. The check belongs in the lowered IR; it is not built now.** Detecting S0C7 needs the
COBOL lowering to emit a validity test before each packed-decimal decode, and to end the run
with a fault outcome when the test fails. jackal would then map that fault to
`Abended(SystemAbend(0x0C7))`. The VM needs no knowledge of packed decimal. This is filed as
red-dragon-forge-13p, deferred, and won't be fixed for now (user decision, 2026-10-12).

**P2. Until then, invalid packed data computes a value.** A job that would abend S0C7 on z/OS
runs to completion under jackal, and later steps run when z/OS would have flushed them. Any
comparison of jackal's results with z/OS's for such data has to allow for this.
