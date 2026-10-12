# jackal: IDCAMS Parses Through One Grammar, ams.lark — Decision Record

**Date:** 2026-10-12
**Status:** accepted (red-dragon-forge-tsw, red-dragon-forge-rqw)
**Issues:** red-dragon-forge-tsw; red-dragon-forge-rqw; supersedes the 2026-10-12 GDG record's G1
(grow the narrow grammar first)

jackal had two IDCAMS grammars. The executor ran on a narrow one (`idcams/grammar.lark`) that grew
one production per executed command. A comprehensive one (`idcams/grammar/ams.lark`) parsed every
command into a typed AST that nothing used. Of CardDemo's 61 IDCAMS inputs the narrow grammar
parsed 39 and the comprehensive one 55. The comprehensive grammar was a superset: no input parsed
only under the narrow one.

## Sources

| Key | Document |
|---|---|
| AMS | [z/OS 3.1 DFSMS Access Method Services Commands](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/idai200_v3r1.pdf) — "Commands", p. xxiv; "How to continue commands and parameters", p. xxvii; ch. 2 "Modal Commands", pp. 15–23; ch. 3 and each command's "Abbreviation:" entries |

## Decisions

**O1. ams.lark is the one IDCAMS grammar; the narrow grammar is deleted.** The executor parses
through it. Moving it is by user decision (2026-10-12), after the CardDemo batch cycle showed that
most IDCAMS failures were parse coverage: alternate indexes, paths, and DEFINE CLUSTER options.

**O2. ams.lark takes the narrow grammar's record model.** A record ends a command unless a `-` or
`+` continues it (AMS p. xxvii). The IF-THEN-ELSE rules of the 2026-10-12 modal record (V1, V2)
move with it: a THEN or ELSE that ends its record is a null command, and each ELSE takes the
nearest unmatched THEN. Until now ams.lark treated a line end as a blank, which loses both rules.

**O3. `+` continuation is lexical, in the grammar.** AMS p. xxvii: "A plus sign continues both the
command and a value within the command." The terminals that can be split this way accept a `+`,
the rest of its record and the next record's leading blanks inside them. The transformer drops
those characters from the token's text. This replaces a regex pass over the input text.

**O3a. Separators and margins are IBM's.** AMS p. xxiv: "Commands are separated from their
parameters by one or more separators (blanks, commas, or comments)", so a comma is a blank
everywhere, not only where a rule lists one. AMS p. xxiv: "For batch processing jobs, the default
margins are 2 and 72." Each SYSIN record is read from column 2 to column 72. A sequence number in
columns 73 to 80 is not part of the command. jackal does not model the MARGINS parameter.

**O4. Every command and parameter name accepts its IBM abbreviation.** AMS gives one for nearly
every name, for example `DEF`, `CL`, `AIX`, `GDG`, `VFY`, `CISZ`, `RECSZ` and `TRK`. ams.lark had
none, which is why CREASTMT's `CISZ(4096)` and DUSRSECJ's DEFINE failed. The abbreviations come
from the "Abbreviation" entries in AMS.

**O5. The AST models what the executor runs (user decision, 2026-10-12).** The transformer builds
the typed commands in `idcams.commands`, holding only the parameters execution reads. The other
parameters of an executed command fall in two kinds:
- Storage and performance parameters (space, VOLUMES, CISZ, FREESPACE, SHAREOPTIONS, BUFFERSPACE,
  ERASE, SPEED, WRITECHECK, the SMS classes, OWNER, CATALOG and the like) do not change what jackal
  computes, so they are parsed and dropped.
- Any other parameter changes what the command does. A command that codes one jackal does not
  model is `NotExecuted`, never run with that parameter silently ignored. Examples are REPRO's
  `COUNT` or `SKIP`, and DEFINE CLUSTER's `MODEL`.

The classification is a table from grammar rule to kind, so a newly modelled parameter moves out of
it. A command jackal does not execute at all (LISTCAT, PRINT, ALTER, EXPORT, IMPORT, DEFINE
NONVSAM, and DEFINE AIX, DEFINE PATH and BLDINDEX until they are executed) is also `NotExecuted`.

**O5a. A KSDS that omits KEYS or RECORDSIZE takes IBM's defaults.** AMS ch. 14 gives KEYS(64 0)
and RECORDSIZE(4089 4089) as the defaults, or RECORDSIZE(4086 32600) when SPANNED is coded.
SPANNED therefore changes what a define means and is not modelled. Either value may be coded on the
cluster or in its `DATA(...)`, and the cluster level is read first.

**O6. A command that is not executed ends with condition code 12.** AMS p. 22 gives 12 for "The
program could not perform requested function". Using it for a command jackal parsed but does not
run is **jackal's own** choice, as for VERIFY of a non-VSAM dataset (record V6). The command's
name is kept so the step's log says what was skipped.

**O7. The comprehensive AST modules, their transformer and their tests are deleted.** They modelled
every parameter of 14 commands as optional `None` fields assembled from untyped keyword
dictionaries: 343 Pyright errors and 772 fp-lint violations, with no consumer. The lean
transformer replaces them, typed and checked like the rest of jackal.
