# jackal: LIKE and REFDD Label a New Dataset — Decision Record

**Date:** 2026-10-12
**Status:** accepted (red-dragon-forge-fjr)
**Issues:** red-dragon-forge-fjr; follows the 2026-10-12 DCB record (A1–A8)

How jackal labels a new dataset whose DD codes `LIKE=dsname` or `REFDD=*.ddname`. These are the
SMS counterparts of `DCB=dsname` and `DCB=*.ddname` (record A3). Neither vendored corpus codes
them. Each rule is quoted from IBM's documentation.

## Sources

| Key | Document |
|---|---|
| JCL | [z/OS 3.1 MVS JCL Reference](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/ieab600_v3r1.pdf) — "LIKE parameter", pp. 208–210; "REFDD parameter", pp. 238–240; override rules, p. 75 |

## Decisions

**L1. LIKE copies a cataloged model's organization and record length, a KSDS's included.** JCL
p. 208: LIKE copies "the allocation attributes of a new data set by copying the attributes of a
model data set, which must be an existing cataloged data set", among them "Record organization
(RECORG) or Record format (RECFM)", "Record length (LRECL)", "Key length (KEYLEN)" and "Key offset
(KEYOFF)".
A sequential model gives its RECFM and LRECL, as `DCB=dsname` does.
A KSDS model gives a KSDS label with the model's LRECL and key.
The DCB form does not do that, since a VSAM dataset has no DCB label to copy. A model not in the
catalog fails allocation with `DATASET_NOT_FOUND`, as record A6 rules for `DCB=dsname`.

**L2. LRECL and RECFM coded on the same DD override what LIKE copied.** JCL p. 209: "Any
attributes you specify on the same DD statement with the following parameters override the
corresponding attributes obtained from the model data set", LRECL and "RECORG (record
organization) or RECFM (record format)" among them. A KSDS model with LRECL coded keeps its key
and takes the coded length. With RECFM coded, the new dataset is sequential, labelled from its
RECFM and LRECL as record A3 describes.

**L3. REFDD copies the RECFM and LRECL coded on the referenced DD, never its dataset's label.**
JCL p. 239: the attributes come "from (1) the attributes specified on the referenced DD
statement, and (2) for attributes not specified on the referenced DD statement, from the data
class", and "REFDD does not copy DCB attributes from the data set label". jackal copies (1)
exactly as it copies `DCB=*.ddname`, with the referencing DD's own coded attributes taking
precedence. It models no data classes, so (2) contributes nothing. The three referback forms are
those of DSN and DCB, the same-step `*.ddname` among them.

**L4. LIKE and REFDD are their own parameters on override.** An override DD changes each only
where it codes it (JCL p. 75), independently of `DCB=`, and `LIKE=` or `REFDD=` with no value
nullifies it. Where a DD codes both `DCB=dsname` and LIKE, the DCB model is used. JCL p. 210 says
not to code LIKE with REFDD.

**L5. A referback in REFDD or in DCB is checked like one in DSN.** One that names no step or DD
is an unresolved reference, which the runner's `UnresolvedReferenceStrategy` settles (record D7).
Before this, an unresolved `DCB=*.step.dd` went unnoticed and only left the new dataset's label
pending.
