# jackal: A DD Naming a GDG Base Reads Every Generation — Decision Record

**Date:** 2026-10-12
**Status:** accepted (red-dragon-forge-zbb)
**Issues:** red-dragon-forge-zbb; follows the 2026-10-12 GDG record (G1–G9)

How jackal allocates a DD whose DSN is a GDG's base name with no generation number (a GDG-all
request), in what order, and what deleting a generation does to its GDG. Each rule is quoted from
IBM's documentation.

## Sources

| Key | Document |
|---|---|
| JCL | [z/OS 3.1 MVS JCL Reference](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/ieab600_v3r1.pdf) — "DSNAME parameter", p. 167; "GDGORDER parameter", pp. 190–191; override rules, p. 75 |
| AMS | [z/OS 3.1 DFSMS Access Method Services Commands](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/idai200_v3r1.pdf) — "DEFINE GENERATIONDATAGROUP", p. 178 |

## Decisions

**Z1. A GDG base name reads as a concatenation of its active generations.** JCL p. 167: "To
retrieve all generations of a generation data group, omit the generation number." JCL p. 191
shows `DSN=D24PP1.SMF.DATA,GDGORDER=FIFO` read as the concatenation `(-2)`, `(-1)`, `(0)`.
jackal rewrites such a DD into exactly that before allocation, against the generations the job
first found (GDGBIAS=JOB, record G4). Each generation is then a concatenation member, allocated
and disposed with the DD's DISP, and read member after member as any concatenation is. A base
name in a concatenated DD is expanded in place.

**Z2. The order is the GDG's, unless the DD's GDGORDER overrides it.** AMS p. 178: FIFO returns
"the oldest GDS defined to the newest GDS", LIFO "the newest GDS defined to the oldest GDS. This
is the default value." `DEFINE GDG` records FIFO or LIFO on the base, and a catalog written
before this change reads as LIFO. JCL p. 190: `GDGORDER=USECATLG|LIFO|FIFO`; "USECATLG is the
default value". GDGORDER is carried through the bridge, symbols and overrides like a DCB
subparameter: an override changes it only where it codes it (JCL p. 75), and `GDGORDER=` with no
value restores the catalog's order. jackal reads GDGORDER from the named DD statement and applies
it to every base in that DD's concatenation. Reading it from each unnamed DD statement as well is
not modelled.

**Z3. The base name of a GDG with no active generations fails allocation with
`DATASET_NOT_FOUND`.** There is nothing to concatenate, and the base name is not itself a
dataset. This is **jackal's own** choice, matching record G9 for a `(0)` of such a GDG. The IBM
pages cited here do not say what z/OS does.

**Z4. Deleting a generation removes it from its GDG.** A generation whose disposition deletes it
loses its catalog entry, and with it its place among the GDG's active generations. Before this,
jackal deleted the dataset but kept listing the generation as active. That broke the common
idiom `DSN=base,DISP=(OLD,DELETE)`, which reads every generation and then deletes them all.
