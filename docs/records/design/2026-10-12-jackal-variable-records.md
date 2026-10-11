# jackal: Variable-Length Records on Disk — Decision Record

**Date:** 2026-10-12
**Status:** implemented (red-dragon-forge-8in, step 3)
**Issues:** red-dragon-forge-8in; red-dragon-1hc3 (upstream, open)
**Follows:** [IDCAMS REPRO and Dataset Labels](2026-10-12-jackal-idcams-repro-labels.md)

How jackal stores and reads a RECFM=V or VB dataset. Each rule is quoted from IBM's
documentation.

## Sources

| Key | Document |
|---|---|
| UDS | [z/OS 3.1 DFSMS Using Data Sets](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/idad400_v3r1.pdf) — "Record descriptor word (RDW)", p. 287 |
| PG | [Enterprise COBOL for z/OS 6.4 Programming Guide, SC27-8714-03](https://publibfp.dhe.ibm.com/epubs/pdf/igy6pg40.pdf) — ch. 9, "Processing QSAM files" p. 167, "Updating QSAM files" p. 178 |
| LR | [Enterprise COBOL for z/OS 6.4 Language Reference, SC27-8713-03](https://publibfp.dhe.ibm.com/epubs/pdf/igy6lr40.pdf) — Table 34, "File status key values and meanings", p. 302 |

## Decisions

**V1. Each variable-length record is stored behind its RDW.** UDS p. 287: "A variable-length
logical record consists of a record descriptor word (RDW) followed by the data. The record
descriptor word is a 4-byte field describing the record. The first 2 bytes contain the length
(LL) of the logical record (including the 4-byte RDW) … All bits of the third and fourth bytes
must be 0, because other values are used for spanned records." jackal writes exactly that,
big-endian. There are no block descriptor words: jackal does not model blocks, so V and VB are
stored alike (as F and FB are).

**V2. A reader gets each record at its own length.** UDS p. 287: "For input, the operating
system provides the RDW". REPRO copies each record at its own length. A COBOL READ gets the
record padded to the FD's record area, because red-dragon moves whatever the provider returns
into that area; the bytes past a short record are unspecified on z/OS. When red-dragon passes a
`RECORD VARYING … DEPENDING ON` length through the provider (red-dragon-1hc3), COBOL will see
the true length too. Until then a COBOL WRITE frames the full record area, as before.

**V3. A REWRITE must keep the record's length; otherwise file status 44.** PG p. 178: "Replace
an existing record with another record of the same length"; PG p. 167: "After you have created a
record, you cannot change its length". LR Table 34, status 44: "an attempt was made to rewrite a
record to a file and the record was not the same size as the record being replaced." red-dragon
reports this as `AccessCondition.BOUNDARY_VIOLATION` → `"44"`. cicada maps it to `RESP_IOERR`
**(jackal's own)**: only this driver produces it, cicada's file control never uses the driver,
and that is cicada's rule for driver conditions a CICS program cannot reach.

**V4. The label chooses the driver** **(jackal's own)**. A dataset labelled V or VB opens
through jackal's variable-record driver, everywhere: a COBOL OPEN (through red-dragon's
overridable `RealFileIOProvider._driver`) and IDCAMS. Every other label opens red-dragon's
fixed-length drivers, as before.
