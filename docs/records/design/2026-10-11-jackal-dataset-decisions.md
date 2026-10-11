# jackal: Datasets, Labels and Dispositions — Decision Record

**Date:** 2026-10-11
**Status:** decided; implemented in part (see each decision)
**Issues:** red-dragon-forge-xkk, -w0e, -93f, -8in, -9po; red-dragon-lc7c, red-dragon-1hc3

Decisions taken with the user while building jackal's job-level model. Each z/OS behaviour is
quoted from IBM's documentation, current edition (z/OS 3.1) unless stated, and checked word
for word against the source. Decisions with no z/OS counterpart are marked **jackal's own**.

## Sources

| Key | Document |
|---|---|
| JCL | [z/OS 3.1 MVS JCL Reference, SA23-1385](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/ieab600_v3r1.pdf) — DD DISP, pp. 149–156, Table 17 |
| UDS | [z/OS 3.1 DFSMS Using Data Sets](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/idad400_v3r1.pdf) — pp. 25, 286–287, 309–311, 319, 530 |
| FTP | [z/OS 3.1 Communications Server IP User's Guide and Commands](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/halu001_v3r1.pdf) — pp. 62, 82–83 |
| IEC141I | [IEC141I message, return code 34](https://www.ibm.com/docs/en/zos/3.1.0?topic=messages-iec141i) |
| S806 | [System completion code 806](https://www.ibm.com/docs/en/zos/3.1.0?topic=codes-806) |
| S322 | [System completion code 322](https://www.ibm.com/docs/en/zos/3.1.0?topic=codes-322) |
| TEMP | [z/OS 2.4 MVS JCL User's Guide, "Temporary data sets"](https://www.ibm.com/docs/SSLTBW_2.4.0/com.ibm.zos.v2r4.ieab500/iea3b5_Temporary_data_sets.htm) |
| OS390 | [OS/390 V2R10 MVS JCL Reference, GC28-1757-09](https://www.informatik.uni-leipzig.de/cs/Literature/Textbooks/jcl/MvsJclReference.pdf) — superseded wording, see D11 |
| CD | `vendor/carddemo/README.md`, "Upload Sample Data" |

## Program outcomes

**D1. A program jackal cannot find abends `S806`, or is stubbed when lenient** (xkk, done).
S806: "The system could not find the module, whose entry point is the value of the EP or EPLOC
operand, in the indicated library (private library, job library, or link library)." Strict mode
gives `Abended(SystemAbend(0x806))`; lenient mode, the CLI's, gives `Completed(0)` with a
warning (**jackal's own**: tolerance of missing code, one injected strategy).

**D2. A COBOL program that outruns its step budget abends `S322`** (w0e, done). S322: "The
system took a longer time to run a job or job step than the time specified in … The TIME
parameter of the EXEC or JOB statement [or] The standard time limit specified in the job entry
subsystem." The budget is per program, `JobRunner`'s `program_step_budget` (**jackal's own**
stand-in for a CPU limit). red-dragon reports exhaustion as a typed `BudgetExhausted` run
outcome (red-dragon-lc7c) rather than an exception.

## Dataset labels (8in, designed; 93f stores them)

**D3. Variable-length records are stored with inline RDWs; blocking is not modelled.** UDS
p. 286: "The record descriptor word is a 4-byte field describing the record. The first 2 bytes
contain the length (LL) of the logical record (including the 4-byte RDW)… All bits of the third
and fourth bytes must be 0, because other values are used for spanned records." BDWs are
omitted, as `BLKSIZE` is.

**D4. The record codec lives in jackal, behind its I/O provider** (**jackal's own**). Record
framing is the runtime's business; the COBOL program reads and writes a record area. The one
language-level piece — a `RECORD VARYING … DEPENDING ON` record's true length — belongs to
red-dragon (red-dragon-1hc3).

**D5. No Forge runtime accepts an unlabelled dataset.** On z/OS a dataset's attributes exist
from allocation. UDS p. 530: "Each data set on a direct access volume has one or more DSCBs to
describe its characteristics. The DSCB appears in the VTOC and … contains … data set
characteristics." Data entering from outside is labelled on the way in. FTP p. 82: "When
allocating new data sets … You can individually use the storage attribute parameters with the
SITE and LOCSITE subcommands or the hlq.FTP.DATA data set"; p. 62: "The default values for the
site parameters are coded in the server FTP.DATA file." CardDemo's own install step declares
each file's format (CD: e.g. `AWS.M2.CARDDEMO.ACCTDATA.PS`, FB, 300). Some step — declaration
or inference — must therefore always build a label; jackal never guesses one from the first
program to open a file.

**D6. A dataset a job creates is labelled at its first `OPEN OUTPUT`, by the DCB merge; with
nothing to merge from, the open fails `S013`.** UDS pp. 309–311: "A DD statement takes priority
over a data set label, and a DCB macro over both"; "From the JFCB, OPEN fills in any field not
completed in the DCB or DCBE"; "All DCB fields are then unconditionally merged into
corresponding JFCB fields if your data set is opened for output … The open routines use the
updated JFCB … to write the DASD data set labels." IEC141I return code 34 includes "QSAM,
LRECL=0, and a RECFM value that is not V or VB" and "QSAM and BLKSIZE=0. No nonzero BLKSIZE
value was available from any source and the system could not determine one." With SMS, a data
class may also supply attributes (UDS p. 319: "the ACS routines assign a data class to the data
set"); how an installation chooses one is its own configuration, so jackal has none.

**D7. Labels are held by jackal's catalog** — the roles of z/OS's VTOC and catalog combined —
not in sidecar files or a separate manifest. UDS p. 25: "The VTOC lists the data sets that
reside on its volume, along with … other data set attributes"; "A catalog describes data set
attributes and indicates the volumes on which a data set is located." Implemented in 93f:
`catalog.json` holds each entry's label.

## The system catalog (93f)

**D8. A persistent system directory; data enters by copy; runs change it in place.** Bringing a
dataset in (`jackal catalog add`) copies its bytes into the system directory with its label, as
an upload creates a dataset on a volume; jobs never touch the original. A run changes the
system for later runs. `--data-dir` and `--dataset` are removed. (**jackal's own** shape; the
z/OS behaviour it models is D5 and D9.) Done: commit e9cb457.

**D9. Dispositions follow SMS.** JCL p. 151: "For new SMS-managed data sets, KEEP implies
CATLG"; "With SMS, UNCATLG is ignored for SMS-managed data sets and VSAM data sets (KEEP is
implied)." UDS p. 25: "All system-managed DASD data sets are cataloged automatically." So jackal
catalogs every non-temporary dataset a job creates unless it is deleted. Done: e9cb457.

**D10. A lenient stand-in for a missing dataset is cataloged like a created one and follows its
DISP as the dataset it stands in for** (**jackal's own**; user's choice over a job-scoped
stand-in). It resolves its DISP as an existing dataset, so `DISP=SHR` keeps it. Done with 9po.

**D11. `PASS`: a dataset the job created and passed, never disposed of later, is deleted at end
of job.** JCL Table 17, "NEW permanent data set or MOD treated as new", normal disposition
`PASS`: "passed … At End of Job: deleted" (abnormal ends: the third subparameter's disposition).
SMS changes this only for existing VSAM: JCL p. 152, "With SMS, the system replaces PASS with
KEEP for existing VSAM data sets." Done: commit 1c791a3; "created" means the dataset did not
exist at allocation, so `MOD` treated as new counts (9po).

*Correction:* the OS/390 edition read "With SMS, the system replaces PASS with KEEP for
permanent VSAM and non-VSAM data sets" (OS390, p. 12-84). On that superseded text a plan to
treat `PASS` as `KEEP` for every permanent dataset was proposed on this date and dropped once
the current edition was read.

## Omitted dispositions (9po)

**D12. An omitted DISP subparameter is recorded as omitted, and defaulted once it is known
whether the dataset existed.** JCL p. 153, Defaults: "If you omit the normal termination
disposition subparameter, the default is DELETE for a NEW data set or KEEP for an existing data
set. If you omit the abnormal termination disposition subparameter, the default is the
disposition specified or implied by the second subparameter. However, if the second
subparameter specified PASS, the default abnormal termination disposition is DELETE for a NEW
data set or KEEP for an existing data set." Whether a `MOD` dataset is new depends on existence,
not on what was coded — JCL p. 149: "If the system cannot find volume information for the data
set on the DD statement, in the catalog, or passed with the data set from a previous step, the
system assumes that the data set is being created in this job step." The parser keeps
`Omitted()`; the catalog decides at allocation whether it found or created the dataset; the
resolved disposition travels with the allocation to disposal.

*Correction:* this issue was first filed claiming an omitted normal disposition on a received
passed dataset defaults to `PASS`. Table 17 shows such a dataset (old status, no normal
disposition) is kept; the claim was wrong.

**D13. Temporary datasets** (unchanged; recorded for completeness). JCL p. 154: "For a temporary
data set, the system ignores any abnormal termination disposition specified in the third
subparameter and processes the data set according to the normal termination disposition." TEMP:
"If the DISP parameter for a temporary data set specifies KEEP or CATLG, the system changes the
disposition to PASS and deletes the data set at job termination."
