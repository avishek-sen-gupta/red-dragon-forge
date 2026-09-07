# cobble

[![reproduce-graph](https://github.com/avishek-sen-gupta/cobble/actions/workflows/reproduce.yml/badge.svg)](https://github.com/avishek-sen-gupta/cobble/actions/workflows/reproduce.yml)

A **standalone, VM-free** knowledge-graph extractor for COBOL/CICS/JCL
mainframe codebases. It is a file-by-file **port** of the streaming graph
pipeline in the `red-dragon-forge` monorepo, lifted into its own repository to
prove the extraction is decoupled from the RedDragon interpreter/VM. Point it
at any corpus via a TOML config (see [Point this at your own
codebase](#point-this-at-your-own-codebase)); the AWS **CardDemo** corpus is
this repo's proof case, where it reproduces the **exact same 449-node /
803-edge graph** starting from nothing but:

- the **CardDemo repo** (a git submodule, the source corpus), and
- the parsers/tools, all **built from source** (submodules + copied Maven source).

Everything generated (the ANTLR CICS parser **and** the BMS symbolic copybooks)
is **generated here from its grammar/source**. No production Python is imported at
runtime, and nothing pre-generated is shipped: the only things tracked are
hand-written source, grammar source (`.g4` / `.bms` / `.mac`), and submodule pins.

## Reproduce from a fresh clone

Requires: `git`, JDK 21+, Maven (bridges); a C++ toolchain (clang or gcc) with
CMake + Ninja (`hlasm_export`); and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone <this-repo> cobble && cd cobble
./build.sh   # submodules -> tools -> generate parser+copybooks -> parse -> extract -> verify 449/803 -> render
```

`make` targets:

| Target | What it does |
|--------|--------------|
| `tools` | Build hlasm, proleap fork, and bridge JARs |
| `codegen` | Generate the CICS parser and BMS copybooks from their grammars |
| `parse` | Parse the corpus to one JSON ASG per member (the cache every later stage reads) |
| `build` | Extract the graph to `out/` |
| `compare` | Identity-diff vs `reference/` (449/803) |
| `render` | Render `out/` as an interactive HTML graph |
| `test` | Run the pytest unit suite |
| `fmt` | Format with black |
| `lint` | Run import-linter, pyright, and python-fp-lint |
| `clean` | Drop all generated artifacts |

### Build the graph from CardDemo

`./build.sh` runs the full pipeline end to end. To run it step by step instead:

```bash
git submodule update --init                            # fetch the CardDemo corpus + parser/HLASM forks
make tools                                             # build hlasm_export + the proleap fork + both bridge JARs
make codegen CONFIG=config/carddemo.toml               # generate the CICS parser (ANTLR) + BMS symbolic copybooks
make parse CONFIG=config/parse-carddemo.toml           # parse the corpus -> one JSON ASG per member in out-parsed/
make build CONFIG=config/carddemo.toml                 # extract the graph -> out/nodes.jsonl, out/edges.jsonl
make compare                                           # identity-diff out/ vs reference/ (must be empty: 449/803)
```

`CONFIG=` is a required argument to `make parse`/`make build`/`make sym`/`make csd`
(and transitively `make codegen`, which depends on `sym`); there's no default, so a
bare `make build` fails with a clear error instead of silently assuming CardDemo.
`make parse` takes a **parse** config (`config/parse-carddemo.toml`), everything
else takes a **corpus** config (`config/carddemo.toml`) — two files, because which
members were parsed with which copybook dirs and which bridge JAR are facts about
the parse, and repeating them in the corpus config would let the two disagree.
`build.sh` hardcodes both for its own from-scratch CardDemo run.

`make parse` is the only stage that starts a JVM, at 4-7 seconds per member. It is
**resumable**: a member whose ASG (or recorded failure) is already in `asg_dir` is
skipped, so re-running it after an interrupt costs nothing for what it already did.
Delete `asg_dir` to force a full reparse after a bridge or grammar change.

`make build` re-runs the four extractors (CALL/COPY, CICS flow, JCL, batch
FILE-CONTROL) from scratch every time, reading the ASGs `make parse` wrote rather
than parsing again; safe to re-run after touching any extractor code. Touch the
corpus itself and `make parse` has to run again first — a member with no cached ASG
is reported as one skipped member, not silently reparsed.

### Point this at your own codebase

`cobble.build_graph`/`cobble.generate_sym` take a required `--config <path>`
flag; nothing about a specific corpus is hardcoded in Python. `make build`/
`make sym` take a matching required `CONFIG=<path>` argument, which they
simply forward. `config/carddemo.toml` is both the config CardDemo uses and a
template for your own corpus:

```toml
[corpus]
cobol_dir = "path/to/your/cobol"
cobol_globs = ["*.cbl", "*.CBL"]
jcl_dir = "path/to/your/jcl"
jcl_globs = ["*.jcl", "*.JCL"]
proclib_dirs = ["path/to/your/proclib"]
csd_files = ["path/to/your/site.csd"]   # omit or leave empty ([]) if your corpus has no CICS
copybook_dirs = ["path/to/your/copybooks"]
copybook_extensions = ["cpy", "txt"]    # omit unless your copybooks are named unconventionally
asg_dir = "out-parsed"                  # what `make parse` wrote; an INPUT to this stage
out_dir = "out"

# omit unless you have no CSD; see "Recover a CSD" below. A table array ENDS the
# table it's in, so these have to come after every bare key of [corpus].
[[corpus.transid_rules]]
member_pattern = "^PGM(?P<tail>.{3})$"
transid_template = "T{tail}"

[bms]
bms_dir = "path/to/your/bms"
bms_globs = ["*.bms"]     # omit unless your map sources are named unconventionally
macros_dir = "bms-macros"
sym_dir = "sym"
```

Every path is relative to wherever you invoke the script from (not to the
config file's own location). Every field is required except `proclib_dirs`,
`csd_files` and `transid_rules`, which default to empty if omitted, and
`copybook_extensions` and `bms_globs`, which default to the conventions cobble
ships with.

Those last two exist because a corpus that doesn't follow file-naming
convention would otherwise need a directory of symlinks. `cobol_globs`,
`jcl_globs` and `bms_globs` select files by listing a directory, so they take
globs; `copybook_extensions` is a list of bare extensions instead, because a
`COPY X` is resolved by ProLeap as *name + extension* rather than by listing
anything. Keep `cpy` in that list if you also generate BMS symbolic maps —
`generate_sym` writes them as `<mapname>.cpy`. The shape these options exist for
is a corpus where every member carries the same extension — say `.txt` — with
programs, copybooks and maps distinguished only by directory and name.

The parse is a config of its own — `config/parse.example.toml` is the template,
`config/parse-carddemo.toml` the working one. Every key is required:

```toml
[parse]
cobol_dir = "path/to/your/cobol"        # the same corpus the corpus config names
cobol_globs = ["*.cbl", "*.CBL"]
copybook_dirs = ["sym", "path/to/your/copybooks"]   # searched in order
copybook_extensions = ["", "cpy", "txt"]            # "" resolves a bare COPY name
bridge_jar = "../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
asg_dir = "out-parsed"                  # must match the corpus config's asg_dir
```

One JSON ASG per member, named for the **member's filename**, not its
`PROGRAM-ID`: `MYPROG.cbl` → `MYPROG.json`. Two members declaring the same
`PROGRAM-ID` is normal on a real corpus, and naming the cache after the id would
have one overwrite the other. A member that won't parse gets a `.fail` beside it
carrying the parser's message, and is not retried on the next run.

Then run:

```bash
uv run cobble-sym           --config your-corpus.toml   # first, if you have BMS maps: sym/*.cpy
uv run cobble-parse-corpus  --config your-parse.toml    # then the parse -> one ASG per member
uv run cobble-build         --config your-corpus.toml   # then the graph -> <out_dir>/{nodes,edges}.jsonl
uv run cobble-render        --config your-corpus.toml   # optional HTML visualization
```

That order matters: `cobble-sym` writes the symbolic copybooks the parse resolves
`COPY` against, and `cobble-build` reads what the parse wrote. `cobble-parse-corpus`
takes `--jobs N` — one worker process, and so one JVM, each — defaulting to one per
core. It names its own bridge JAR in `bridge_jar` and reads no environment variable
for it, and it refuses to start when that path is not a file.

`cobble.compare`'s golden-file check stays CardDemo-specific: it's not
meaningful against a different corpus's output.

### Recover a CSD your corpus never shipped

A CSD is an export of a running CICS region, and plenty of handovers don't
include one. With `csd_files` empty, `build_graph` skips the CICS flow stage
entirely: no transaction gets a worklist entry, so no member is scanned for its
`EXEC CICS LINK`/`XCTL` operands and none of those edges reach the graph.

```bash
make csd CONFIG=your-corpus.toml    # -> <out_dir>/synthetic.csd
```

This reconstructs the `DEFINE TRANSACTION(...) PROGRAM(...)` pairs from the
members themselves, in three tiers of evidence:

| Tier | What it means |
| --- | --- |
| `corroborated` | `transid_rules` places a transaction id on this member *and* the member's own source names that id literally, and no other member claims it |
| `convention` | `transid_rules` places it and nothing contradicts that |
| `synthetic` | nothing establishes a transaction, so the member gets `UNKNOWN.<member>` |

Nothing is guessed. A transaction id two members both claim demotes both and is
reported; a literal id no member claims is reported. `transid_rules` is an
ordered list of regex + template pairs — the first whose `member_pattern`
matches wins, and its named groups fill `transid_template` — because how member
names encode transaction ids is a fact about your site, not about cobble.

A `synthetic` entry is a worklist entry, not a claim: it gets the member parsed
and its `LINK`/`XCTL` edges read, and `build_graph` then suppresses the
placeholder `TRANSACTION` node and any edge touching it, so nothing the corpus
never stated appears in the graph. With no `transid_rules` at all every member
goes synthetic, which still recovers every program-derived edge — you just get
no `TRANSACTION` nodes and no `STARTS` edges.

The generated file is not picked up automatically. Point `csd_files` at it to
use it, which keeps it an explicit, reviewable input to the next run:

```toml
[corpus]
csd_files = ["out/synthetic.csd"]
```

Because it lives under `out_dir`, cleaning `out_dir` leaves `csd_files` pointing
at a path nothing has written — so `build_graph` **refuses to start** when a
`csd_files` entry is not a readable regular file, naming the paths, before the
expensive phase. That used to be one guarded warning, and the run went on to
write a graph missing the entire CICS stage. An empty `csd_files` is still a
choice, not an error: the stage says it skipped. Content stays the guarded
stage's business — a malformed CSD is reported per file, as before.

`DEFINE FILE` entries can't be reconstructed this way, so a generated CSD also
yields no `DEFINES_DATASET` edges and only the CICS files programs actually
name.

### Diagnose missing copybooks before parsing

```bash
uv run diagnose-copybooks --config your-corpus.toml
uv run diagnose-copybooks --config your-corpus.toml --output out/missing-copybooks.json
```

Worth running first on a corpus you've never built. One `COPY` the ProLeap
preprocessor can't resolve fails that whole member's parse, and parsing is the
expensive phase — one JVM per member, thousands of members. This scans the
`COPY` statements instead, so it reports in one pass what `make parse` would
take hours to tell you.

Resolution mirrors ProLeap's `CobolWordCopyBookFinderImpl` exactly, because a
diagnostic that disagrees with the parser is worse than none: a candidate
matches iff its full filename equals (ignoring case) the copy name itself or
`<name>.<ext>` for one of the configured `copybook_extensions`, and
`copybook_dirs` are listed non-recursively. That's stricter than the corpus
index, which indexes every file in `copybook_dirs` whatever its extension — so
a name can carry a real `file_path` in the graph and still fail the parse, and
the graph's UNRESOLVED count is a lower bound on what this reports.

stdout (or `--output`) is JSON and nothing else — missing name → program → the
lines its `COPY` statements are on — so `| jq` works. The human summary goes to
stderr. Those names are corpus identifiers; prefer `--output` to a shared
terminal on a client corpus.

`--fix DIR` writes an empty stub copybook into `DIR` for every missing name
nobody staged, so a parse gets past it:

```bash
uv run diagnose-copybooks --config your-corpus.toml --fix path/to/your/copybooks
```

That buys a **parse, not data**. A stubbed `COPY` declares nothing, so whatever
records, fields or `PROCEDURE` text the real member carried is absent from the
graph — the summary says so every time. Each stub is three fixed-format comment
lines saying what it is, not a zero-byte file, so a stub is greppable and
distinguishable from a truncated real member.

Two things it deliberately does not do. A name already on disk under an
*unlisted* suffix is never stubbed: the stub would resolve first and the real
member would never be read again — that one needs a `copybook_extensions` edit.
And `DIR` outside the config's `copybook_dirs` is **refused before anything is
created** — nothing written, the listed dirs printed, exit code 2. ProLeap lists
those directories and nothing else, so stubs anywhere else resolve nothing, and a
path outside them may belong to something that is not a copybook dir at all: one
`--fix <out_dir>/synthetic.csd` put a *directory* where `make csd` writes the
generated CSD, and the next build came out with 32,463 nodes and zero
`TRANSACTION`. A listed dir that does not exist yet is still created.

This one is a console script rather than a `make` target: `[project.scripts]` in
`pyproject.toml`, which is why the project is installed editable into the venv
instead of `package = false`.

### Diagnose unparseable JCL and COBOL before building

```bash
JCL_BRIDGE_JAR=jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
  uv run diagnose-jcl --config your-corpus.toml --output out/unparseable-jcl.json

PROLEAP_BRIDGE_JAR=proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
  uv run diagnose-cobol --config your-corpus.toml --output out/unparseable-cobol.json
```

Two more pre-flight reports, same shape as the copybook one: `--config` names
the corpus, JSON is the machine channel, the human summary is logged to stderr
with counts only, and the exit status is 0 whatever they find. They report; they
don't gate.

`diagnose-jcl` runs the build's own JCL parse phase and stops. It prints the four
numbers that say where a corpus stands — members parsed, members failed, steps,
DDs — which are the columns of the table in
`docs/corpus-onboarding-blockers.md`. The steps and DDs are the regression check:
a grammar change that recovers members has to leave every member that already
parsed with the counts it already had, and that delta is readable off two runs.

`diagnose-cobol` does the same for the COBOL side, and matters more, because the
build's COBOL phase dies on the *first* program the bridge rejects — thousands of
subprocesses and tens of minutes to learn one program's name. This one keeps
going and groups the rejections by **signature**: the parser's own exception
line with the quoted source text and the line and column numbers stripped out.
227 programs failing one way is a single fix; 227 failing forty ways is a survey,
and the summary tells you which you have.

That stripping is also what makes grouping loggable. A ProLeap message quotes the
bytes it choked on, and a missing-copybook error names the copybook and the
directories searched, so the full messages stay in the JSON and only the stripped
signature is logged. Neither tool ever logs a member name.

Both take `--max-workers` (default 4; `cobble-parse-corpus`'s `--jobs` defaults to
one per core instead, because that one is the run you wait on). `diagnose-cobol` writes
no cache: each ASG is written and unlinked at once, so peak disk is one ASG per
worker rather than the gigabytes a full corpus of them would be.

### Gate an ASG cache before field-level dataflow

```bash
uv run diagnose-asg-operands path/to/asg-cache-dir
```

Verifies a cached ASG directory carries structured subscripts on MOVE operands,
which the field-level dataflow analysis requires. Takes the directory path
directly, not `--config`, since checking a cache against another cache means
comparing two directories and a config names only one `asg_dir`.

Exit status is the gate:

| exit | meaning |
| ---- | ------- |
| 0 | precondition met, subscripted MOVEs present |
| 1 | precondition failed, no subscripted MOVEs |
| 2 | directory not found |
| 3 | some files unreadable |

The JSON on stdout reports five counts: bare, subscripted, ref-modified, total,
unreadable. The human summary goes to stderr.

### Field-level byte dataflow

```bash
uv run cobble-fields --config config/fields.toml --member PROGA PROGB   # one program and its neighbours
uv run cobble-fields --config config/fields.toml --all                  # the whole cache
uv run cobble-fields --config config/fields.toml --member PROGA --sweeps 3
```

Exactly one of `--member` and `--all` is required; both together, or neither, is
a usage error. The usual question is about the fields of one program, and a
whole-cache pass is minutes of fixpoint per member, so it is asked for rather
than defaulted into.

Reads the ASG cache `cobble-parse-corpus` wrote — no JVM, no corpus tree — and
writes five files to `<out_dir>`:

| file | one row per | holds |
| ---- | ----------- | ----- |
| `nodes.jsonl` | `FIELD` endpoint | nothing but the id — every attribute it once carried now has a table |
| `edges.jsonl` | `(node, source extent, target extent)` | the `FLOWS_TO` relation and `node`, the statement that moved the bytes |
| `extents.jsonl` | *declared* name | its `level`, its `usage`, and the byte ranges it owns |
| `defs.jsonl` | `(node, source extent)` | the statements whose writes reach that read |
| `aliases.jsonl` | (`LINK`/`XCTL`/`CALL` site, caller window) | the commarea window the caller and callee both address, or the reason they share none |

A `FIELD` id is `<program>.<field>`, because a field name is only unique within a
program: two copybooks routinely give one piece of storage two names. An edge
deliberately does not carry the guard condition — a reader asks
`cobble-srccfg-query guards` for that node's guards instead, which keeps
conditions out of the lattice they would otherwise multiply.

The split is the point: **the graph holds only what nothing outside it could
state.** The extents and defs tables are many-to-one against a flow, so neither
survives as an edge attribute. One read has as many reaching definitions as it has paths
(measured on the corpus: 862 flows with more than one, one with a hundred), and
one byte range as many declared names as it has groups and redefinitions over it
(30% of ranges are owned by more than one name). Pinned to the edge they were
duplicated per path and then deduplicated by endpoint, which kept one and dropped
the rest — nondeterministically. As relations of their own each is stated once
and all of it survives.

`extents.jsonl` is one row per name against the ranges it owns —
`{"id": "PROGA.WS-B", "level": 5, "usage": "DISPLAY", "extents":
["WS-B@working_storage[4:8]"]}`. Its own file because where a field *is* is true
whether or not a value ever moved through it. *Declared*, because an edge names
the smallest field covering the bytes it moved, so a group-level write puts the
group in the graph and leaves every child it filled out of it — and the child is
what a reader is asking about. One entry per range rather than a single span,
because `OCCURS` gives a name an occurrence per subscript and a span from the
first to the last would swallow the siblings between them. `level` is there
because a group with one child and a `REDEFINES` pair each own identical bytes,
so only the level says which contains which; `usage` because a partial overlap of
a `COMP-3` field is not a partial read of its value. A synthetic origin
(`<program>.LITERAL`, `FILE:<name>`, `%CICS-STATE`, `%CALL:<target>`) is not
storage and has no row at all.

An extent reads `NAME@region[start:end]`, with a trailing `~` when the range is
clamped rather than exact — a computed subscript lands somewhere inside it and
nothing knows where. The mark matters because the byte-for-byte correspondence
between a MOVE's two operands holds only for an exact target.

A group write is one edge naming the group, not one per child: which bytes each
child received follows from the two extents and the declared layout, so storing
it per child stated the same fact 7842 times over. `fields.query.contributed()`
is that derivation, and the artefact is lossless because of it.

`aliases.jsonl` is one row per call site **and shared caller window**, carrying
both sides of the window a `COMMAREA` shares — `caller_extent` and
`callee_extent`, equal in length because the window is the shorter of the two
declared areas, and past it the two areas are not both addressable. A row is
keyed by the site *and* the caller window rather than the site alone because a
commarea name declared in two records resolves to two caller cells on different
bytes: that site contributes a row per resolution, so a consumer joining on
`(caller, node)` must expect the fan-out. Not an edge: the relation is byte
identity across a call, rebased to the callee's offset 0, so the graph itself
stays intra-program. A site that reaches no window is still a row, naming what
stopped it (`dynamic-target`, `callee-not-in-cache`,
`callee-declares-no-commarea`, `empty-window`, …) rather than going missing, and
the JSON summary states `aliased` — distinct *sites*, not rows — against the
`alias_dead_ends` breakdown so the table's coverage is read off the run. A member
the walk's budget gave up on still contributes its rows: they need the caller's
layout, and the dequeue cap is reached long after that layout is built. Only a
member whose layout never built — the unsizeable-field skip — contributes none.
The table costs a full parse of every distinct callee's cache file, once per run,
to lay out its `LINKAGE` alone.

The config is its own table, holding only what this stage reads:

```toml
[fields]
asg_dir = "out/asg"
out_dir = "out/fields"
```

`--min-coverage` (default 0.60) is the floor for the fraction of writes the
analysis resolved to storage. The human report goes to stderr, a JSON summary to
stdout.

Two walks reach the answer, and `--iteration-factor` and `--sweeps` are their
budgets — mutually exclusive, because each binds only its own walk.

`--iteration-factor` (default 50) drives the worklist walk: dequeues allowed per
CFG node before a member is given up on with `dequeue cap N reached`. No constant
is right for every program. The bound is nodes × the lattice height at each node,
height is the distinct sources held at each extent, so a large member can need a
factor in the hundreds. The heartbeat carries an estimate from the queue's drain
rate; when it reads `past the N cap`, waiting buys nothing and the factor is what
to raise. Once `nodes reached` stops climbing, the remaining dequeues are
refining provenance rather than discovering the program.

`--sweeps N` runs the cheaper walk instead: at most N passes in reverse
postorder, stopping early on a pass that changes nothing. Reverse postorder is
what makes it cheap — every predecessor a node is reached through, back edges
aside, is already processed, so one pass carries a forward chain of any length,
where the worklist's FIFO order re-visits a node long before its predecessors
have settled. A member reported as **settled in k sweeps** is exactly as
complete as the worklist's answer; one still growing when the budget runs out is
an under-approximation — a subset of that program's flows, warned about by name
and counted as `unsettled` in the JSON summary. Nothing is invented either way,
because join and the transfer are monotone: a smaller entry state yields fewer
sources, never a wrong one. Two is the useful floor, since detecting settlement
across a back edge takes the pass that changes nothing; with no back edges at all
one pass is provably the fixpoint and reports settled immediately. What a single
sweep drops is narrow — a read whose feeding write sits later in the same loop
body.

The two walks report progress differently because only one of them can. A sweep
knows how many nodes it will visit before it starts, so it logs a true fraction
(`sweep 2, 2000/3919 nodes visited (51%)`) and a line per pass saying `settled` or
`still growing`; the worklist has a queue with no bound to compare against, so it
estimates from the drain rate instead.

Exit status is the gate:

| exit | meaning |
| ---- | ------- |
| 0 | every member analysed, coverage at or above the floor |
| 1 | coverage below the floor |
| 2 | ASG directory not found, config missing its `[fields]` table, or a `--member` the cache does not hold |
| 3 | one or more members skipped, unreadable, or colliding on program_id |

A named member absent from the cache ends the run before it starts: analysing
the rest would report coverage over a member set nobody asked for and exit 0
while the program in question went unexamined.

**The graph is intra-program.** A `CALL` or `LINK` contributes a synthetic
`%CALL:<target>` source and no callee summary; `aliases.jsonl` states which bytes
that site shares with its callee, but it is not an edge — naming several members
analyses each independently, so no edge crosses a program. A program_id
two members declare is exit 3 rather than a rename, since
one shared `edges.jsonl` has no filename to qualify — both members' field ids
would silently merge into one namespace.

`tests/dataflow/fields/` covers the byte-extent algebra (`may_alias`
over-approximates, `must_cover` under-approximates), the extent wire form and its
round trip, the per-statement transfer functions, the node-keyed fixpoint,
extent-to-name resolution, what each of the five files carries, the query
surface's five primitives, and the corpus pass's exit codes.

### Querying the field dataflow

```bash
uv run cobble-fields-query writers    WS-TOTAL --out out/fields
uv run cobble-fields-query readers    PROGA.WS-TOTAL --out out/fields
uv run cobble-fields-query reaches    WS-TOTAL --out out/fields --depth 4
uv run cobble-fields-query contains   SOME-REC --out out/fields
```

Joins the graph with the extents and defs tables and answers in bytes. The
queries are `extents`, `writers`, `readers`, `reaches`, `reached-by`, `contains`,
`within`, and `overlapping`; the subject is a field name, or `PROGRAM.FIELD` to
disambiguate one declared in several members.

**Every predicate intersects byte ranges rather than matching ids**, and that is
not an optimisation — it is the only way to get the right answer. Because an edge
names the smallest declared field covering the bytes it moved, a group-level write
leaves every child it filled out of the graph entirely. Measured on one corpus
field: three writers by byte overlap against one by id, and twenty-one readers
against **zero**. A consumer joining these files on node ids will silently miss
most of what it asks for.

Because 30% of ranges are owned by more than one declared name, an endpoint id is
a **label, not a claim**: where a record, a `REDEFINES` view of it and that view's
children all own the same bytes, the id is whichever of them the tie-break settled
on — the name the statement itself wrote, where a statement made the reference.
`overlapping` recovers the others. It is the only predicate that reports partial
overlap and the only one with no level comparison, which is what lets it answer the
two cases containment cannot: an equal-level alias, reported by neither `contains`
nor `within`, and a range straddling two records, contained by neither.

Ranges compare only within a program: a byte offset is a coordinate in one
member's region, so a walk that dropped the program would leak into members
nobody asked about. `reaches` and `reached-by` walk the closure of that
intersection to `--depth` (default 6), stopping on a field already visited over
overlapping bytes — both parts, because bytes alone prune a sibling inside a group
already reached, and an id alone prunes a second occurrence of a table entry.

Field names go to stdout and nowhere else, so the log stays safe to tail.

`load()` reads a directory and `store_of()` takes the rows directly, off one
assembly — an in-process caller and a reader of the published artefact cannot
answer differently. A missing table loads as empty rather than as an error, so a
directory an older build wrote is still worth querying.

### Render the HTML visualization

```bash
make render CONFIG=config/carddemo.toml   # reads <out_dir>/{nodes,edges}.jsonl -> writes <out_dir>/graph.html
```

`CONFIG=` is required here too (same as `build`/`sym`): `out_dir` comes from
the config's `corpus.out_dir` field, so `render_graph.py` looks in the same
place `build_graph.py` wrote to. `<out_dir>/graph.html` is a single
self-contained file (vis-network is vendored at
`cobble/knowledge_graph/vendor/vis-network.min.js` and inlined; no server,
no CDN, no network access needed). Open it directly in a browser. It has
checkboxes to filter by node/edge kind, a search box that highlights matching
node labels, and click-to-highlight-neighbors on any node. Requires
`<out_dir>/nodes.jsonl` / `<out_dir>/edges.jsonl` to already exist (i.e. run `make build`
first).

### Unit tests

```bash
make test   # uv run pytest, no JARs, no corpus, runs in well under a second
```

Unlike `make verify` (one big end-to-end golden-file check over the real
CardDemo corpus, needing JDK/Maven/CMake), `tests/` unit-tests cobble's pure
modules in isolation (grammars, dataclass transforms, graph merging) with
hand-built inputs, giving localized signal on which piece broke rather than
just "449/803 doesn't match." Coverage is still partial; see `tests/` for
what's covered so far.

### Formatting, linting, and pre-commit hooks

```bash
make fmt    # uv run python -m black .
make lint   # uv run lint-imports && uv run pyright && uv run python -m python_fp_lint check cobble/
```

`.pre-commit-config.yaml` wires these up (plus the terminology guard and
`make test`) to run automatically on every commit: `black` auto-formats and
re-stages, `pyright` and `python-fp-lint` report warnings without blocking
the commit, and `import-linter` / the unit tests block it on failure.
Architecture contracts live in `.importlinter` (e.g. `interpreter` may not
import `cics`/`jackal`/`knowledge_graph`/`bms_copybook_gen`, and those four
consumers may not import each other).

## What's here

| Path | What |
|------|------|
| `cobble/` | The ported extraction code, plus this repo's own driver scripts (see below); everything lives under one package so there's no Python at the repo root. Extraction modules are byte-for-byte / import-rewired from their `red-dragon-forge` counterpart (imports → `cobble.*`), with the two documented exceptions below (`cics/verb_source_asg.py`, `cics/flow_map.py`). Imports **no** production Python: only `cobble.*`, stdlib (configs are TOML, read with `tomllib`), and pip (`lark`, `networkx`, `antlr4-python3-runtime`). Includes `cobble/bms_copybook_gen/` (the copybook generator, run as `python -m cobble.bms_copybook_gen`). |
| `cobble/cics/cics_grammar/*.g4` | The ANTLR grammar **source** (`CICSzLexer.g4`, `CICSzParser.g4`). `make codegen` generates the `CICSz*.py` parser from these; the generated `.py` is gitignored, never shipped. |
| `cobble/cics/verb_source_asg.py` | **The one seam.** Production sources CICS verbs by *lowering* each program through the CICS strategy (which needs the VM). This replaces that with a VM-free walk of the typed `CobolASG`: it reads each `EXEC CICS` statement, resolves operands to their static `VALUE` clauses, and routes the `CicsVerb`s through the byte-for-byte `flow_graph_core._verb_edge`. |
| `cobble/cics/flow_map.py` | Ported, and the one other module that diverges — in how the pass *reports*, not in what it emits. It returns what it read and what it could not (production reports into a list the caller hands down), and it says where it is: a bar over its per-program loop, which is where a corpus run spends its time, and each member's name at DEBUG before it is read. Every node and edge, and the order they reach the sink, are unchanged. |
| `cobble/build_graph.py` / `cobble/compare.py` | This repo's own driver scripts (not ported from `red-dragon-forge`): extract the graph → `out/` (`cobble-build --config <path>`, reading the config's `asg_dir` — needs `make parse` first); identity-diff `out/` vs `reference/` (`python -m cobble.compare`). |
| `cobble/parsing/` | **Stage-1.** The one place a corpus is turned into ASGs and the one place they are read back: `parse_corpus.py` writes one JSON ASG per member (`cobble-parse-corpus --config <path>`), `asg_cache.py` owns the naming rule and the reader every later stage calls, `config.py` is the parse's own config. Nothing downstream starts a JVM. |
| `cobble/corpus_config.py` | `CorpusConfig`/`BmsConfig` dataclasses + TOML loading (`tomllib`, stdlib); `cobble.build_graph`/`cobble.generate_sym` read the corpus location/layout from here instead of a hardcoded CardDemo path. `asg_dir` is an input: the cache Stage-1 wrote. |
| `config/carddemo.toml` / `config/parse-carddemo.toml` | The two tracked configs CardDemo uses — the corpus one for `make build`/`make sym`/`make csd`/`make render`, the parse one for `make parse`. Copy them as a starting point for a different corpus; `config/parse.example.toml` documents the parse shape with no corpus in it. |
| `cobble/corpus_index.py` / `cobble/file_location.py` | `CorpusIndex` resolves every `(NodeKind, id)` to a `FileLocation` (a real `Path`, or a `NoFileLocation` explaining why not: not file-based, no CSD/definition source, or genuinely unresolved) once per run, from the same `CorpusConfig`. Every extractor and `GraphWriter` resolve a given node identically regardless of call order, which is what lets `GraphWriter` stream nodes keep-first with no merge step. |
| `cobble/render_graph.py` | Render `<out_dir>/{nodes,edges}.jsonl` as a self-contained interactive HTML graph at `<out_dir>/graph.html` (`python -m cobble.render_graph --config <path>`; `out_dir` comes from the config's `corpus.out_dir` field. `cobble/knowledge_graph/export.py` reads the NDJSON, `merge.py` builds one `networkx.MultiDiGraph`, `render.py` inlines the vendored `vis-network.min.js`). |
| `tests/` | The pytest unit suite (`make test`), mirroring `cobble/`'s package structure. No JARs/corpus needed; pure modules tested in isolation with hand-built inputs. |
| `cobble/generate_sym.py` | **Stage-0.** Generates the BMS symbolic copybooks: `hlasm_export <map>.bms --syslib bms-macros/ | python -m cobble.bms_copybook_gen → sym/*.cpy` (`python -m cobble.generate_sym --config <path>`). |
| `cobble/generate_csd.py` / `cobble/cics/synth_csd.py` | **Stage-0, optional.** Reconstructs a CSD a corpus arrived without, so its CICS members reach the flow stage at all → `<out_dir>/synthetic.csd` (`python -m cobble.generate_csd --config <path>`). `synth_csd.py` is the pure core: literal transaction ids in the source, placed on members by the config's `transid_rules`, everything else marked synthetic or reported — never guessed. |
| `reference/` | The 449/803 identity golden (copied from the production fitness golden, the *target*, not an input to the extraction). |
| `proleap-bridge/` | The COBOL→JSON ASG bridge (copied Maven source). Depends on the **forked** `proleap-cobol-parser` (`io.github.uwol:proleap-cobol-parser:4.0.0`, **not on Maven Central**) vendored as the submodule `proleap-bridge/proleap-cobol-parser`, built (`mvn install`) *before* the bridge. |
| `jcl-bridge/` | The JCL→JSON bridge (copied Maven source, self-contained). |
| `bms-macros/` | The hand-written `DFHMSD`/`DFHMDI`/`DFHMDF` prototype macros (assembler SYSLIB for `hlasm_export`). Source, not generated. |
| `vendor/carddemo/` | The CardDemo corpus, a git **submodule** (includes `app/bms`, the BMS map sources). |
| `vendor/che-che4z-lsp-for-hlasm/` | The HLASM language-server **fork** (submodule); `hlasm_export` is built from it (CMake + Ninja, OS-agnostic `build.sh`: CMake picks the system toolchain). |
| `.github/workflows/reproduce.yml` | CI: build everything from source on `ubuntu-latest` and verify 449/803. |

## Submodules (all pinned)

| Path | Repo |
|------|------|
| `vendor/carddemo` | `aws-mainframe-modernization-carddemo` (the corpus) |
| `vendor/che-che4z-lsp-for-hlasm` | forked che-che4z HLASM LSP (builds `hlasm_export`) |
| `proleap-bridge/proleap-cobol-parser` | forked `proleap-cobol-parser` (builds `4.0.0`) |

## Invariant

`cobble/**` imports zero live production Python (no bare `interpreter` / `cics` /
`jackal` / `knowledge_graph` absolute imports; only `cobble.*`):

```bash
grep -rE '^\s*(import|from)\s+(interpreter|cics|jackal|knowledge_graph)\b' cobble
# (no output)
```

The only coupling to RedDragon is (a) the two bridge JARs and `hlasm_export`,
invoked as subprocesses, all **built from source**, and (b) the one seam
(`cobble/cics/verb_source_asg.py`). The graph identity (449/803) is reached by
independent Python that shells out to those tools: the decoupling, proven from a
repo that contains no production interpreter code and ships no generated
artifacts.

## Acknowledgments

The JCL grammar (`jcl-bridge/src/main/antlr4/org/jackal/jcl/JCLLexer.g4` /
`JCLParser.g4`) and the CICS `EXEC CICS` grammar
(`cobble/cics/cics_grammar/CICSzLexer.g4` / `CICSzParser.g4`, adapted for the
Python3 ANTLR runtime) are both vendored from **Craig Schneiderwent's
[mapa](https://github.com/cschneid-the-elder/mapa)** project; thank you for
making these available. See `jcl-bridge/PROVENANCE.md` for the exact vendored
commit/files, and `jcl-bridge/LICENSE` for mapa's MIT license text.

## License

MIT; see [LICENSE.md](LICENSE.md). Project rationale in [PHILOSOPHY.md](PHILOSOPHY.md).
The vendored `cobble/knowledge_graph/vendor/vis-network.min.js` ships under its
own license: see `cobble/knowledge_graph/vendor/VIS_NETWORK_LICENSE.md`.
The vendored mapa grammars (see Acknowledgments above) ship under their own
MIT license: see `jcl-bridge/LICENSE`.
