---
name: cobble-artifacts
description: Answer questions about a COBOL corpus — where a field's value comes from, who changes it, what a change would break, which programs touch a file or screen, what a program does — by deducing from the artifacts cobble generated, not by reading source. Use whenever a cobble output directory exists (the one `tools/rebuild-all.sh` or `make carddemo-all` writes, `cobble/out-*`) and the question is about programs, fields, files, screens, transactions, data flow or impact.
---

# Answering from cobble's artifacts

Deduce answers from the artifacts. Source is for **quoting a conclusion you already reached**, at
most a few lines, never for reasoning. The artifacts are static: they hold the code's structure and
data flow, never record contents or runtime values. If no artifact can answer the question, say
which artifact would have to exist, and stop.

Run every tool from `cobble/` with `uv run --no-sync`. `$RUN` below is the output directory.

## What each artifact answers

| artifact | holds | answers |
|---|---|---|
| `extents.jsonl` | every declared field: program, byte extents, record, declaration path, PIC, usage, `REDEFINES`, `OCCURS` | where a field lives in storage; which fields share bytes |
| `fixpoint/` (`graph.jsonl`, `defs.jsonl`, `sinks.jsonl`, `aliases.jsonl`, `members/<P>/`) | per program, every byte move (`FLOWS_TO`) with its site, landing and `rebuilt` flag; reaching definitions; where values leave; each edge's `attrs.origin` and each sink row's `sink` is `{"kind", "name"}` (kinds such as `LITERAL`, `FILE`, `MAP`, `CALL`, `DYNAMIC_CALL`, `CICS_STATE`) | where a value came from and where it goes, inside one program |
| `combine/links.jsonl` | every `CALL`/`LINK`/`XCTL`: caller and callee extents of the shared area | which bytes cross which program boundary, in each direction |
| `combine/targets.jsonl` | dynamic call/file targets with their candidate values | what a `CALL WS-PGM` or `FILE(WS-FILE)` can resolve to |
| `knowledge-graph.jsonl` (`.html`) | programs, copybooks, JCL jobs and steps, DDs, datasets, CSD transactions and files, in-stream control cards (`IDCAMS DEFINE`) | which job runs which program, which DD is which dataset, which transaction starts which program |
| `srccfg/cfg-<P>.jsonl` (`.html`) | one program's control-flow graph and its transitive closure: nodes with writes and reads, guards | which paragraphs run, under which conditions, in which order |
| `accesses/<P>.jsonl` | every place a field is read or tested (`IF`/`EVALUATE`), with bytes | where a field is examined, including tests that move nothing |
| `depgraph/` | name-level dependency graph, one node per name | quick, coarse "what feeds what" across a program |
| `bms/metadata.json`, `bms/*.html` | every screen field: map, name, length, position, attributes, label (one JSON object per line, one per mapset: `{"mapset", "maps": [{"map_name", "fields": [{"name", "length", "attrb", "pos", "screen_label"}]}]}`; a program's output field is the name plus `O`, its input field the name plus `I`) | which program field a label on a screen is |
| `graph.jsonl` | the partition graph, one JSON object per line: `{"node": {id, kind, program, record, field, size, offset, …}}` or `{"edge": {source, target, alignments, certainty, reasons, rebuilt, …}}`. A field id is `PROGRAM:RECORD.FIELD`; a file slot id is the dataset name and byte range, `AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS[12:24]`. An edge runs from where the bytes were to where they land: a field into a file slot is a write to the file, a file slot into a field is a read | how a value travels across the whole system |
| `render/` | the partition graph's pages: program map and per-program neighbourhoods | pictures of the above |
| `aggregates/unified.jsonl` | classes of fields connected by exact moves | which fields are copies of one another |
| `aggregates/matrix.npz`, `meta.json`, `decompose/rounds.json` | field-by-program matrix and its NMF factors | which fields travel together, suggesting the system's entities |
| `datalog/` (`<relation>.facts`, `schema.dl`) | the run as Soufflé facts, one tab-separated file per relation, declared in `schema.dl`; generic rules in `cobble/cobble/experimental/datalog/rules/` (see `docs/reference/cobble/datalog.md`) | any question above as a Datalog query: `souffle -I $RUN/datalog -I <rules dir> -F $RUN/datalog -D - question.dl` |

## Query tools

- `cobble-trace-query {backward|forward} PROGRAM.FIELD --fixpoint $RUN/fixpoint --links $RUN/combine/links.jsonl --extents $RUN/extents.jsonl --depth N`: provenance chains across programs.
- `cobble-dataflow-fixpoint-query {extents|writers|readers|reaches|reached-by|contains|within|overlapping} SUBJECT --fixpoint-dir $RUN/fixpoint --extents $RUN/extents.jsonl`: byte-interval questions; `writers` lists every write with its site and definers.
- `cobble-srccfg-query {provenance|guards|coassign} SUBJECT --cfg $RUN/srccfg/cfg-P.jsonl`: control-flow questions within one program.
- `cobble-access-query FIELD --accesses $RUN/accesses/P.jsonl --extents $RUN/extents.jsonl`: where a field is read or tested.
- `cobble-experimental-partition-copies --graph $RUN/graph.jsonl --extents $RUN/extents.jsonl --width N --start NODE_ID [--start …]`: every place holding all `N` bytes of a value, followed byte by byte. Starts are node ids from `graph.jsonl`, usually file slots such as `AWS.M2.CARDDEMO.CARDDATA.VSAM.KSDS[0:16]`; quote them, since `[…]` is a glob to the shell.

For anything else, read the JSONL with a short script in the scratchpad. Parse rows into the
fields you need; never guess a format. Progress lines (`[0h00m00s] …`) go to stderr; the answer is
on stdout.

**Which file slot holds a field:** find edges in `graph.jsonl` whose source is a file slot and whose
target is the field (`…:ACCOUNT-RECORD.ACCT-CURR-BAL`); the slot's id carries the byte range. The
writers of that slot are the sources of the edges into it.

## Judgement rules

Each rule comes from CardDemo. Apply it when a hop looks surprising.

- **A commarea carries only the bytes its link carries.** In `combine/links.jsonl` the menu
  `COMEN01C` takes 218 bytes in from COTRN02C and COBIL00C, and passes only 160 on. So a byte past
  160 in one caller cannot reach another caller through the menu, even when the byte graph joins
  them.
- **The tail of a shared commarea is reused.** Past the common header, each program puts its own
  fields in the same bytes. A move there only means the same thing if both programs' fields agree.
- **A field and the field it directly `REDEFINES` are one location** (`CC-CARD-NUM-N REDEFINES
  CC-CARD-NUM`). Sibling variants of a record that only share bytes are not: CBEXPORT's
  `EXP-CARD-NUM` and `EXP-TRAN-ID` overlap in different record types.
- **`rebuilt` edges are not copies.** Arithmetic and `STRING` build a new value in the target.
- **A trailing `~` means a computed subscript.** The write landed somewhere in the range, and
  which row cannot be known statically.
- **Keys select; they are not data flow.** `RIDFLD`, `READ … KEY IS` and `RECORD KEY` say which
  record arrives, not where its bytes came from, so no flow edge exists for them. The facts are in
  the ASGs (`cobble/out-*/asg/*.json` or the corpus cache): `RIDFLD` is a CICS option; `KEY IS` and
  `RECORD KEY` are on the batch read and in `file_control`. Two files holding the same value (card
  file and xref file) are often joined only through a key.
- **"overlapping-layouts" dataset edges** (certainty `possible`, no alignments) mean the file holds
  several record layouts in the same bytes. Match writer and reader by the same field path and
  offset in `extents.jsonl`; say that you did.
- **Names lie.** COTRN02C's `CDEMO-CT02-TRN-SELECTED` carries a card number. Trust the moves.
- **An alternate index is its base file.** The knowledge graph's `DEFINE PATH` cards tie
  `CARDXREF.VSAM.AIX.PATH` to `CARDXREF.VSAM.KSDS`.

## Worked examples

**"Where does the current balance on the account-view screen come from, and which programs can
change it?"**
1. `bms/metadata.json`: the label "Current Balance" is field `ACURBAL` on map `CACTVWA`; its
   output field is `ACURBALO`.
2. `cobble-trace-query backward COACTVWC.ACURBALO …` gives `ACCT-CURR-BAL`, read from
   `FILE:LIT-ACCTFILENAME` (the program's name for the file, held in a variable) in
   `9300-GETACCTDATA-BYACCT`.
3. `graph.jsonl`: the edge into `COACTVWC:ACCOUNT-RECORD.ACCT-CURR-BAL` comes from the file slot
   `AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS[12:24]`: the CICS file and the batch DDs resolve to that one
   dataset, and the balance is bytes 12 to 24.
4. The edges into that slot come from CBACT04C (adds interest), CBTRN02C (posts daily
   transactions), COBIL00C (bill payment) and COACTUPC (the account-update screen).
   `cobble-dataflow-fixpoint-query writers PROGRAM.FIELD` names the statement in each.

**"If the card number widens from 16 to 19 digits, what breaks?"**
1. Find the file slots holding a card number: `extents.jsonl` gives each card-number field's
   offset in its record; `graph.jsonl` gives the dataset node for that range (card file, xref file
   and its alternate index, transaction file, daily-transaction file).
2. `cobble-experimental-partition-copies --width 16` with those slots as starts. On CardDemo that
   is about 90 places across about 20 programs and several files.
3. Check surprising entries with the rules above (commarea bytes in vs out, record layouts,
   misleading names).
4. Report what the walk cannot see: key lookups (`RIDFLD` fields, `KEY IS` fields), table rows
   written through a computed subscript, and screen output fields that share bytes with input
   fields through a map-level `REDEFINES`.

## Answer format

1. The answer, plainly.
2. The evidence chain: each step's artifact and the row or query output it rests on.
3. Which steps needed judgement, and which rule you applied.
4. What the artifacts cannot tell, if anything.
