# jackal: A COBOL OPEN and the Dataset's Label — Decision Record

**Date:** 2026-10-11
**Status:** implemented (red-dragon-forge-8in, step 2a)
**Issues:** red-dragon-forge-8in; red-dragon-03sk, red-dragon-p98c
**Follows:** [Datasets, Labels and Dispositions](2026-10-11-jackal-dataset-decisions.md)

How a COBOL program's `OPEN` meets a dataset's label. Each rule is quoted from IBM's
documentation and checked against it.

## Sources

| Key | Document |
|---|---|
| LR | [Enterprise COBOL for z/OS 6.4, RECORDING MODE clause](https://www.ibm.com/docs/en/cobol-zos/6.4.0?topic=entries-recording-mode-clause) |
| PG | [Enterprise COBOL for z/OS 6.4 Programming Guide, SC27-8714-03](https://publibfp.dhe.ibm.com/epubs/pdf/igy6pg40.pdf) — ch. 9 "Processing QSAM files", pp. 183–185 |
| UDS | [z/OS 3.1 DFSMS Using Data Sets](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/idad400_v3r1.pdf) — "Filling in the DCB", pp. 309–311 |

## Decisions

**E1. The program's record format is derived from its FD, by the compiler's rule.** LR: with
`RECORDING MODE` omitted, the compiler selects F when "you either use the RECORD CONTAINS
clause or omit the RECORD clause with all level-01 records identical in size without OCCURS
DEPENDING ON", and V when you "use RECORD IS VARYING, omit the RECORD clause with
varying-length records, or use RECORD CONTAINS with differing minimum/maximum values". A coded
`RECORDING MODE F` or `V` is taken as written. red-dragon exposes the FD's `RECORDING MODE` and
`RECORD` clause (red-dragon-03sk); jackal applies the rule (`jackal.record_format`).

**E2. A variable format's dataset LRECL is the program's maximum record plus 4.** PG Table 21:
for V or S, the program's maximum record length is "Exactly 4 bytes less than the length
attribute of the data set"; for F, the "Same value".

**E3. An existing dataset whose label contradicts the FD fails the OPEN with file status 39.**
PG p. 183: "Mismatches in the attributes for file organization, record format (fixed or
variable), record length, or the code set result in file status code 39 and the failure of the
OPEN statement." jackal compares organization (a sequential FD against a KSDS, or an indexed FD
against a sequential dataset), fixed against variable, and length. Blocking (`F` vs `FB`) is not
compared: jackal does not model blocks. red-dragon reports the condition as
`AccessCondition.ATTRIBUTE_CONFLICT` → `"39"` (red-dragon-p98c). The program is not overridden;
the merge's precedence (UDS: "A DD statement takes priority over a data set label, and a DCB
macro over both") fills only fields that are unset, and a COBOL FD always sets these.

**E4. A dataset with a pending label is labelled from the FD at its first `OPEN OUTPUT` or
`EXTEND`.** PG p. 183: when COBOL creates the file, "the file attributes that are coded in your
program are used"; UDS p. 310: fields are "merged into corresponding JFCB fields if your data set
is opened for output … The open routines use the updated JFCB … to write the DASD data set
labels." An `OPEN INPUT` or `I-O` writes no label.

**E5. `RECORD CONTAINS 0` takes its length from the dataset.** PG p. 184: "If you intend to use
the same program to process different files at run time, and those files have differing fixed
lengths, avoid record-length conflicts by coding RECORD CONTAINS 0." Such an FD is not compared,
and it labels nothing: with a pending label there is no length to write, so the label stays
pending.

**E6. `RECORDING MODE U` and `S` are refused** (**jackal's own**). LR: U has "only one record for
each block"; S records "can be larger than a block". Both are block-level formats and jackal
does not model blocks, so a program declaring either is refused with `UnsupportedRecordingMode`
rather than run on an approximation.
