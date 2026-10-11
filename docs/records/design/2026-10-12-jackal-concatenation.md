# jackal: DD Concatenation — Decision Record

**Date:** 2026-10-12
**Status:** implemented (jackal-1o2.5)
**Issues:** jackal-1o2.5; red-dragon-forge-2cy.3 (the parser keeps every member);
red-dragon-forge-2dz (REPRO from a concatenation); red-dragon e802efc7 (status 37), 1336c032

How jackal allocates, reads and disposes a DD followed by unnamed DDs. Each rule is quoted from
IBM's documentation.

## Sources

| Key | Document |
|---|---|
| Ref | [z/OS 3.1 MVS JCL Reference, SA23-1385-60](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/ieab600_v3r1.pdf) — "Concatenating data sets", pp. 91–92 |
| UDS | [z/OS 3.1 DFSMS Using Data Sets](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/idad400_v3r1.pdf) — "Concatenating Data Sets Sequentially", "Concatenating Like Data Sets", pp. 369–370 |
| LR | [Enterprise COBOL for z/OS 6.4 Language Reference, SC27-8713-03](https://publibfp.dhe.ibm.com/epubs/pdf/igy6lr40.pdf) — Table 34, file status 37, p. 301 |

## Decisions

**K1. Members are read in order as one sequential dataset; end of file comes after the last.**
Ref p. 91: "When data sets are concatenated, the application program can treat them as if they
were one logical data set … The data sets are processed in the same sequence as the DD
statements defining them." UDS p. 369: "your program is open to only one of the data sets at a
time", and end-of-data passes to the program "only if the last data set in the concatenation
has been processed." jackal opens each member when the previous one ends.

**K2. Each member is allocated and disposed with its own DISP.** Each concatenated DD statement
carries its own DSN and DISP (Ref p. 91: "omit the ddnames from all the DD statements except
the first"). If a member fails allocation, the DD fails, and members the step had already
created are deleted, as for any failed DD.

**K3. A concatenation cannot be opened for output; the OPEN fails with file status 37.** Ref
p. 91: "Restriction: You cannot concatenate output data sets." LR Table 34, status 37: "An OPEN
statement was attempted on a file that would not support the open mode specified … The EXTEND
or OUTPUT phrase was specified but the file would not support write operations." Mapping that
restriction to status 37 is **jackal's own**; IBM does not name the outcome. I-O is refused the
same way.

**K4. Every member must fit the program like the first; a later V member may be shorter.** Ref
p. 91: "For like concatenation, the same logical record length (LRECL) value and record format
apply to all the data sets." Ref p. 92: "Concatenated data sets with format-V records can have
different logical record lengths as long as the data set with the largest logical record length
appears first." UDS p. 369 has the rest processed "with the record format of the first data
set". z/OS finds a mismatch only on reaching that member (UDS p. 370: "an open failure (ABEND
013-60) occurs when EOV switches to the concatenated data set"); jackal checks every member at
the OPEN and fails it with file status 39 **(jackal's own)**, as for a single dataset whose label
contradicts the FD. An in-stream member is 80-byte fixed records; a DUMMY member has no label to
check. jackal reads only like concatenations; COBOL does not ask for unlike processing.

**K5. A backward reference to a concatenation names its first dataset.** Ref p. 92: "If you
make a backward reference to a concatenation (using *.), the system obtains information only
from the first data set defined in the sequence of DD statements." jackal already copied only
the first DSN.

**K6. VSAM is not concatenated** (UDS p. 369: "Rule: You cannot concatenate VSAM data sets").
jackal does not check for it: an indexed file over a concatenation reads as sequential members.
