# jackal: DD DCB Attributes and Model Datasets — Decision Record

**Date:** 2026-10-12
**Status:** accepted (jackal-1o2.12)
**Issues:** jackal-1o2.12; red-dragon-forge-2cy.2 (the bridge parses `DCB=dsname`); 14l (REPRO into
a pending output)

How a DD's DCB attributes, coded directly or copied from a model, become a dataset's label. Each
rule is quoted from IBM's documentation.

## Sources

| Key | Document |
|---|---|
| Ref | [z/OS 3.1 MVS JCL Reference, SA23-1385-60](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/ieab600_v3r1.pdf) — "Additional rules for modifying DD parameters", p. 75; "DCB parameter", pp. 126–129 |
| UDS | [z/OS 3.1 DFSMS Using Data Sets](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/idad400_v3r1.pdf) — "Creating a Model DSCB", p. 482 |
| PG | [Enterprise COBOL for z/OS 6.4 Programming Guide](https://publibfp.dhe.ibm.com/epubs/pdf/igy6pg40.pdf) — "Opening QSAM files", p. 177 |

## Decisions

**A1. A DD carries RECFM, LRECL and a model, however they are coded.** Ref p. 127: "All of
the DCB keyword subparameters can be specified without the need to code DCB=". `RECFM=FB` and
`DCB=RECFM=FB` are therefore the same attribute. The model is the positional subparameter. It
is either `dsname`, "a cataloged data set. The system is to copy DCB information from the data
set's label", or `*.ddname`/`*.stepname.ddname`, which copies "DCB information from the DCB
parameter specified on that DD statement". jackal does not model blocks, buffers or devices, so
BLKSIZE, BUFNO, DSORG, OPTCD and the rest are parsed and dropped.

**A2. The values are kept as written until symbols are substituted, then parsed.** `LRECL=&LR`
has no value until its procedure is expanded. That is the one boundary such a value may cross
as text.

**A3. A new dataset is labelled at allocation from its DD's attributes over its model's
label.** Ref p. 128: "If you code any DCB subparameters after the dsname, these subparameters
override the corresponding subparameters in the data set label. The system copies from the
referenced label only those subparameters not specified on the referencing DD statement." UDS
p. 482 shows that allocation records these attributes in the label even when the dataset is
never opened. A GDG's model is built by a DD with `SPACE=(TRK,(0))` and
`DCB=(applicable subparameters)`, "Because only the attributes in the data set label are used".
jackal labels the dataset when RECFM and LRECL are both known. Otherwise the label stays
pending and the first `OPEN OUTPUT` labels it from the FD, as before.

**A4. A program whose FD contradicts those attributes fails its OPEN with status 39.** PG
p. 177: an OPEN works if "The fixed file attributes coded in the ddname definition or the
data-set label for the file match the attributes coded for that file in the SELECT clause and FD
entry. Mismatches in the file-organization attributes, code set, maximum record size, or record
format (fixed or variable) result in file status code 39". The check is the one jackal already
applies to a label.

**A5. RECFM keeps fixed or variable, and blocked or not.** A label is F, FB, V or VB. `A` and
`M` (control characters in the record) and `S` (standard or spanned blocks) do not change the
records jackal stores, so they are dropped: `FBA` labels FB, `VBS` labels VB. `U` and `D` have
no jackal label; a DD coding them leaves the label pending. **jackal's own**, as for RECORDING
MODE U (2026-10-11 record, E6).

**A6. A model that is not cataloged fails the allocation with `DATASET_NOT_FOUND`.** Ref p. 128:
`dsname` "Names a cataloged data set". The missing-data strategy settles it like any other
missing dataset: strict fails the step, lenient stands in an empty dataset. A model with a KSDS
label gives nothing, since copying a VSAM model needs RECORG, which jackal does not model.

**A7. An existing dataset's label is not changed by its DD's attributes.** Ref p. 129 lets a
DD override a label "for the same DCB field" while the dataset is open, and "If you override
attributes for a data set that your program is reading, then it does not affect the actual
data." jackal has no open-time override. The label stands, and a program that relies on such
an override gets status 39.

**A8. Overriding a procedure DD changes only the DCB subparameters it codes.** Ref p. 75: "Code
only the keyword subparameters to be changed; the other DCB subparameters remain unchanged. If
a positional subparameter is needed, code it, regardless of whether it appears in the overridden
DCB parameter. If a positional subparameter is not needed or is to be nullified, omit it from
the overriding DCB parameter." An override that codes `DCB=` therefore keeps the procedure's
model only when it codes the model again. A keyword coded as `RECFM=` with no value nullifies
that keyword, and an override without `DCB=` leaves the model alone. "To nullify all parameters
but the DCB parameter, code DUMMY on the overriding DD statement": a DUMMY override keeps the
attributes. An override coding `DCB=` with no value nullifies every subparameter and the model
(**jackal's own**; Ref names only the per-subparameter form).
