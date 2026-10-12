# jackal: A Dynamic CALL Reaches Programs on the Link List — Decision Record

**Date:** 2026-10-12
**Status:** accepted (red-dragon-forge-ua7)
**Issues:** red-dragon-forge-ua7; red-dragon-forge-xzw (a target not in the run unit);
red-dragon-forge-btr (a link list derived from cobble's analysis)

How a COBOL step reaches a program it CALLs by data-name (`CALL WS-PGM`).

## Sources

| Key | Document |
|---|---|
| PG | [Enterprise COBOL for z/OS 6.4 Programming Guide](https://www.ibm.com/docs/en/cobol-zos/6.4.0?topic=calls-when-use-dynamic-call-subprograms), "When to use dynamic calls with subprograms" |
| LR | [Enterprise COBOL for z/OS 6.4 Language Reference](https://www.ibm.com/docs/en/cobol-zos/6.4.0?topic=statements-call-statement), "CALL statement" |

## Finding

PG: "CALL identifier is always dynamic, even if you use the NODYNAM compiler option", and "The
program object that you want to dynamically call must be in an MVS load library". z/OS loads it
when the CALL runs, so any member of the step's library can be the target.

red-dragon dispatches a CALL by data-name at run time, but only to a program linked into the run
unit before the run starts. Linking follows `CALL 'literal'` edges, so a program named only by a
data item's contents is never compiled, and the CALL fails.

## Decisions

**L1. A step's run unit holds its program, the programs it CALLs by literal, and the runner's link
list.** jackal's source directory stands in for the load library. Linking all of it into every
step would be faithful, but it compiles every member for every step, which is too slow for a
large codebase. The link list (`JobRunner(linked_programs=…)`, CLI `--link PGM …`) names the
members a dynamic CALL may reach. Each is compiled into every COBOL step through red-dragon's
`compile_program(linked_subprogram_sources=…)`, and its FILE-CONTROL entries are mapped to the
step's DDs like any callee's. Choosing the members by hand is **jackal's own** choice, made by the
user as the simpler start. Deriving the list from cobble's dynamic-call analysis is
red-dragon-forge-btr.

**L2. A link list naming a program with no source is refused before any job runs.** The runner
raises `LinkedProgramNotFound`, and the CLI reports it as a usage error. A typo in the list
would otherwise surface only when some CALL failed to reach the program.

**L3. A dynamic CALL to a program outside the run unit is not modelled yet.** LR: the
`ON EXCEPTION` phrase runs "When the called subprogram cannot be made available". Without that
phrase z/OS abends the step. Under jackal, red-dragon's `UnresolvedProgramError` ends the run
instead (red-dragon-forge-xzw).
