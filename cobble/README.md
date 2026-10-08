# cobble

A **VM-free** knowledge-graph extractor for COBOL/CICS/JCL mainframe codebases,
living in the `red-dragon-forge` workspace. It is a file-by-file **port** of the
streaming graph pipeline, kept decoupled from the RedDragon interpreter/VM. Point
it at any corpus via a TOML config (see [Point this at your own
codebase](#point-this-at-your-own-codebase)); the AWS **CardDemo** corpus is the
proof case, where it builds a **448-node / 836-edge graph** from
nothing but the corpus (forge's `vendor/carddemo` submodule) and the tools forge
builds from source.

Beside the graph, cobble analyses each program statically, from the same ASG
cache and without running it: a control-flow graph per program (`srccfg`), a
byte-level dataflow fixpoint over every field (`dataflow/fixpoint`, `dataflow/fields`)
that also resolves dynamic `CALL`/`XCTL` targets for the graph, and the queries,
traces and views built on those.

Everything generated (the BMS symbolic copybooks and the ASG cache) is generated
from source; nothing pre-generated is shipped.

## Setup

Cobble builds nothing itself. Every tool it shells out to is built by `make setup`
at the **forge root**:

| Tool | Forge path |
|------|------------|
| ProLeap COBOL bridge JAR | `vendor/red-dragon/proleap-bridge/` |
| JCL bridge JAR | `jackal/jcl-bridge/` |
| `hlasm_export` | `cicada/third-party/che-che4z-lsp-for-hlasm-fork/` |

Requires: `git`, JDK 21+, Maven (bridges); CMake + Ninja + a C++ toolchain, e.g.
LLVM@18 (`hlasm_export`; `make setup` names any that are missing); and
[`uv`](https://docs.astral.sh/uv/).

```bash
make setup   # at the forge root
```

Cobble has no Makefile: each stage is an entry point run with `uv run` from
`cobble/`, after `. ../bridge-env.sh` exports the bridge JAR paths.

| Command | What it does |
|---------|--------------|
| **Before parsing** | |
| `diagnose-copybooks --config <corpus> [--fix <dir>]` | Which `COPY` statements the parser will not resolve, without running it; `--fix` writes an empty stub for each |
| `diagnose-cobol --config <corpus>` | Which COBOL programs the ProLeap bridge will not parse |
| `diagnose-jcl --config <corpus>` | Which JCL members the JCL bridge will not parse |
| `cobble-sym --config <corpus>` | Generate the BMS symbolic copybooks from their `.bms` sources |
| `cobble-csd --config <corpus> --out <file>` | Synthesize a CSD for a corpus that arrived without one |
| `cobble-bms-metadata --config <corpus> [--output <file>]` | Each BMS map's fields and attributes as JSONL, via `hlasm_export` |
| `cobble-bms-render --config <corpus> [--map <name>] [--format text\|html]` | Draw BMS maps as 3270 screens |
| **Parsing** | |
| `cobble-parse-corpus --config <corpus> [--force]` | Parse the corpus to one JSON ASG per member — the cache every later stage reads; members with an ASG are skipped unless `--force` |
| `cobble-expand-corpus --config <corpus> --out-dir <dir>` | Write each member's expanded source (copybooks inlined); no ASG, nothing downstream reads it |
| **Knowledge graph** | |
| `cobble-build --config <corpus> --output <file> [--dynamic-call-targets <targets.jsonl>]` | Extract the graph to one file, a tagged row per node and edge |
| `cobble-compare --graph <file>` | Identity-diff vs `reference/graph.jsonl` (448/836) |
| `cobble-render` / `cobble-render-webgl --graph <file>` | Render the graph file as an interactive HTML / WebGL page beside it |
| `cobble-viz-callgraph --graph <file> --cfg <jsonl> --out <file>` | The program-level call dependency graph, for `cobble.viz`'s renderer |
| **Variable dependency graph** (name-level, coarse) | |
| `cobble-depgraph --config <depgraph>` | Which variables feed which, by name, over the whole ASG cache |
| `cobble-depgraph-render --config <depgraph>` | That graph as a WebGL page |
| **Source control-flow graphs** | |
| `cobble-srccfg-build PROGRAM --config <corpus> [--dynamic-call-targets <targets.jsonl>] [--output <file>]` | Build one program's source CFG **and every program it transitively calls**, through dynamic calls too when given a targets file (the combine's, or the fixpoint's), as JSONL rows |
| `cobble-srccfg-dot` / `cobble-srccfg-webgl --cfg <jsonl> --output <file>` | Draw that CFG as Graphviz DOT / a self-contained WebGL page |
| `cobble-srccfg-query {guards,provenance,coassign} <subject> --cfg <jsonl>` | A node's guards, a field's provenance by name, or the fields assigned together with one |
| `cobble-srccfg-reachability-walk --cfg <jsonl> --from <node-id>` | What can run from one PERFORM until control returns, and every other way it ends, as rows `cobble-srccfg-dot`/`-webgl` render |
| `cobble-srccfg-dfs-walk --cfg <jsonl> --from <node-id> [--mode primary\|tree]` | The same stepper driven depth-first instead of level-by-level: a readable execution-*order* trace (`primary`: first arm at every branch, alternates noted; `tree`: both arms, recursed) |
| **Byte-level field dataflow** | |
| `cobble-extents --asg-dir <cache> --out <file>` | Every member's declared field layout in bytes — the table the dataflow stages read |
| `cobble-dataflow-fixpoint --asg-dir <cache> --out-dir <dir> --extents <file> (--all \| --member <name>...)` | The fixpoint: which writes reach every read, the values fields can hold, dynamic call targets, what every jump hands over (`graph`, `defs`, `aliases`, `targets`, `jumps` and the run summary) |
| `cobble-dataflow-fixpoint-query <query> <field> --fixpoint-dir <dir> --extents <file> [--links <links.jsonl>]` | Ask the fixpoint's output for a field's `writers`, `readers`, what it `reaches` or is `reached-by` (in statement order), and byte containment/overlap |
| `cobble-dataflow-area-need --asg-dir <cache> --extents <file> --out <area-need.jsonl> [--config <toml>] [--fixpoint-dir <dir> --combined-dir <dir>] [--explain MEMBER] [--explain-over BYTES] [--max-workers N]` | Once per corpus, one row per member: which bytes of the commarea or `USING` areas it receives its call targets read on entry, and which its callers read back after it returns. A call that names its program by a literal is charged with that callee's row; a callee not in the corpus, with every byte. A dynamic XCTL, LINK or CALL, and a `RETURN TRANSID`, are resolved within their own program by reaching definitions: the operand's values are followed forward over the CFG from the `VALUE` clause image, and the site resolves only when every definition reaching it overwrites all of it with a literal, a transaction id mapped to its program through the CSD of `--config`. A resolved site is charged with only the programs it reaches, for entry and read-back alike. `--fixpoint-dir` with `--combined-dir` (and `--config`) adds the sites a finished fixpoint and combine resolved completely. Any other dynamic site is charged with the union over every member for that kind of area (commarea or `USING`). A byte-for-byte MOVE (a group on either side, or both alphanumeric, with no subscript and a start the compiler knows, `LENGTH OF` included) counts only the bytes it copies; any other read counts the whole source. Loads each member once, every member starting at no bytes, then reruns liveness in rounds until no row changes. `--explain MEMBER` then prints the bytes that member needs, what each demand source alone accounts for (read-back split into all of it and the part unresolved dynamic calls charge to every member), and the writes that make more live than their target keeps; `--explain-over BYTES` does the same for every member needing at least BYTES. Each worker explains its own members from what it kept at load, rebuilding nothing. `cobble-dataflow-fixpoint --call-targets-only --narrow-areas <area-need.jsonl>` reads it and refuses a file in the older single-union format |
| `cobble-dataflow-fixpoint-diagnose --asg-dir <cache> --member <name> [--max-steps N] [--every N] [--call-targets-only] [--anonymise]` | Walk one member's fixpoint step by step and report where the work goes: the most-dequeued nodes and whether each dequeue grew anything, the cycle each sits in, the fields that keep gaining writers, the tallest writer sets, and reached nodes and state size over time. `--anonymise` swaps paragraph and field names for stable aliases |
| `cobble-dataflow-combine --config <corpus> --fixpoint-dir <dir> --out-dir <dir> (--all \| --member <name>...)` | Link the fixpoint's per-program results across programs: dynamic targets resolved through the bytes callers hand over, plus the links used |
| `cobble-fields-trace <program> --asg-dir <cache> --out <file> [--record-paths <file>] [--single-program] [--force]` | Sample execution paths from a program's entry and record, per path, where each field's bytes came from; `--single-program` keeps to that program's own CFG; an existing `--out` is left as it is unless `--force` |
| `cobble-trace-query {forward,backward} <field> --trace <file>` | Provenance over a trace: what a field affects, or what feeds it |
| `cobble-viz-pathwalk --cfg <jsonl> --paths <file> --output <html>` | Animate a trace's recorded paths over the paragraphs, with chosen fields' provenance |
| `cobble-fields-access --cfg <jsonl> --asg-dir <cache> --out <file>` | Every site in a CFG file that reads a field, with the bytes it reads |
| `cobble-access-query <field> --accesses <file> --extents <file>` | The access sites for a field, by name and by overlapping bytes |
| **Tests** | |
| `python -m pytest` | Run the pytest unit suite |

### Build the graph from CardDemo

```bash
. ../bridge-env.sh
uv run cobble-sym --config config/carddemo.toml              # generate the BMS symbolic copybooks
uv run cobble-parse-corpus --config config/carddemo.toml     # parse the corpus -> one JSON ASG per member in out-parsed/
uv run cobble-extents --asg-dir out-parsed --out out-fields/extents-input.jsonl   # every member's declared layout
uv run cobble-dataflow-fixpoint --asg-dir out-parsed --out-dir out-fields \
  --extents out-fields/extents-input.jsonl --all             # -> out-fields/targets.jsonl, among others
                                                             # (--call-targets-only when targets are all you need)
uv run cobble-dataflow-combine --config config/carddemo.toml --fixpoint-dir out-fields \
  --out-dir out-combined --all                               # link the programs -> out-combined/targets.jsonl
uv run cobble-build --config config/carddemo.toml --output out/carddemo.jsonl \
  --dynamic-call-targets out-combined/targets.jsonl          # extract the graph -> out/carddemo.jsonl
uv run cobble-compare --graph out/carddemo.jsonl             # identity-diff against reference/graph.jsonl (must be empty: 448/836)
uv run cobble-render --graph out/carddemo.jsonl              # -> out/carddemo.html
```

`demo/carddemo/run.sh`, run from the forge root, does all of this and more in one
go: the fixpoint, the combine, the graph and its WebGL page, one program's source-CFG
closure (`SRCCFG_PROGRAM`, default `COSGN00C`) and one field trace (`TRACE_PROGRAM`,
default `CBACT01C`). Every artefact lands under `demo/carddemo/output/`, which is
git-ignored; its configs (`carddemo.toml`, `srccfg.toml`) are `config/carddemo.toml`
with the generated directories moved there.

### Source CFGs, and drawing a call closure

`cobble-srccfg-build` walks out from one program through its calls, building the CFG
of everything it reaches. The result is a *bundle*: one CFG per program, plus the
calls linking them — not a single merged graph.

```bash
. ../bridge-env.sh
uv run cobble-srccfg-build COSGN00C --config config/srccfg.toml --output closure.jsonl
uv run cobble-srccfg-webgl --cfg closure.jsonl --output closure.html    # the whole closure
uv run cobble-srccfg-dot   --cfg closure.jsonl --output one.dot         # graphviz DOT
```

The bundle is JSONL: one row per line, each tagged with a `type`. A `program` row
opens each CFG, its `node` and `edge` rows follow, and the `call` rows joining the
programs come after all of them; the first program is the seed. A CFG is what the
corpus build writes one of per member, unchanged. A call row names the calling
program and node, the callee and **the entry node in it the call lands on** — the one
thing the call site itself does not know, and exactly what a reader crossing into the
callee needs, so no consumer has to rebuild the join to walk the closure:

```json
{"type": "call", "caller": "COSGN00C", "node": "READ-USER-SEC-FILE/1.when.0.0.then.5.else.0", "transfer": "CICS_XCTL", "program": "COMEN01C", "entry": "MAIN-PARA#label", "resolved": true, "commarea": "CARDDEMO-COMMAREA", "expression": "", "reasons": [], "certain": true}
```

A callee the ASG cache does not hold — another subsystem's module, or a member whose
parse failed — is still in the closure, as an **external** program: its `program` row
carries `"external": true`, and its CFG is the single node `%EXTERNAL#label` with no
edges. Its calls land on that node like any other, and the caller carries on past a
CALL or LINK as usual, so it draws as a call that returns into a program with no
inside. Unresolved sites with no candidate program are kept with an empty `entry`,
because "this program calls something we cannot name" is an answer.

Every paragraph has a `<name>#label` node where control enters and a `<name>#end`
node where it leaves, and so does every section: a section's label flows into its
first paragraph, and its last paragraph's end flows into the section's end. So
`PERFORM`, `GO TO` and a `WHENEVER`'s `GO TO` land on a section's label when they
name one, a `PERFORM` of a section returns from the section's end, and falling off
one section enters the next through its label. Names are upper-cased, declared ones
and jumped-to ones alike, since COBOL does not distinguish `Main-Para` from
`MAIN-PARA`: node ids use the upper-case spelling whatever the source wrote.

A performed range always runs, so a `PERFORM` that can return has no edge past it:
its node's `resume` names where it continues, and the range's `RETURN` edge lands
there. Two kinds keep a `FLOW` edge to the next statement instead and have no
`resume`: a `PERFORM` of a range the program does not declare, which has no other
way on, and one whose range end nothing reaches, which by the graph never returns
but is kept reachable on purpose — the graph can be wrong about that (an `ALTER`ed
`GO TO`, control flow the parse dropped), and dead code loses every flow after it.

**Dynamic calls.** A `CALL`/`XCTL`/`LINK` through a field names no program, so by
default it pulls nothing into the closure. Given
`--dynamic-call-targets <targets.jsonl>` (the flag `cobble-build` takes) — the
combine's, or the fixpoint's when no combine was run — each
such site's candidates are built like any callee — transitively, so a candidate's own
dynamic calls are followed too — and the site becomes one call per candidate, joined
to that candidate's entry. `expression` names the field the site calls through,
`reasons` carries the row's doubt, and `certain` is the three-way rule's proven case:
one candidate and no reasons. A site with no candidates stays one call naming the
field, with its reasons and an empty `entry`. A named file that does not exist stops
the build before it starts.

`cobble-srccfg-dot` and `cobble-srccfg-webgl` draw a certain dynamic call like a
literal one (`CALL`, dashed orange in DOT) and every other candidate as
`CALL_CANDIDATE` (dotted grey in DOT, its own colour on the WebGL page), so a hop
the analysis is unsure of looks unsure. A site with no candidates draws nothing.

```bash
uv run cobble-srccfg-build COSGN00C --config config/srccfg.toml \
  --dynamic-call-targets out-combined/targets.jsonl --output closure.jsonl
```

Every CFG file has one shape — JSONL rows, as above — whether it holds a whole
closure or the single program the corpus build writes, which is one `program` row and
no `call` rows. A line that is not a row, including a file in the one-document shape
this replaced, is refused with its line number rather than half-read;
`cobble-srccfg-build` regenerates it.

**`dot` for one program, `webgl` for a closure.** Graphviz gives the better picture —
ranked top to bottom, edges labelled — but it is a layered layout with crossing
minimisation and on a whole closure it does not finish: a 6,638-node / 9,468-edge
bundle ran past twelve minutes and was killed, where `sfdp` lays the same graph out in
about five seconds. `webgl` takes `--program MEMBER` to draw one member instead.

The WebGL page is the only target that folds the bundle into one connected graph: every
node is namespaced by its program, and resolved calls become cross-program edges.
That fold is `dataflow/srccfg/joined.py`, shared with anything else that walks a
closure, so a traversal crosses a call exactly where the picture draws it. Positions
are computed at build time, so the browser opens an arranged graph and simulates
nothing.

Two things that make a closure look smaller than the code is. A call the resolver could
not pin contributes no edge, and a callee missing from the ASG cache is logged
(`called but not in the ASG cache; not built`) and skipped — so run
`cobble-parse-corpus` over everything you want reachable first.

Note the analyses are **per program**: `cobble-srccfg-query`'s guards and provenance run
over one CFG at a time, so a field crossing a COMMAREA stops at the caller's boundary.
Cross-program field flow is a different system — `cobble/dataflow/fields/`.

`--config` is required by every stage that reads the corpus; there's no default, so
a bare `cobble-build` fails with a clear error instead of silently assuming CardDemo.
`cobble-build` also requires `--output`, the graph file it writes: one JSON line per
node and per edge, each tagged `"type": "node"` or `"type": "edge"`. The stages that
read only that file — `cobble-compare`, the renderers, `cobble-viz-callgraph` — take it
as `--graph` and no config.
Every stage, the parse included, reads the same **corpus** config, so the parse
and the build cannot disagree about which members and copybook dirs `asg_dir`
holds. To parse differently for a special case, point `cobble-parse-corpus` at a
copy of the config. Drop generated output with `rm -rf out out-parsed sym`; `sym/` is a
`copybook_dirs` entry, so `cobble-sym` has to run again before the next build.

`cobble-parse-corpus` and `cobble-expand-corpus` are the two stages that start a JVM,
at 4-7 seconds per member. Both refuse to start at all if any `copybook_dirs` entry is
not an existing directory, naming it and why: ProLeap's copybook finder reads
`File.listFiles()` unguarded, so such an entry is a Java NullPointerException on every
member rather than a missing copybook, and each stage would otherwise record that as
the member's permanent failure. `sym` is the usual one — it is written by `cobble-sym`,
so run that first. Both are **resumable**, each on its own output: the parse
skips a member whose ASG (or recorded failure) is already in `asg_dir`, so re-running
it after an interrupt costs nothing for what it already did. Delete `asg_dir` to force
a full reparse after a bridge or grammar change.

`cobble-expand-corpus` stops one stage earlier than the parse and writes the text the
COBOL grammar is handed — copybooks inlined, continuations folded, comments stripped —
as one `<member>.cbl` per member. That is what to read when a member will **not** parse,
which is exactly when no ASG exists to read instead. It resumes on `--out-dir` rather
than on `asg_dir`, deliberately: keyed on the ASG cache it would skip every member of an
already-parsed corpus and write nothing. A member it cannot expand gets the same
`<member>.fail` record the parse uses, for the same reason — a missing copybook is
permanent until the copybook arrives. Nothing downstream consumes the output, which is
why the destination is a flag and not a config key.

`cobble-build` re-runs the four extractors (CALL/COPY, CICS flow, JCL, batch
FILE-CONTROL) from scratch every time, reading the ASGs `cobble-parse-corpus` wrote
rather than parsing again; safe to re-run after touching any extractor code. Touch
the corpus itself and `cobble-parse-corpus` has to run again first — a member with no cached ASG
is reported as one skipped member, not silently reparsed.

### Reachability from a PERFORM, and execution order

`cobble-srccfg-reachability-walk --cfg <file> --from <PERFORM node id>` answers "what can run
from this PERFORM until control comes back, and how else can it end". It walks
the first program in a `cobble-srccfg-build` file over states of a node and the
PERFORMs open there, so a range end returns only to an open PERFORM whose range
ends there and falls through otherwise — the call-stack knowledge a plain BFS over
the CFG lacks. It is reachability, not path enumeration: each state is visited once.

| At | The walk |
| --- | --- |
| a PERFORM | opens a frame for its resume point and enters the range; never takes the edge past it |
| a range end | returns from the innermost open PERFORM whose range ends here — matched by the end, so two PERFORMs resuming at one statement stay apart — else falls through |
| a GO TO | follows it; a GO TO out of a range keeps the pending return |
| a decision | follows every arm |
| a recursive PERFORM | is not entered (`refused`); the walk resumes after it |
| a PERFORM of an undeclared range | is stepped past (`unresolved`) |
| a CALL or LINK | is stepped past; other programs are not entered |

Output is JSONL on stdout, written as the walk goes: the reached nodes and the
edges actually taken, in the src-cfg row format, so `cobble-srccfg-dot` and
`-webgl` draw it; and, as each is found, `outcome` rows — `returns`, `stop-run`, `goback`,
`exit-program`, `abend`, `xctl`, `cics-return`, `unhandled-condition`, `dead-end`,
each at its node — plus `unresolved` and `refused` rows, and a last `summary` row
with the number of states visited. A missing summary means the walk did not
finish. The graph does not keep the stack: a paragraph reached from two
PERFORMs shows both returns, so one route through the picture is not
guaranteed to be a real execution.

Rows arrive level-by-level — distance from the seed, not runtime sequence.
`cobble-srccfg-dfs-walk` drives the identical stepper (`reach/expand.py`'s
`expand()`/`start()`, nothing about PERFORM/RANGE_END/recursive-PERFORM
handling reimplemented) depth-first instead, which is what makes it the
faithful tool for "what executes, in order": `--mode primary` is one
straight line, the first arm at every branch, with every untaken alternate
noted inline rather than expanded; `--mode tree` recurses both arms of
every branch (the same reachable set as `cobble-srccfg-reachability-walk`, shown in
real control order instead of BFS levels). A TEST node has two live
successors in general, so there is no single "the" execution order for a
program with any conditional in its reachable set — cross-check
`--mode primary`'s branch points against source before calling any one
arm "the" answer, and read every `outcome` event it prints before
claiming a path returns to its caller: a GOTO buried in the reachable set
can leave the task entirely and never come back, same program, different
path.

### Point this at your own codebase

`cobble.build_graph`/`cobble.generate_sym` take a required `--config <path>`
flag; nothing about a specific corpus is hardcoded in Python. `config/carddemo.toml` is both the config CardDemo uses and a
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
asg_dir = "out-parsed"                  # what `cobble-parse-corpus` wrote; an INPUT to this stage

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

`cobble-parse-corpus` reads `cobol_dir`, `cobol_globs`, `copybook_dirs` (searched
in order), `copybook_extensions` (`""` resolves a bare `COPY` name) and `asg_dir`
from that same `[corpus]` table, and the bridge JAR from `PROLEAP_BRIDGE_JAR`
(`. ../bridge-env.sh`).

One JSON ASG per member, named for the **member's filename**, not its
`PROGRAM-ID`: `MYPROG.cbl` → `MYPROG.json`. Two members declaring the same
`PROGRAM-ID` is normal on a real corpus, and naming the cache after the id would
have one overwrite the other. A member that won't parse gets a `.fail` beside it
carrying the parser's message, and is retried on every run, since the copybook it
lacked may have arrived since; only a member with an ASG is skipped. `--force`
re-parses every member. A re-parse whose outcome changes removes the other record,
so a member never has both an ASG and a `.fail`.

Then run:

```bash
uv run cobble-sym           --config your-corpus.toml   # first, if you have BMS maps: sym/*.cpy
uv run cobble-parse-corpus  --config your-corpus.toml   # then the parse -> one ASG per member
uv run cobble-build         --config your-corpus.toml --output out/your-corpus.jsonl   # then the graph -> that one file
uv run cobble-render        --graph out/your-corpus.jsonl   # optional HTML visualization
```

That order matters: `cobble-sym` writes the symbolic copybooks the parse resolves
`COPY` against, and `cobble-build` reads what the parse wrote. `cobble-parse-corpus`
takes `--jobs N` — one worker process, and so one JVM, each — defaulting to one per
core. It names its own bridge JAR in `bridge_jar` and reads no environment variable
for it, and it refuses to start when that path is not a file.

`cobble.compare`'s golden-file check stays CardDemo-specific: it's not
meaningful against a different corpus's output.

### Visualise pipeline outputs

`cobble.viz` turns the JSON outputs of the pipeline stages into self-contained
HTML files — open in any browser, no server required.

```bash
# Call dependency graph — which programs CICS-LINK to which
uv run cobble-viz-callgraph \
  --graph  out/carddemo.jsonl \
  --cfg    <srccfg_dir>/cfg-<ENTRY>.jsonl \
  --out    out-viz/call-dep.json

# Sequence diagrams — cross-program call order + per-program PERFORM trees
uv run cobble-viz-sequence \
  --cfg    <srccfg_dir>/cfg-<ENTRY>.jsonl \
  --entry  <ENTRY_PROGRAM> \
  --out    out-viz/sequences.json

# Render either as HTML
uv run cobble-viz-render --input out-viz/call-dep.json   --mode callgraph --out call-dep.html
uv run cobble-viz-render --input out-viz/sequences.json  --mode top       --out sequence-top.html
uv run cobble-viz-render --input out-viz/sequences.json  --mode program   --program <PROG> --out sequence-prog.html
```

`--cfg` is the JSONL produced by `cobble-srccfg-build`; the program list and
entry point are both derived from it automatically.  `--entry` is optional —
omitted, it picks the program with no callers within the subgraph.

Render modes:

| Mode | Input | Renderer | Output |
|---|---|---|---|
| `callgraph` | `call-dep.json` | vis.js force-directed | Interactive node graph |
| `top` | `sequences.json` | Mermaid sequenceDiagram | Cross-program call sequence |
| `program` | `sequences.json` | Mermaid sequenceDiagram | Per-program PERFORM tree |

Program labels are shortened by stripping the longest common uppercase prefix
across all programs in the subgraph.

The `corpus-viz-dataflow` and `corpus-viz-render --mode dataflow` commands that
trace commarea fields to VSAM record writes are corpus-specific and live in
the `corpus_viz` package in the analysis tooling, not here.

### Recover a CSD your corpus never shipped

A CSD is an export of a running CICS region, and plenty of handovers don't
include one. With `csd_files` empty, `build_graph` skips the CICS flow stage
entirely: no transaction gets a worklist entry, so no member is scanned for its
`EXEC CICS LINK`/`XCTL` operands and none of those edges reach the graph.

```bash
uv run cobble-csd --config your-corpus.toml --out out/synthetic.csd   # --out is required
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

Because it lives wherever `--out` put it, cleaning that directory leaves
`csd_files` pointing at a path nothing has written — so `build_graph` **refuses to start** when a
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
`COPY` statements instead, so it reports in one pass what `cobble-parse-corpus` would
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
`--fix out/synthetic.csd` put a *directory* where `cobble-csd` had written the
generated CSD, and the next build came out with 32,463 nodes and zero
`TRANSACTION`. A listed dir that does not exist yet is still created.

This one is a console script like every stage: `[project.scripts]` in
`pyproject.toml`, which is why the project is installed editable into the venv
instead of `package = false`.

### Diagnose unparseable JCL and COBOL before building

```bash
JCL_BRIDGE_JAR=../jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
  uv run diagnose-jcl --config your-corpus.toml --output out/unparseable-jcl.json

PROLEAP_BRIDGE_JAR=../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
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


### Field-level byte dataflow

```bash
uv run cobble-extents --asg-dir out-parsed --out out-fields/extents-input.jsonl     # the layout, once per corpus change
uv run cobble-dataflow-fixpoint --asg-dir out-parsed --out-dir out-fields --extents out-fields/extents-input.jsonl --member PROGA PROGB
uv run cobble-dataflow-fixpoint --asg-dir out-parsed --out-dir out-fields --extents out-fields/extents-input.jsonl --all
uv run cobble-dataflow-fixpoint --asg-dir out-parsed --out-dir out-fields --extents out-fields/extents-input.jsonl --member PROGA --sweeps 3
uv run cobble-dataflow-fixpoint --asg-dir out-parsed --out-dir out-targets --extents out-fields/extents-input.jsonl --all --call-targets-only
```

`--call-targets-only` keeps, at each node, only the entries some later read can still
need. Before each member's walk, the demand is found from the program itself: every
dynamic `CALL`/`XCTL`/`LINK` target, every area a jump hands over, and the LINKAGE
areas read at an exit or a CICS `RETURN`, each at the node it is read at. A backward
liveness pass carries that demand over the program's writes. A write overlapping
something live makes its sources live before it, and only an exact strong write that
covers a range kills it. Every write still runs. Entries that overlap nothing live at
the next node are dropped, so `targets.jsonl`, `jumps.jsonl` and the combine's
results equal a full run's, while `graph` and `defs` keep only rows for writes that
are live afterwards. Each member's `counts.json` records the scope and both sizes:
`relevant` of `tracked` written extents. An out-dir holds one scope: rerunning in the
other one stops and asks for `--force`. `cobble-dataflow-fixpoint-query` refuses a
restricted out-dir. The saving depends on how long records stay live. Programs that
fill a record, use it and move on shrink most; programs that copy whole records
around a loop that reaches a call keep most of them.

`--extents` is required and is the table `cobble-extents` writes: this stage
computes no extent of its own. A member's records come out of that file, and the
walk is seeded from the `VALUE` image of exactly those records, so the layout the
analysis ran against is the published one and not a second computation of it.
Reading all 29 members of CardDemo back takes under 3s in total, against 34.6s to
lay the same members' DATA DIVISIONs out again — 1.2s per member, 2.2s for the
worst.

The walk runs over the control-flow graph `cobble-srccfg-build` writes, less the
fall-throughs described next: both build it through
`srccfg/program.py:program_cfg`, which joins every CICS command that can raise a
condition to the `HANDLE CONDITION` paragraphs armed where it runs. A paragraph
reached only through such a handler is walked like any other, so its writes appear
in every output.

**A performed paragraph does not fall through.** The walk keys on the node and
keeps no call stack, so it follows every edge out of a paragraph's end, including
the `FALLTHRU` into the next paragraph. A paragraph entered only by `PERFORM` never
takes that edge: it returns. Followed anyway, it let a write that every performer
makes before `PERFORM X` fail to dominate `X`, and on CardDemo it gave seven
return-to-previous-screen `XCTL`s their own program as a candidate. So before
walking, `fixpoint/fallthrough.py` drops a paragraph end's (or a section end's)
`FALLTHRU` unless control can reach that end where it falls through. It is kept
when the end is reached:

- with no `PERFORM` active, from the program's entry, from each `ENTRY` statement
  and from each paragraph a CICS `HANDLE ABEND LABEL` names, stepping over each
  `PERFORM` to where it resumes and following every other edge but `RETURN`;
- inside a `PERFORM` range that does not end there: a `THRU` range running through
  it, a `GO TO` into it from another performed paragraph, or a paragraph inside a
  performed `SECTION`, whose range ends at the section's end;
- in the overlap of two `PERFORM` ranges that overlap without nesting.

A program keeps every edge when it has any of these: a `GO TO` (including a
`GO TO DEPENDING` branch and a `WHENEVER … GO TO`) or a `PERFORM` whose target is
not a declared paragraph or section; a `PERFORM … THRU` whose end is undeclared or
declared before its start, which the graph narrows to the start alone; an `ALTER`;
or a `HANDLE CONDITION` or `HANDLE ABEND LABEL` naming a paragraph that does not
exist. Control the graph does not show at all is not detected: `DECLARATIVES`
are absent from it, and an unqualified name declared in two sections resolves to
its first. An activation always returns at its own range end, even when an
enclosing `PERFORM` shares that end; that holds for IBM's and GnuCOBOL's return
handling, and the standard forbids two active `PERFORM`s sharing an end. Only the fixpoint's copy is pruned: `cobble-srccfg-build`, the srccfg queries and
`cobble-fields-trace` see the graph unchanged.

**A write kills what it overwrites, and only that.** An exact write drops every
entry it fully covers, in both the provenance and the value map. An exact write
into part of an exact entry splits that entry: the bytes left untouched keep its
writers, values (sliced to them) and reasons, and the overwritten bytes hold only
the new write. So `MOVE WS-PGMNAME TO CDEMO-FROM-PROGRAM` after a whole-record copy
of the commarea leaves `CDEMO-FROM-PROGRAM` with one writer and no
`inbound-linkage`, while its untouched neighbours keep both. A read straddling two
pieces finds no value. Where either side is CLAMPED (a computed subscript), nothing
is split: the entry keeps its writers whole and loses its values to `not-a-literal`.
A join rewrites one field's exact pieces into a canonical form, merging adjacent
pieces with the same writers, so paths that split a record differently settle on
the same keys. `tests/dataflow/fixpoint/test_fixpoint_cost_synthetic.py` records the
fixpoint's cost on three invented programs before the split, with it, with an
atom-cut variant, reverted and coalesced, and fails when the current cost moves.

**Statements with no transfer of their own.** The transfer models `MOVE`,
`INITIALIZE`, arithmetic, `COMPUTE`, `STRING`, `READ`, `CALL` and `EXEC CICS`. Any
other statement that writes storage — `ACCEPT`, `UNSTRING`, `INSPECT`, `SET`,
`SEARCH`, the `CORRESPONDING` forms, `WRITE`/`REWRITE … FROM`, `XML GENERATE` — is
read as a *weak* write of the names its CFG node lists: it becomes a definer of its
targets and kills nothing, its reads become the flow's sources (or, with none, a
source named after the verb), and every value it may have changed gains the reason
`unmodelled`. A level-88 name written by `SET … TO TRUE` stands for its parent. The
summary counts these writes as `unmodelled`; they are part of `writes` and
`covered` like any other, and the statement still counts as `unhandled`.

`EXEC SQL … INTO` and `FETCH … INTO` are not covered: the SQL is opaque text and
nothing names its host variables as writes yet, so those writes are still lost.

`cobble-extents` lays members out in parallel worker processes — `--max-workers`,
default 4 — and writes them in member order, so the table is byte for byte the one a
single worker writes. It logs each member's row count and time as it is written.

The table is **streamed**, one member at a time, and each member's records are
dropped before the next member's arrive, so the peak memory is the largest member's
layout rather than the corpus's — 29 members' cells held at once are 1.5GB of
Python objects, and this is meant for corpora ten times longer. The cost is the
order: members are analysed in the order the table holds them, which for `--all` is
the sorted order they were already in, and for `--member PROGA PROGB` is no longer
the order they were named in. Which members are analysed is unchanged.

Members are analysed in parallel worker processes — `--max-workers`, default 4. The
parent streams the table and hands each worker one member's rows, never the built
layout, keeping at most `--max-workers` members in flight: the peak memory is
that many members' layouts, and the table is still read only that far ahead. A
member is submitted as soon as any worker finishes, not the oldest one, so one slow
member never holds the other workers idle behind it. Members are reported as they
finish -- `[n/N]` counts finished members -- while the corpus files and the summary
are built in table order, so they are byte for byte what one worker writes. The
walk's own progress lines come from the workers and interleave; each names its
program.

The run is **resumable**. Each finished member is a directory of its own,
`<out_dir>/members/<MEMBER>/` — its five tables and a `counts.json` holding what it
adds to the run's report — renamed into place when the member is done, so a
directory that exists is a member that finished, skipped members included. A
re-run reuses those members (`[n/N] MEMBER reused`) and analyses only the rest. The
five corpus files are rebuilt from the selected members' directories, in table
order and through the same deduping writers, only once every member is done: an
interrupted run leaves the previous corpus files as they were, and a resumed run
publishes exactly the files and summary an uninterrupted one does. A `--member`
run publishes only its members and leaves every other directory alone. Nothing
checks whether a member directory came from a different `--sweeps`, ASG cache or
extents table; `--force` discards every member directory and analyses again.

A member the table does not hold is a recorded skip naming the command that fixes
it — never a crash, never silence — reported after the members it does hold. An
absent table is exit 2 before the first member. The table is read, never
republished: queries take the same file as their own `--extents`.

Exactly one of `--member` and `--all` is required; both together, or neither, is
a usage error. The usual question is about the fields of one program, and a
whole-cache pass still costs real time — tens of seconds for a large member,
a couple of seconds for a typical one, not the minutes per member this once
claimed — so it is asked for rather than defaulted into. Seeding the walk from
the `VALUE` image roughly doubles the cost on large members, because the entry
state then holds an entry per valued extent and those propagate through every
join. Per-member seconds vary by machine, so none are restated here;
`tests/dataflow/fields/test_fields_acceptance.py`'s performance bound (90s, for
the corpus's largest member) and the measurement it was calibrated against both
live in `config/carddemo-fields-tests.toml`.

Reads the ASG cache `cobble-parse-corpus` wrote and the extents table
`cobble-extents` wrote over it — no JVM, no corpus tree — and writes four files to
`<out_dir>`:

| file | one row per | holds |
| ---- | ----------- | ----- |
| `graph.jsonl` | `FIELD` endpoint, and `(node, source extent, target extent)` | node rows: nothing but the id — every attribute it once carried now has a table; edge rows: the `FLOWS_TO` relation and `node`, the statement that moved the bytes. Each row's `type` says which |
| `defs.jsonl` | `(program, node, source extent)` | the statements whose writes reach that read (`definers`; empty when no statement wrote those bytes, so their content is a `VALUE` clause or nothing), the byte values the read can see (`values`, untrimmed) and why they may be short (`reasons`, as in `targets.jsonl`); the program is part of its identity because node ids and extents repeat across programs. Only reads that feed a write have a row, and only quoted literals become values — a numeric field carries reasons, not values |
| `aliases.jsonl` | (`LINK`/`XCTL`/`CALL` site, caller window) | the commarea window the caller and callee both address — for a `CALL`, one window per `USING` argument, shared with the callee parameter at that position in its `PROCEDURE DIVISION USING` — or the reason they share none |
| `targets.jsonl` | dynamic `CALL`/`XCTL`/`LINK` site | the settled byte state read at that site: `caller`, `transfer`, the operand `expression`, the `candidates` it resolved to, any `reasons` the candidates carry doubt, and the `dropped` values that resolved but name no program |

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

The table `cobble-extents` writes — the `--extents` input — is one row per name against the ranges it owns —
`{"id": "PROGA.WS-B", "level": 5, "usage": "DISPLAY", "extents":
["WS-B@working_storage[4:8]"], "program": "PROGA", "names": ["WS-B"], "starts": [4],
...}`. Those first four fields are the whole of what the queries read, and they
have not moved; after them come arrays **parallel to `extents`**, one entry per
occurrence, carrying everything that occurrence was declared with — its record,
qualification path, start, length, level, PIC, usage, REDEFINES, OCCURS,
subscripts, declaration number, ordinal, parent, `VALUE` — plus its record's
origin, size and place in declaration order. That is `layout`'s whole answer, which
is why `cobble-dataflow-fixpoint` reads its records here instead of recomputing
them, and `cobble.dataflow.fields.extents_input` is the reader that rebuilds them.
Columns rather than an object per occurrence because a 29-member corpus declares
569226 of them, and an object apiece would spell all nineteen field names once per
occurrence: 113MB of table as columns, several times that as objects.

Its own file because where a field *is* is true
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
stopped it *and* naming the callee it
stopped on, so a consumer learns whose cache file to look at without going back to
the ASG. Some of those reasons state a fact about the two programs — no bytes are
shared, and none would be at run time either — while the rest state a limit of this
analysis: sharing very likely happens and we could not say which bytes. All twelve,
labelled, because the row carries the bare string and a consumer has no way to
discover the partition (`b7k` is the machine-readable field this is standing in for):

| reason | | what it says |
| --- | --- | --- |
| `no-commarea-operand` | fact | the call passes no `COMMAREA` at all, so nothing is shared |
| `callee-declares-no-commarea` | fact | the callee has no `DFHCOMMAREA` in `LINKAGE`, so it addresses none of it |
| `empty-window` | fact | the shorter of the two areas is zero bytes long |
| `dynamic-target` | limit | the target is a field: nothing short of running the program resolves it |
| `callee-not-in-cache` | limit | the target resolved to a name the ASG cache has no file for |
| `caller-field-unknown` | limit | the `COMMAREA` operand named nothing this member's layout holds |
| `argument-is-not-a-field` | fact | a `CALL … USING` argument is a literal or `OMITTED`, so no caller storage is passed |
| `callee-declares-no-parameter-there` | fact | the callee's `PROCEDURE DIVISION USING` lists no parameter at that argument's position |
| `parameter-not-in-linkage` | limit | the callee's `USING` names a parameter its `LINKAGE` layout lacks — usually a missing copybook |
| `unreadable` | limit | the callee's cache file would not parse (the row carries the error) |
| `unsizeable` | limit | the callee's `LINKAGE` layout never built |
| `alias-phase-failed` | limit | the phase failed on this member before reaching any site |

`callee` is
blank where the target is a field rather than a literal, which means "nothing short
of running the program resolves this" rather than "the pass did not carry it". The
one exception is `alias-phase-failed` — the alias phase giving up on a member before
it reached any site at all, so there is no target and no `node` to name. That is a
bug in this repo rather than in the corpus, and it costs that member its alias rows
and nothing else. There is no finer wall per site: filing our own defects as
artefact rows would hide them.

The JSON summary states `aliased` — distinct *sites*, not rows — against the
`alias_dead_ends` breakdown, so the table's coverage is read off the run. The two
are not a partition of the site count: one of a twice-declared name's two cells can
share a window while the other is zero-length and can never be crossed, which puts
that one site in both buckets, so the two can exceed the site total. A member whose
walk stopped at its budget contributes its rows like any other: they need the
caller's layout, which is built before the walk starts. Two members contribute
none — one whose own cache file will not parse, which is reported as a skip
instead, and one whose layout never built, which is the unsizeable-field skip and
is not reachable today. The table costs a full parse of every distinct callee's
cache file, once per run, to lay out its `LINKAGE` alone.

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
CFG node before the walk stops with `dequeue cap N reached`. A member stopped there
is published **unsettled**, exactly as a sweep budget's is (below): its flows so far
are a subset of the program's, warned about by name and counted as `unsettled` in
the JSON summary, and its dynamic call targets carry `incomplete-walk`. No constant
is right for every program. The bound is nodes × the lattice height at each node,
height is the distinct sources held at each extent, so a large member can need a
factor in the hundreds. The heartbeat carries an estimate from the queue's drain
rate; when it reads `past the N cap`, waiting buys nothing and the factor is what
to raise. Once `nodes reached` stops climbing, the remaining dequeues are
refining provenance rather than discovering the program.

`--sweeps N` runs the cheaper walk instead: at most N passes in reverse
postorder, stopping early on a pass that changes nothing. Reverse postorder is
what makes it cheap — every predecessor a node is reached through, back edges
aside, is already processed, so one pass carries a forward chain of any length.
The worklist also visits in reverse-postorder priority, but keeps revisiting
until nothing grows; a sweep budget stops after N passes. A member reported as **settled in k sweeps** is exactly as
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
| 2 | ASG directory not found, extents table not found, or a `--member` the cache does not hold |
| 3 | one or more members skipped, unreadable, or colliding on program_id |

A named member absent from the cache ends the run before it starts: analysing
the rest would report coverage over a member set nobody asked for and exit 0
while the program in question went unexamined.

**The graph is intra-program.** A `CALL` or `LINK` contributes a synthetic
`%CALL:<target>` source and no callee summary; `aliases.jsonl` is the fourth table
in the query join, stating which bytes that site shares with its callee, but it is
not an edge — naming several members analyses each independently, so no edge
crosses a program. A non-empty program_id
two members declare is exit 3 rather than a rename, since one shared `graph.jsonl`
has no filename to qualify — both members' field ids would silently merge into one
namespace. Two members that declare *no* program_id are not reported at all: the
collision check skips a blank name, so their ids merge under one empty prefix and
nothing in the run says exit 3.

`tests/dataflow/fields/` covers the byte-extent algebra (`may_alias`
over-approximates, `must_cover` under-approximates), the extent wire form and its
round trip, the per-statement transfer functions, the node-keyed fixpoint,
extent-to-name resolution, what each of the four files carries, the query
surface's five primitives, and the corpus pass's exit codes.

### Resolving a dynamic call target

A `CALL WS-PROG` or `EXEC CICS XCTL PROGRAM(CDEMO-TO-PROGRAM)` names its target
through a data item, not a literal. A field's declared `VALUE` clause becomes
bytes in an initial image, the fixpoint walk starts from it, and transfer
functions carry literals forward through moves and redefinitions.
`targets.jsonl` (above) is a second pass that reads the settled byte state at
each such site, producing one row per site: the candidates it reached, and a
typed `reasons` entry for each source of remaining doubt (`from-callee`: the
walk models a callee's `LINK`/`XCTL` write-back even though the callee may never
return control to update it; `inbound-linkage`: the read landed in the LINKAGE
region, whose writer is a caller an intra-program walk never sees;
`uninitialised`: a branch reaches the site with no write recorded on that byte
range at all).

Two things the pass does **not** do. It does not check a candidate against the
corpus's program names: `targets.py:_is_program_name` rejects only a value that
could not name anything at all — blank or unprintable — and a `PROGRAM` node is
minted for whatever survives, with the rest reported in `dropped`. That every
candidate on this corpus is a real member is a property of the data, not a guard.
And it carries nothing forward out of a write whose content it cannot name: an
`EXEC CICS RECEIVE` target, a file read and a callee write-back each contribute
their reason and no value, so a name that only such a write could have supplied
stays unresolved.

`cobble-build --dynamic-call-targets <file>` reads that `targets.jsonl` and turns
each row into one of three edge forms, by a three-way rule. `cobble-dataflow-combine`
writes rows of the same shape, plus an `outside` column the build ignores, with
targets resolved across programs; pass its file to build from those. Without the flag the
build adds no dynamic-target edges; a named file that does not exist stops the
build before it starts.

| candidates | reasons | edge(s) |
| ---------- | ------- | ------- |
| exactly one | none | one ordinary `CALL`/`XCTL`/`LINK` edge, straight to the resolved `PROGRAM` — proven |
| one or more | any | one `*_CANDIDATE` edge per candidate (`CALL_CANDIDATE`/`XCTL_CANDIDATE`/`LINK_CANDIDATE`) — resolved but carrying doubt |
| none | — | one edge to a `DYNAMIC_TARGET` node, carrying the reasons (or the dropped values) that explain why nothing survived |

A `DYNAMIC_TARGET` node's id is `<program>.<expression>` — scoped to the
program that names it, like a `FIELD` id, never a corpus-wide node keyed on the
expression text alone. `CDEMO-TO-PROGRAM` is written by more than one caller
with a different candidate set each time; a single node per expression name
would fuse every member naming it into one hub that means nothing, the same
defect this unit removed when a fallback-to-operand-text read fabricated
`PROGRAM` nodes named after variables.

On the CardDemo corpus, most resolved sites are `*_CANDIDATE`, not proven: of
24 dynamic call sites, 12 resolve to exactly one program and 12 to several, and
6 of the 12 singletons carry no doubt. 11 of the 24 carry `inbound-linkage`,
which linking (below) answers from the callers. One also carries `from-callee`,
because `cobble/dataflow/fields/transfer.py` models an
`EXEC CICS XCTL`'s COMMAREA the same way as `LINK`'s — a callee write-back —
even though `XCTL` does not return control to the site that issued it. The CFG
already says so: after an `XCTL` or `RETURN`, only the failure path continues —
to the armed handler, or under `RESP`/`NOHANDLE` to the next statement — and
`ABEND` ends the path outright. But the write-back still rides that failure
path, where the callee never ran. Dropping it is a follow-up, not done here: it
is also an exact write that kills older values, so removing it alone widens
candidate sets; a reader comparing 42 `XCTL_CANDIDATE` edges against 6
proven `XCTL` edges should read this as "resolved, mostly with acknowledged
doubt," not "only 6 sites resolved."

Every row this corpus produces is a `CICS_XCTL`. It contains no dynamic COBOL
`CALL` — every `CALL` in it names a literal — and no `EXEC CICS LINK` in any
member the build can read, the one CSD-defined program without source being
skipped. So on this corpus the `CALL` and `LINK` arms of the three-way rule go
unexercised; `CALL` is pinned instead by a bridge-compiled program in
`tests/dataflow/fixpoint/test_call_shapes_synthetic.py`, and `LINK` by unit tests
only.

#### Which call sites are detected

A site gets a `targets.jsonl` row when its transfer is `CALL`, `EXEC CICS XCTL` or
`EXEC CICS LINK` and its program operand is a data item. A literal target —
`CALL 'PROGB'`, `XCTL PROGRAM('PROGB')` — is an ordinary edge and gets no row.

| Form | Resolved through |
| ---- | ---------------- |
| `CALL WS-PGM` | the bytes of `WS-PGM` |
| `CALL WS-PGM OF WS-REC` | the qualified field's bytes, not a same-named field elsewhere |
| `CALL WS-LONG(9:8)` | exactly the reference-modified bytes, so two windows of one field resolve separately |
| `CALL WS-PGMS(I)` | every occurrence the subscript can reach |
| `… USING [BY REFERENCE / BY CONTENT] …`, `RETURNING`, `ON EXCEPTION` | as the bare form; the phrases do not change the target |
| `XCTL` / `LINK PROGRAM(WS-PGM)` | as `CALL WS-PGM` |

The bytes are whatever reaches the site: a `VALUE` clause, any `MOVE` into the
field or a group or redefinition over it, joined across branches. A branch that
sets no value still counts: a field one branch moves a literal into and another
computes or leaves unset reads back as that literal with the other branch's
reason, a candidate rather than a proven target. A value is trimmed of trailing
spaces before it becomes a candidate.

A `reasons` entry says why the candidates may be short:

| Reason | Raised when |
| ------ | ----------- |
| `uninitialised` | some path reaches the site with no write to those bytes and no `VALUE` |
| `not-a-literal` | a write whose content the walk cannot name, such as CICS state it does not model |
| `from-file` | the bytes came from a `READ` or a CICS file verb |
| `from-callee` | the bytes are a `LINK`/`XCTL` COMMAREA a callee may have written back |
| `inbound-linkage` | the bytes are in the LINKAGE SECTION, written by a caller this walk never sees |
| `no-extent` | the operand has no byte range to read, so nothing could be looked up |
| `over-budget` | more than 32 values reached it; the first 32 in sorted order are kept |
| `incomplete-walk` | the fixpoint stopped at its cap before settling |
| `unmodelled` | a statement the transfer has no handler for may have written the bytes — `ACCEPT`, `UNSTRING`, `SET … TO TRUE` and the rest; the old value stays possible |

Two limits sit upstream of the walk:

- **The ASG must come from a current bridge.** Since red-dragon `76d98d2e`
  (2026-09-20) the bridge writes a data-item callee as
  `"program_ref": {"name": …}` and a literal as a bare `"program"` string. A cache
  parsed before that writes both as `"program"`, which reads as a literal: every
  dynamic `CALL` in it silently becomes a static edge to a `PROGRAM` named after
  the variable, with no row. Re-parse such a cache into a fresh directory, since
  `cobble-parse-corpus` skips members it already has, with a JAR rebuilt by
  `make jar-force`.
- **Nested programs are not in the ASG.** The bridge serialises only the outer
  program, so a `CALL` inside a nested `PROGRAM-ID` is not seen, nor is anything
  else in it.

### Linking programs

```bash
uv run cobble-dataflow-combine --config corpus.toml --fixpoint-dir out-fields --out-dir out-linked --all
uv run cobble-dataflow-combine --config corpus.toml --fixpoint-dir out-fields --out-dir out-linked --member PROGA PROGB
```

`cobble-dataflow-fixpoint` settles each program alone, so a target read from the
commarea is only ever `inbound-linkage`. This command reads that output (every
`members/<program>/` table, whose ENTRY rows give each linked callee's received area),
the corpus TOML's `asg_dir` only for a callee outside the linked set, each one read once
per run, and its `csd_files` for transaction-to-program names, and lets values cross
programs. A missing corpus config, fixpoint `members/` directory or parse cache refuses
the run with exit 2, writing nothing.
It links in rounds: a target found only after values arrive adds edges, which can
deliver more values, until the edges stop growing.

A `XCTL`, `LINK` or `CALL` link to a callee exists because the target field could name
that callee, so when the field lies inside the bytes handed over, those bytes on that link
hold exactly the callee's name, space-padded. Bytes wholly inside the field resolve to
that name; bytes that straddle it are walked as before.

A target with a computed subscript, `PROGRAM(WS-PGMS(I))`, names no single occurrence. Its
jump row carries no extent, so linking keeps the fixpoint's own candidates and reasons for
it rather than walking one occurrence's bytes, and no link pins any occurrence to a name.

`--all` links every program with results. `--member` links only those named
(case-insensitive, each once) and refuses the run, writing nothing, when one has no
results. Under `--member`, programs left out are read for the jumps they make into the
linked set: a target a linked program may be reached from by one of them lists it in
`outside`, and the run report counts what it cannot say.

| File | Row | Holds |
|---|---|---|
| `targets.jsonl` | dynamic site | the fixpoint's `targets.jsonl` row after linking (`candidates`, `reasons`, `dropped`), plus `outside`: the programs outside the linked set known to jump into the caller |
| `links.jsonl` | one link used | `caller`, `node`, `transfer`, `callee`, the bytes lined up on each side (`caller_extent`, `callee_extent`), `returns` (a `LINK` or `CALL`), and `discovered` (the link exists only because linking resolved its target) |

The run report goes to stderr: rounds, discovered links, outside jumps whose targets
could not be resolved, and outside programs with no results at all.

### Querying the field dataflow

```bash
uv run cobble-dataflow-fixpoint-query writers    WS-TOTAL --fixpoint-dir out-fields --extents out-fields/extents-input.jsonl
uv run cobble-dataflow-fixpoint-query readers    PROGA.WS-TOTAL --fixpoint-dir out-fields --extents out-fields/extents-input.jsonl
uv run cobble-dataflow-fixpoint-query reaches    WS-TOTAL --fixpoint-dir out-fields --extents out-fields/extents-input.jsonl --depth 4
uv run cobble-dataflow-fixpoint-query contains   SOME-REC --fixpoint-dir out-fields --extents out-fields/extents-input.jsonl
uv run cobble-dataflow-fixpoint-query reaches    PROGA.WS-KEY --fixpoint-dir out-fields --extents out-fields/extents-input.jsonl --across-calls --max-hops 2
uv run cobble-dataflow-fixpoint-query reaches    PROGA.WS-KEY --fixpoint-dir out-fields --extents out-fields/extents-input.jsonl --across-calls --links out-combined/links.jsonl
```

Joins the graph, defs and aliases tables with the `--extents` table and answers in bytes. The
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
nobody asked about.

`reaches` and `reached-by` follow values in statement order, to `--depth`
(default 6). Each step goes from one statement's move to the next move that can
actually see its result: forward, to a read the write reaches; backward, to a
write the read can see — the fixpoint's `defs.jsonl` says which. So in

```cobol
MOVE WS-B TO WS-C      *> runs first
MOVE WS-A TO WS-B
```

`reaches WS-A` is `WS-B` alone: the copy of `WS-B` into `WS-C` ran before
`WS-A` was moved in. A literal or a file read ends a chain without being a
landing. `--across-calls` (below) still walks field to field, regardless of
statement order.

#### Crossing a call: `--across-calls`

`reaches` and `reached-by` take `--across-calls`, which lets the walk step through
a `COMMAREA` window into the callee, and `--max-hops N` (default 3) bounds how many
such steps one route may take. Off by default, because the call graph reaches most
of itself within a few hops, so an unbounded provenance answer names half the system
and tells a reader nothing. Refused rather than ignored on the other six questions,
which this analysis does not answer across a call.

The crossings come from the fixpoint's `aliases.jsonl`, which cannot cross a site
whose target it could not resolve. `--links <links.jsonl>` reads
`cobble-dataflow-combine`'s links instead: the same rows plus the ones linking
discovered, so the walk also crosses into callees the combine resolved.

A hop is not an edge: the two windows are the same storage, so a crossing is a byte
identity rebased to the other side's offsets. `LINK` returns, so its window is
symmetric and the callee's write-back comes home; `XCTL` does not, so it is inbound
only. A `CALL` crosses per argument, into the parameter at the same position in the
callee's `PROCEDURE DIVISION USING`: `BY REFERENCE` is shared storage and comes home
as `LINK` does, while `BY CONTENT` and `BY VALUE` hand over a copy and are inbound
only. Each landing prints the bytes it landed on, its `hops` — the cheapest route
the walk found within the depth budget — and `via`, the last site that route
crossed. Landings are the whole answer: the walk reports what it reached and says
nothing about why it ended, so a short answer does not distinguish "nothing flows
here" from "the analysis stopped here". Where the analysis gave up is a build-time
fact instead — `aliases.jsonl`'s dead-end rows and the run summary's
`alias_dead_ends` breakdown name every site that could not be resolved. A
query-time verdict naming the hop limit, the depth limit, each dead-end site met
and each pruned arrival was built and then deliberately removed: it cost more to
read than the distinction was worth.

Three limits follow from that, all of them open beads:

- **Overlap pruning drops a covering write-back** (`nsv`). A callee that repacks the
  whole record it read — `MOVE CALLEE-REC TO DFHCOMMAREA` — lands on bytes the
  inbound hop already stood on, and the walk drops it silently, losing the return
  direction. A lost answer, not a fact about the two programs.
- **`hops` is minimal only within `--depth`** (`u3v`). A cheaper route needing more
  flow steps than the depth budget allows is never found, so the cost reported is
  the cheapest of the routes seen.
- **An external origin reads like an absence** (`bm7`). A range whose only writer is
  a `READ INTO` from a file reads the same as a range nothing writes at all: the
  synthetic `FILE:`/literal/`%CALL:` source the walk ended on is never named.

Field names go to stdout and nowhere else, so the log stays safe to tail. The extents table is streamed, not loaded: a question needs only the programs that declare its subject — `PROGRAM.FIELD` keeps that program, a bare name every program declaring it — so memory stays near one program's declarations however large the table is, though the whole file is still read once per question. A `PROGRAM.FIELD` that program does not declare is reported as no such field. The log, on stderr, says what the command is doing: the scan of the extents table, with its size first, a line every 100 programs and one for each program it keeps, then the other tables, which of the matching fields it is answering for, and the walk depth by depth.

`load()` reads a directory and `store_of()` takes the rows directly, off one
assembly — an in-process caller and a reader of the published artefact cannot
answer differently. A missing table loads as empty rather than as an error, so a
directory an older build wrote is still worth querying.

### Path sampling, across calls

`cobble-fields-trace PROGRAM --asg-dir DIR --out FILE` answers a different
question from the artefact tables. It interprets **one concrete path at a time**
over the same byte-provenance model, threads a single store with no join, and
steps into a `LINK`ed callee by binding the callee's `DFHCOMMAREA` onto the
caller's commarea window — so a write-back needs no mechanism, because the two
sides are the same storage. Because a path has a stack, it also takes only the
`RETURN` edge back to the site that actually performed the paragraph — and when a
performed paragraph has no exit the walk will admit, the stack still says where it
came from, so the path resumes at the performer instead of ending there.

The output is **JSONL, streamed to disk per path**: each path's deps are appended
immediately, so a killed run still produces a queryable file. Footer rows (dead
ends, coverage, limits) are written once at the end. The file may contain
duplicate dep rows across paths; the query tool deduplicates on load. An existing
`--out` is skipped and left untouched; `--force` traces again and overwrites it.

A callee the parse never covered is an opaque block, not an error: the site is
listed under `dead ends` with the reason the alias table gives it
(`callee-not-in-cache` for a member with no ASG file), the commarea it passed is
credited to `%CALL:<program>`, and the caller's path runs on past the call. Any
corpus selection `LINK`s outside itself, so this is the common case. A `CALL` is
stepped into with one window per `USING` argument, bound to the callee parameter at
that position: on return, only a `BY REFERENCE` argument's window is written back,
since `BY CONTENT` and `BY VALUE` handed over a copy. An argument with no window -- a
literal, a position the callee lists no parameter at -- is a dead end of its own,
and the `CALL` is still entered.

`--single-program` (off by default) keeps the trace to `PROGRAM`'s own CFG. Its
`LINK` and `XCTL` sites run as ordinary statements — the commarea is credited to
`%CALL:<program>` as above — rather than steps into the callee, so no other
program is loaded, not even to size a shared window, the default `--max-depth`
counts this program's nodes alone, and coverage is this program's branches.

A path **is** a plan: the arm index to take at each branch, in the order the
branches arise. The walk is a pure function of it, so a plan names a route
exactly — deterministic, no random seed — and the sampler enumerates plans rather
than guessing arms. After a path runs, every branch it met with an untried arm
left yields one new plan (that prefix, one arm further along); those queue up in
two lanes — **fresh** (plans whose flip takes a branch edge nothing has taken and
no other queued plan already promises) and **stale** (the rest). The fresh lane is
drained first, so every path raises coverage; once it empties the run stops,
because the remaining stale plans flip already-taken edges and cannot reach any
new branch.

Past its own end a plan keeps taking the first arm, so which arm is first decides
how far every route gets: arms whose target goes nowhere are ordered last. The CFG
gives every CICS command with no `NOHANDLE` and no `RESP` a raising arm that is
such a dead stop, because naming the armed handler is a reaching-definitions
question the lowering declines to answer, and leaving that arm first would end
every route at the first such command past its last flip.

Progress goes to stderr, one line per sampled path carrying the nodes it ran, the
cumulative branch coverage, the fresh and stale queue sizes, the programs entered
and the dead ends met, then a closing line naming why the run stopped: the
coverage target met, the path budget spent, the fresh queue exhausted, or
`nothing unexplored is reachable` — the queue is empty, so every route the walk
admits has been walked exactly once.

It under-approximates, deliberately: a flow it does not report was not sampled,
never "does not exist", and a loop body runs once. `--paths` and `--coverage`
bound the sampling and the branch-coverage figure is printed with the answer, as
are those limits. The fixpoint behind `cobble-dataflow-fixpoint` keeps the other guarantee —
over-approximate, every real flow present — and neither replaces the other.

### Querying provenance from a trace

```bash
uv run cobble-trace-query forward  DFHCOMMAREA  --trace /tmp/trace.jsonl
uv run cobble-trace-query backward WS-TOTAL     --trace /tmp/trace.jsonl
uv run cobble-trace-query forward  DFHCOMMAREA  --trace /tmp/trace.jsonl --depth 3
```

`cobble-trace-query` walks forward (what does a field affect?) or backward (what
feeds it?) over a JSONL trace by **byte-extent containment**. The subject is a
field name, or `PROGRAM.FIELD` to qualify it; `--depth` (default 5) bounds the
number of hops.

The backward walk **narrows the frontier** at each hop: when a dep's target is a
group wider than the range being traced, the source is clipped to the
corresponding sub-range via offset arithmetic. A 3-byte field inside a 1000-byte
commarea follows only the 3 bytes that feed it, not all 1000. It is the overlap
of the two that is clipped, and every overlapping frontier range yields its own
slice — the frontier is a set, so narrowing to the first of them would make the
answer depend on the order it came out in.

Extents are compared within a program, so a dep row carries `source_program`
beside `source`: at a `LINK` return the caller is credited with bytes still named
in the callee's address space, and collapsing the two onto the row's one
`program` would both hide the callee's own writes and let the caller's bytes at
those offsets stand in for them. It is absent on rows with an `origin`, which
have no source to address, and defaults to `program` when a trace predates it.

Output is an indented tree, one line per provenance edge, with terminal origins
(`FILE:`, `LITERAL`, `%CALL:`) at the leaves. The file may be a partial (killed)
trace with no footer — the query tool reads whatever dep rows are present.

### Render the HTML visualization

```bash
uv run cobble-render --graph out/carddemo.jsonl   # reads the graph file -> writes out/carddemo.html
```

`--graph` is the file `cobble-build --output` wrote; no config is read. The page is
written beside it and named for its stem, and `cobble-render-webgl` writes
`<stem>-webgl.html` the same way. `out/carddemo.html` is a single
self-contained file (vis-network is vendored at
`cobble/knowledge_graph/vendor/vis-network.min.js` and inlined; no server,
no CDN, no network access needed). Open it directly in a browser. It has
checkboxes to filter by node/edge kind, a search box that highlights matching
node labels, and click-to-highlight-neighbors on any node. A missing `--graph` file
exits 1 and names `cobble-build --output`.

### Unit tests

```bash
uv run python -m pytest   # no JARs, no corpus
```

Unlike `cobble-build` + `cobble-compare` (one big end-to-end golden-file check over
the real CardDemo corpus, needing the forge-built tools), `tests/` unit-tests cobble's pure
modules in isolation (grammars, dataclass transforms, graph merging) with
hand-built inputs, giving localized signal on which piece broke rather than
just "448/836 doesn't match." Coverage is still partial; see `tests/` for
what's covered so far.

### Formatting, linting, and pre-commit hooks

```bash
uv run python -m black cobble tests
uv run lint-imports && uv run pyright && uv run python -m python_fp_lint check cobble/
```

`.pre-commit-config.yaml` wires these up (plus the terminology guard and
the unit tests) to run automatically on every commit: `black` auto-formats and
re-stages, `pyright` and `python-fp-lint` report warnings without blocking
the commit, and `import-linter` / the unit tests block it on failure.
Architecture contracts live in `.importlinter` (e.g. `interpreter` may not
import `cics`/`jackal`/`knowledge_graph`/`bms_copybook_gen`, and those four
consumers may not import each other).

## What's here

| Path | What |
|------|------|
| `cobble/` | The ported extraction code, plus this repo's own driver scripts (see below); everything lives under one package so there's no Python at the repo root. Extraction modules are byte-for-byte / import-rewired from their `red-dragon-forge` counterpart (imports → `cobble.*`), with the two documented exceptions below (`cics/verb_source_asg.py`, `cics/flow_map.py`). Imports **no** production Python: only `cobble.*`, stdlib (configs are TOML, read with `tomllib`), and pip (`lark`, `networkx`, `antlr4-python3-runtime`). Includes `cobble/bms_copybook_gen/` (the copybook generator, run as `python -m cobble.bms_copybook_gen`). |
| `cobble/cics/verb_source_asg.py` | **The one seam.** Production sources CICS verbs by *lowering* each program through the CICS strategy (which needs the VM). This replaces that with a VM-free walk of the typed `CobolASG`: it reads each `EXEC CICS` statement, resolves operands to their static `VALUE` clauses, and routes the `CicsVerb`s through the byte-for-byte `flow_graph_core._verb_edge`. |
| `cobble/cics/flow_map.py` | Ported, and the one other module that diverges — in how the pass *reports*, not in what it emits. It returns what it read and what it could not (production reports into a list the caller hands down), and it says where it is: a bar over its per-program loop, which is where a corpus run spends its time, and each member's name at DEBUG before it is read. Every node and edge, and the order they reach the sink, are unchanged. |
| `cobble/build_graph.py` / `cobble/compare.py` | This repo's own driver scripts (not ported from `red-dragon-forge`): extract the graph → one file (`cobble-build --config <path> --output <file>`, reading the config's `asg_dir` — needs `cobble-parse-corpus` first); identity-diff it against `reference/graph.jsonl` (`python -m cobble.compare --graph <file>`). |
| `cobble/parsing/` | **Stage-1.** The one place a corpus is turned into ASGs and the one place they are read back: `parse_corpus.py` writes one JSON ASG per member (`cobble-parse-corpus --config <path>`), `asg_cache.py` owns the naming rule and the reader every later stage calls, `config.py` is the parse's own config. `expand_corpus.py` is the same walk stopped before the grammar runs, writing expanded source instead (`cobble-expand-corpus --config <path> --out-dir <dir>`), with `expanded_cache.py` owning its naming; it reuses `parse_corpus`'s `Job`, `Result` and `bridge_jar` so the two cannot disagree about the JAR. These two stages start a JVM; nothing downstream does. |
| `cobble/corpus_config.py` | `CorpusConfig`/`BmsConfig` dataclasses + TOML loading (`tomllib`, stdlib); `cobble.build_graph`/`cobble.generate_sym` read the corpus location/layout from here instead of a hardcoded CardDemo path. `asg_dir` is an input: the cache Stage-1 wrote. |
| `config/carddemo.toml` | The corpus config CardDemo uses, read by every stage from `cobble-parse-corpus` to `cobble-build`. Copy it as a starting point for a different corpus. |
| `cobble/corpus_index.py` / `cobble/file_location.py` | `CorpusIndex` resolves every `(NodeKind, id)` to a `FileLocation` (a real `Path`, or a `NoFileLocation` explaining why not: not file-based, no CSD/definition source, or genuinely unresolved) once per run, from the same `CorpusConfig`. Every extractor and `GraphWriter` resolve a given node identically regardless of call order, which is what lets `GraphWriter` stream nodes keep-first with no merge step. |
| `cobble/render_graph.py` | Render the graph file as a self-contained interactive HTML graph beside it, `<stem>.html` (`python -m cobble.render_graph --graph <file>`. `cobble/knowledge_graph/graph_file.py` reads the file, `merge.py` builds one `networkx.MultiDiGraph`, `render.py` inlines the vendored `vis-network.min.js`). |
| `cobble/dataflow/srccfg/` | **Source control-flow graphs.** `desugar.py`/`build.py` lower each paragraph's statements to nodes and edges — PERFORM with its resume point and range end, GO TO, EXIT PARAGRAPH / SECTION / PERFORM [CYCLE], NEXT SENTENCE (per sentence, from the ASG's sentence ends), EVALUATE with stacked WHENs chained into one body, the end-of-file, I-O error, size error, CALL exception and STRING / UNSTRING overflow arms (`arm_clauses.py`, which the statement index reads too), CICS raise arms and HANDLE CONDITION dispatch, EXEC SQL WHENEVER guards — and `program.py`'s `program_cfg` is the one way every consumer builds a program's CFG. `closure.py`/`link.py` join a program to the programs it calls; `bundle.py` and `rows/` are the JSONL file format, the only code that reads or writes it; `dataflow.py`/`query.py` answer the name-level guards and provenance questions; `dot.py`/`webgl.py` draw it. |
| `cobble/dataflow/srccfg/reach/` | `cobble-srccfg-reachability-walk`: reachability from one PERFORM over states of a node and the PERFORMs open there (`expand.py` holds the rules, `walk.py` streams the rows, `reachability_cli.py` is the entry point). `cobble-srccfg-dfs-walk` drives the identical stepper depth-first for an execution-order trace instead (`dfs.py`/`dfs_cli.py`). |
| `cobble/dataflow/layout.py` | Byte extents for every field in a program's records — the substrate the field dataflow runs on. |
| `cobble/dataflow/fields/` | **Byte-level field dataflow, the parts.** Extents and the extents table (`extent.py`, `emit_extents.py`), the per-statement transfer functions (`transfer.py`), the state each statement sees — provenance and value sets (`state.py`, `values.py`, `image.py` for `VALUE` clauses) — commarea aliasing across calls (`aliases.py`), the path-sampling trace and its queries (`trace*.py`), and field-access sites (`access*.py`). |
| `cobble/dataflow/fixpoint/` | **The fixpoint.** The solver over each program's CFG (`fixpoint.py`), the corpus run writing `graph`, `defs`, `aliases` and `targets` (`build_corpus.py`), dynamic call-target resolution (`targets.py`), and the query over its output (`query.py`). |
| `cobble/dataflow/depgraph/` | The coarse, name-level variable dependency graph, built from the ASG cache (`cobble-depgraph`). |
| `cobble/viz/` | Views over the graph file and CFGs: the program call graph, PERFORM sequence diagrams, and trace path animation, rendered by `render_cmd.py`. |
| `cobble/diagnosis/` | Read-only reports on what a corpus build will fail on, before the expensive phase: unresolved `COPY`s, unparseable COBOL and JCL. |
| `cobble/bms_metadata.py` / `cobble/bms_render.py` | BMS screen maps as structured metadata (via `hlasm_export`) and as rendered 3270 screens. |
| `tests/` | The pytest unit suite (`uv run python -m pytest`), mirroring `cobble/`'s package structure. No JARs/corpus needed; pure modules tested in isolation with hand-built inputs. |
| `cobble/generate_sym.py` | **Stage-0.** Generates the BMS symbolic copybooks: `hlasm_export <map>.bms --syslib bms-macros/ | python -m cobble.bms_copybook_gen → sym/*.cpy` (`python -m cobble.generate_sym --config <path>`). |
| `cobble/generate_csd.py` / `cobble/cics/synth_csd.py` | **Stage-0, optional.** Reconstructs a CSD a corpus arrived without, so its CICS members reach the flow stage at all → the file `--out` names (`python -m cobble.generate_csd --config <path> --out <file>`). `synth_csd.py` is the pure core: literal transaction ids in the source, placed on members by the config's `transid_rules`, everything else marked synthetic or reported — never guessed. |
| `reference/graph.jsonl` | The 448/836 identity golden, in the graph file's format: cobble's own output for CardDemo with the cross-program combine. It began as a copy of the production fitness golden (448/832) and departs from it in 7 edges: 3 candidates proven `XCTL` because the target field is moved a literal right before the jump, and 4 return-to-caller candidates the combine finds across programs (`COCRDSLC`→`COCRDLIC`, `COCRDUPC`→`COCRDLIC`, `COUSR02C`→`COUSR00C`, `COUSR03C`→`COUSR00C`). |
| `bms-macros/` | The hand-written `DFHMSD`/`DFHMDI`/`DFHMDF` prototype macros (assembler SYSLIB for `hlasm_export`). Source, not generated. |
## Invariant

`cobble/**` imports zero live production Python (no bare `interpreter` / `cics` /
`jackal` / `knowledge_graph` absolute imports; only `cobble.*`):

```bash
grep -rE '^\s*(import|from)\s+(interpreter|cics|jackal|knowledge_graph)\b' cobble
# (no output)
```

The only coupling to RedDragon is (a) the two bridge JARs and `hlasm_export`,
invoked as subprocesses, all **built from source** by forge's `make setup`, and (b) the one seam
(`cobble/cics/verb_source_asg.py`). The graph identity (448/836) is reached by
independent Python that shells out to those tools: the decoupling, proven by a
package that imports no production interpreter code and ships no generated
artifacts.

## Acknowledgments

The JCL grammar (`jackal/jcl-bridge/src/main/antlr4/org/jackal/jcl/JCLLexer.g4` /
`JCLParser.g4`) and the CICS `EXEC CICS` grammar
(`cicada/cics/cics_grammar/CICSzLexer.g4` / `CICSzParser.g4`, adapted for the
Python3 ANTLR runtime) are both vendored from **Craig Schneiderwent's
[mapa](https://github.com/cschneid-the-elder/mapa)** project; thank you for
making these available. See `jackal/jcl-bridge/PROVENANCE.md` for the exact vendored
commit/files, and `jackal/jcl-bridge/LICENSE` for mapa's MIT license text.

## License

MIT; see [LICENSE.md](LICENSE.md). Project rationale in [PHILOSOPHY.md](PHILOSOPHY.md).
The vendored `cobble/knowledge_graph/vendor/vis-network.min.js` ships under its
own license: see `cobble/knowledge_graph/vendor/VIS_NETWORK_LICENSE.md`.
The vendored mapa grammars (see Acknowledgments above) ship under their own
MIT license: see `jackal/jcl-bridge/LICENSE`.
