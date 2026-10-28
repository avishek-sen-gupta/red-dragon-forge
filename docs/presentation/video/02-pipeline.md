# 2. The pipeline, stage by stage

Run each stage on camera, then open what it wrote. The stages and their order are
`tools/rebuild-all.sh`; `make carddemo-all` runs them all at once. This segment builds into its own
directory, so the frozen run that segment 4 reads stays as it is. Set up the shell once:

```bash
. ./bridge-env.sh
cd cobble
CONFIG=config/carddemo-partition.toml
ASG=out-partition/asg
OUT=out-video-pipeline
```

The running example is the **current balance** on the account-view screen, from COBOL to the
file it is read from.

## 2.1 Screens and resources (one line each)

```bash
uv run --no-sync cobble-sym --config $CONFIG
uv run --no-sync cobble-csd --config $CONFIG --out $OUT/csd/synthesised.csd
```

Say: the screen maps compile to copybooks the programs include, and the CICS resource table (which
transaction starts which program, which file name means which dataset) is rebuilt from the
programs where it was not shipped.

## 2.2 Parse: the AST

```bash
uv run --no-sync cobble-parse-corpus --config $CONFIG --force
```

**Explainer: what an AST is.** A parser turns text into a tree whose nodes are the language's
constructs. The tool then reasons about constructs, never about text. Show the source line, then
its node:

```cobol
MOVE ACCT-CURR-BAL       TO ACURBALO OF CACTVWAO
```

```bash
jq -c '[.. | objects | select(.type=="MOVE" and (.operands[0].name? == "ACCT-CURR-BAL"))][0]' $ASG/COACTVWC.json
```

```json
{"type":"MOVE","operands":[{"name":"ACCT-CURR-BAL"},{"name":"ACURBALO","qualifiers":["CACTVWAO"]}], ...}
```

Point out: `OF CACTVWAO` became a qualifier, so `ACURBALO` is unambiguous; a regex would have to
guess that. (Strictly this is an ASG, an AST with names resolved; say "tree" and move on.)

## 2.3 Extents: where every field lives, byte by byte

```bash
uv run --no-sync cobble-extents --asg-dir $ASG --out $OUT/extents.jsonl --synthesize-undeclared
grep '"id": "COACTVWC.ACCT-CURR-BAL"' $OUT/extents.jsonl | cut -c1-200
```

Say: data flow in COBOL is really about bytes. Groups, `REDEFINES` and record moves mean one value
can have several names, so every field is laid out to its byte range first. Names a program uses
but never declares (a missing copybook) get a nominal declaration so they are still tracked.

## 2.4 Data-flow analysis, and the fixpoint that computes it

**Explainer first: data flow.** The two questions behind almost every reverse-engineering task:
*where did this value come from*, and *where does it go*. Draw it for the balance:

```
account file ──READ──▶ ACCT-CURR-BAL ──MOVE──▶ ACURBALO ──SEND MAP──▶ screen
```

One program, one path, is easy to read by eye. Real programs have loops, branches and `PERFORM`s:
a value at a point can come from several earlier writes, depending on the path taken.

**Explainer: the fixpoint.** The analysis walks the control flow, carrying "which writes can reach
here" for every byte. Where paths join, it merges what each brought. Around a loop it goes round
again, because the second time round more writes can reach. It stops when another pass changes
nothing. That stable state is the fixpoint: the answer for every point at once.

```bash
uv run --no-sync cobble-dataflow-fixpoint --asg-dir $ASG --extents $OUT/extents.jsonl \
  --out-dir $OUT/fixpoint --all --force
uv run --no-sync cobble-trace-query backward COACTVWC.ACURBALO --fixpoint $OUT/fixpoint \
  --extents $OUT/extents.jsonl --depth 8
```

Show the trace: `ACURBALO ← ACCT-CURR-BAL ← FILE:…` at named sites (paragraph and statement).
Point out that the answer cites where each step happens.

## 2.5 Combine: across programs

```bash
uv run --no-sync cobble-dataflow-combine --config $CONFIG --fixpoint-dir $OUT/fixpoint \
  --out-dir $OUT/combine --all --max-hops 5
head -3 $OUT/combine/links.jsonl
```

Say: programs call each other and hand over a shared area (the commarea). Each link records which
bytes of the caller's area land where in the callee's, in each direction.

## 2.6 Knowledge graph: the system's inventory

```bash
uv run --no-sync cobble-build --config $CONFIG --output $OUT/knowledge-graph.jsonl \
  --dynamic-call-targets $OUT/combine/targets.jsonl
uv run --no-sync cobble-render-webgl --graph $OUT/knowledge-graph.jsonl --out $OUT/knowledge-graph.html
open $OUT/knowledge-graph.html
```

Say: programs, copybooks, jobs, job steps, datasets and transactions, and how they connect. This is
what tells you that the file a CICS program calls by one name and the dataset a batch job opens
under another are the same file.

## 2.7 Control flow: the CFG (one program)

```bash
mkdir -p $OUT/srccfg
printf '[srccfg]\nasg_dir = "%s"\n' "$ASG" > $OUT/srccfg/srccfg.toml
uv run --no-sync cobble-srccfg-build --config $OUT/srccfg/srccfg.toml COACTVWC \
  --dynamic-call-targets $OUT/combine/targets.jsonl --output $OUT/srccfg/cfg-COACTVWC.jsonl
uv run --no-sync cobble-srccfg-webgl --cfg $OUT/srccfg/cfg-COACTVWC.jsonl --output $OUT/srccfg/cfg-COACTVWC.html
open $OUT/srccfg/cfg-COACTVWC.html
```

**Explainer: what a CFG is.** A control-flow graph has one node per statement and an edge for
every way control can move next: fall through, branch, `PERFORM` and return, `GO TO`. Show
`1200-SETUP-SCREEN-VARS`: an `IF EIBCALEN = 0` splits into two paths, and only one of them moves
the balance to the screen. The fixpoint walked exactly this graph.

The full run builds one per program (about 12 minutes for CardDemo); say so and show one. The same
stage also writes each program's field accesses (every place a field is read or tested) and its
call-graph and sequence views.

## 2.8 Name-level dependency graph and screen maps (one line each)

```bash
printf '[output]\nasg_dir = "%s"\ngraph_dir = "%s"\n' "$ASG" "$OUT/depgraph" > $OUT/depgraph.toml
uv run --no-sync cobble-depgraph --config $OUT/depgraph.toml
uv run --no-sync cobble-depgraph-render --config $OUT/depgraph.toml
uv run --no-sync cobble-bms-metadata --config $CONFIG --output $OUT/bms/metadata.json
uv run --no-sync cobble-bms-render --config $CONFIG --format html --out-dir $OUT/bms
open $OUT/bms/CACTVWA.html
```

Say: a coarse "what feeds what" by name, and every screen rendered with its fields. Point at
"Current Balance" on `CACTVWA`: that label is field `ACURBAL`, which is how segment 4 starts.

## 2.9 The partition graph: every byte, across the whole system

```bash
uv run --no-sync cobble-experimental-partition-graph --extents $OUT/extents.jsonl --fixpoint $OUT/fixpoint \
  --links $OUT/combine/links.jsonl --knowledge-graph $OUT/knowledge-graph.jsonl \
  --targets $OUT/combine/targets.jsonl --barrier fanout --fanout-limit 8 --out $OUT/graph.jsonl
uv run --no-sync cobble-experimental-partition-file-sites --fixpoint $OUT/fixpoint \
  --knowledge-graph $OUT/knowledge-graph.jsonl --targets $OUT/combine/targets.jsonl
uv run --no-sync cobble-experimental-partition-render --graph $OUT/graph.jsonl --out $OUT/render
open $OUT/render/index.html
```

Say: one node per field, per file slot, and per place values enter or leave; one edge per byte
move, within programs, across calls and through files. Click a program, then a field, to see what
it connects to. The file-site census reports which file reads and writes resolved to a dataset,
and why the rest did not.

## 2.10 Aggregates: which fields belong together

```bash
uv run --no-sync cobble-experimental-aggregate-unify --graph $OUT/graph.jsonl --out $OUT/aggregates/unified.jsonl
uv run --no-sync cobble-experimental-aggregate-matrix --defs $OUT/fixpoint/defs.jsonl --extents $OUT/extents.jsonl \
  --unified $OUT/aggregates/unified.jsonl --out-matrix $OUT/aggregates/matrix.npz --out-meta $OUT/aggregates/meta.json
uv run --no-sync cobble-experimental-aggregate-decompose --matrix $OUT/aggregates/matrix.npz \
  --meta $OUT/aggregates/meta.json --min-occurrences 4 2 --k 30 10 --out-dir $OUT/aggregates/decompose
uv run --no-sync cobble-experimental-aggregate-scorecard --matrix $OUT/aggregates/matrix.npz \
  --meta $OUT/aggregates/meta.json --unified $OUT/aggregates/unified.jsonl --min-occurrences 4 2 --k 30 10
```

First, unify: fields connected by exact moves are one class (every program's copy of
`ACCT-ACTIVE-STATUS` is one class).

**Explainer: NMF and why it helps.** Build a table: one row per paragraph, one column per field
class, a 1 where that paragraph reads or writes the field. Fields that make up one business entity
tend to be used together: an account's id, balance and limits are handled in the same paragraphs.
Non-negative matrix factorisation splits the table into a small number of parts, each a weighted
set of fields plus the paragraphs that use them. Because the weights cannot be negative, each part
is something added in, not subtracted out, so it reads as "these fields go together". Those parts
are candidate entities, found from behaviour rather than from names.

Show three parts from the frozen run's first round (`jq '.[0].fit.factors[3,6,1]'
$OUT/aggregates/decompose/rounds.json`), reading out the top fields and paragraphs:

| part | top fields | top paragraphs | reads as |
|---|---|---|---|
| 3 | `ACCT-CURR-BAL`, `ACCT-CREDIT-LIMIT`, `ACCT-ACTIVE-STATUS`, `ACCT-GROUP-ID`, `ACCT-REISSUE-DATE`, `ACCT-OPEN-DATE` | `1500-B-LOOKUP-ACCT`, `2800-UPDATE-ACCOUNT-REC`, `1100-GET-ACCT-DATA` | the account |
| 6 | `CUST-SSN`, `CUST-PHONE-NUM-1`/`-2`, `CUST-LAST-NAME`, `CUST-MIDDLE-NAME`, `CUST-PRI-CARD-HOLDER-IND` | `1200-SETUP-SCREEN-VARS`, `9400-GETCUSTDATA-BYCUST` | the customer |
| 1 | `CARD-NUM`, `CARD-ACCT-ID`, `CARD-EMBOSSED-NAME`, the old expiry date | `9000-READ-DATA`, `1100-RECEIVE-MAP` | the card |

Then be honest about the rest: some parts are runs of `FILLER` bytes or file-status codes. They are
real patterns of use, but not business entities; telling the two apart is interpretation, which is
where segment 4 comes in.

The scorecard says how well the parts fit and how stable they are across runs; say what the
numbers mean, not their values.
