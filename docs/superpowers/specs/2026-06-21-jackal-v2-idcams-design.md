# jackal v2 — run a real CardDemo batch job end-to-end — Design

**Status:** Designed (2026-06-21), approved (goal-level; JCL details delegated).

## What this builds (plain terms)
Run a **real mainframe batch job script** end-to-end: first build an indexed data
file from the shipped account data, then run the COBOL account-reader program
(`CBACT01C`) against it — the way it'd run on a real mainframe.

Concretely: execute the real `ACCTFILE.jcl` (delete old file → create a keyed
file → copy the account data in) followed by `READACCT.jcl` (run `CBACT01C`,
which reads the keyed file and writes an output file), against the external
CardDemo checkout, on genuine EBCDIC data.

**Glossary** (mainframe term → normal-software meaning):
- **JCL** = batch job script (a Makefile/shell-script for "run program A wired to
  these files, then program B").
- **DSN** = a filename (written dotted, e.g. `AWS.M2.CARDDEMO.ACCTDATA.PS`).
- **DD statement** = wires a program's logical file to an actual file.
- **IDCAMS** = the mainframe's built-in file utility (`rm`/`mkfs`/`cp` for datasets).
- **KSDS** = an indexed (keyed) file; **PS** = a flat sequential file;
  **REPRO** = copy records from one to the other.
- **in-stream data / `DD *`** = inline commands/data embedded in the job script.
- **EBCDIC** = mainframe text encoding (datasets are byte-faithful EBCDIC, per the
  red-dragon I/O model).

## Driver
jackal v1 runs synthetic multi-step jobs (parse JCL, sequence steps, dataset
catalog, COBOL + `IEFBR14` steps). red-dragon now runs `CBACT01C` correctly
end-to-end (byte-faithful EBCDIC I/O, CLOSE status, figurative arithmetic — all
merged). The missing pieces to run a *real* job are the JCL/utility features the
real job uses: the `IDCAMS` utility, in-stream data, and real-DSN resolution.

## Scope

**In scope (v2):** exactly what `ACCTFILE.jcl` + `READACCT.jcl` need.
- **In-stream data** (`//DDN DD *` … `/*`) and `//DDN DD SYSOUT=*`.
- **IDCAMS** control language: `DELETE <dsn> CLUSTER`, `DEFINE CLUSTER( NAME(..)
  KEYS(len off) RECORDSIZE(a b) INDEXED .. ) DATA(..) INDEX(..)`,
  `REPRO INFILE(dd) OUTFILE(dd)`, and `IF MAXCC <op> n THEN SET MAXCC = n`.
  (Other IDCAMS verbs/params are parsed-and-ignored or rejected — see below.)
- **Real-DSN resolution** via a configured data dir.
- **KSDS dataset type** in the catalog, loaded by REPRO and read by `CBACT01C`.

**Out of scope (later):** `SORT`/`IEBGENER`/other utilities; `PROC`/symbolic
params; GDG; DD concatenation; `COND`/`IF` step-level conditionals; the broader
CardDemo batch chain (transaction posting, interest, statements).

## Architecture — extend v1 (no new repo)
v1's seams absorb v2: the JCL grammar gains in-stream data; the dataset catalog
gains a data-dir search path and a KSDS dataset type; the utility registry gains
`IDCAMS`. Flow:
```
JCL (now: DD * in-stream, SYSOUT) → Job
JobRunner, per step:
  resolve DDs (capture in-stream SYSIN; resolve DSN via catalog; allocate if NEW)
  → IDCAMS step: parse+execute its SYSIN control statements
  → COBOL step (CBACT01C): run via red-dragon; OPEN INDEXED reads the KSDS
```

## Components
1. **`jcl/grammar.lark` + `jcl/parser.py`** — add in-stream data (`//DDN DD *`
   followed by lines until `/*`) attached to the owning `DD`, and `DD SYSOUT=*`.
   Grammar-based, no regex.
2. **`model.py`** — `DD` gains `in_stream: tuple[str, ...]` (default `()`) and
   `sysout: bool` (default `False`).
3. **`idcams/grammar.lark` + `idcams/parser.py`** — new Lark grammar for the
   IDCAMS control language (the four verb forms above + `-` continuation),
   producing immutable command objects: `Delete(dsn)`, `DefineCluster(name,
   key_length, key_offset, record_size)`, `Repro(infile_dd, outfile_dd)`,
   `IfMaxcc(op, value, set_value)`.
4. **`idcams/executor.py`** — `run_idcams(commands, step_dds, catalog) -> int`
   (returns MAXCC). `DELETE`: remove the DSN from the catalog (missing → MAXCC 8).
   `DEFINE CLUSTER`: register a KSDS `Dataset` (org KSDS, key_offset/len,
   record_size) backed by a fresh catalog file. `REPRO`: resolve INFILE/OUTFILE
   DDs → datasets; read the PS input as fixed-length records and write each into
   the KSDS via red-dragon's `IndexedDriver`. `IF MAXCC …/SET MAXCC`: adjust MAXCC.
5. **`catalog.py`** — (a) `resolve` for `SHR/OLD` falls back to `<data_dir>/<DSN>`
   when the DSN isn't already cataloged; (b) `Dataset` gains `org: DatasetOrg`
   (PS|KSDS), `key_offset`, `key_length`, `record_size`; `allocate_ksds(...)` for
   DEFINE.
6. **`utilities.py`** — register `IDCAMS`: parse its `SYSIN` DD's in-stream lines,
   call `run_idcams`, map MAXCC → `StepResult.return_code`.
7. **`cli.py` / `runner.py`** — `--data-dir` (default
   `$CARDDEMO_HOME/app/data/EBCDIC`); `--source-dir` (default
   `$CARDDEMO_HOME/app/cbl`); thread `data_dir` into the catalog.

## Data flow (the crux)
`REPRO` reads the INFILE **PS** (EBCDIC flat file at `<data-dir>/<DSN>`, here
`…ACCTDATA.PS`) as fixed-length records and writes each into the OUTFILE **KSDS**
using red-dragon's `IndexedDriver` — the *same on-disk format red-dragon reads*.
Then `CBACT01C`'s `OPEN INPUT … ORGANIZATION INDEXED` reads that exact KSDS file
through the `RealFileIOProvider` jackal already wires. No bespoke VSAM format:
both ends use red-dragon's file drivers.

## Error handling
- `MAXCC`: `DELETE` of a missing cluster → 8; `IF MAXCC LE 08 THEN SET MAXCC = 0`
  resets it (the real job's idiom for "ignore delete-of-missing"). A step's RC is
  its final MAXCC; a nonzero RC does not by itself stop the job (COND is out of
  scope) — matches the v1/spec error model.
- Unresolved `SHR`/`OLD` DSN (not cataloged, not under data-dir) → clear error.
- `REPRO` with a missing INFILE → clear error. Unknown IDCAMS verb → clear
  "unsupported IDCAMS command" error (fail loud; grammar rejects it).
- No regex; no defensive `None`; grammar errors over runtime `None` checks.

## Testing (TDD)
- **Unit:** `idcams/parser` (each verb + `IF/SET` + `-` continuation, and a
  reject case); `catalog` data-dir resolution + KSDS allocation; `idcams/executor`
  REPRO (small synthetic PS → KSDS, read back via `IndexedDriver`); JCL parser
  in-stream-data + SYSOUT.
- **Integration (headline, `carddemo_e2e`-gated — skips if `CARDDEMO_HOME`
  unset, mandatory locally):** run real `ACCTFILE.jcl` then `READACCT.jcl` against
  the checkout; assert every step RC 0 and `CBACT01C`'s `OUTFILE` contains the
  expected first account record (decoded from its EBCDIC bytes).

## Binding constraints (carried from v1)
- **No regex** — IDCAMS control language and JCL in-stream parsing are Lark
  grammars.
- TDD; FP (frozen dataclasses, functional core / imperative shell); no defensive
  programming; small composable functions.
- **No external-codebase references in tracked artifacts** — real DSNs and data
  come from the env-var checkout (`CARDDEMO_HOME`); never committed; the headline
  test is gated and skips without it.
- Python 3.13+, uv, pytest, Black.
