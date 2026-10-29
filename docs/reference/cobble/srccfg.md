# cobble: source control-flow graphs

A source CFG is one program's statements as nodes and control transfers as edges, built from
the ASG cache. `cobble-srccfg-build` writes a closure: the seed program's CFG and the CFG of
every program it reaches through calls. The other commands read that file.

The code is in `cobble/cobble/dataflow/srccfg/`. `program.py:program_cfg` is the one way a
program's CFG is built; the field dataflow uses the same function.

## cobble-srccfg-build

```
cobble-srccfg-build PROGRAM --config CONFIG [--output OUTPUT] [--dynamic-call-targets FILE]
```

| Flag | Meaning |
|---|---|
| `PROGRAM` | the seed member |
| `--config` | a srccfg config (`[srccfg]` table, see [config](config.md)), not the corpus config |
| `--output` | write the closure here; default stdout |
| `--dynamic-call-targets` | a `targets.jsonl` from the fixpoint or the combine. Each dynamic site's candidates are built like any callee, transitively. Without it, dynamic sites pull in nothing. A named file that does not exist stops the build |

Each program is looked up as `<program>.json` and built from that member's first program; a
batch or contained program after it is not reachable this way (red-dragon-forge-1yoa).

A callee missing from the ASG cache is logged as `called but not in the ASG cache; not built`
and becomes an external program (see below). Parse everything you want reachable first.

## File format

JSONL. Each row has a `type`:

| Row | Holds |
|---|---|
| `program` | opens a program's CFG. The first is the seed. `entry` is the label node of its first paragraph in source order (`""` for a program with no paragraphs; `%EXTERNAL#label` for an external one). `"external": true` marks a program the cache does not hold |
| `node` | one node of the preceding program |
| `edge` | one edge of the preceding program |
| `call` | after all programs: `caller`, `node`, `transfer`, `program` (callee), `entry` (the callee node the call lands on), `resolved`, `commarea`, `expression`, `reasons`, `certain` |

A single-program file is one `program` row and no `call` rows. A line that is not a row is
refused with its line number. `bundle.py` and `rows/` are the only code that reads or writes
the format.

An external program's CFG is the single node `%EXTERNAL#label` with no edges. Calls land on it
and the caller continues past a `CALL` or `LINK`.

For a dynamic site with candidates, the site becomes one `call` row per candidate.
`expression` names the field called through, `reasons` carries the doubt, and `certain` is
true for one candidate with no reasons. A site with no candidates is one `call` row naming the
field, with an empty `entry`.

## Graph shape

- Every paragraph and every section has a `<name>#label` entry node and a `<name>#end` exit
  node. A section's label flows into its first paragraph; its last paragraph's end flows into
  the section's end.
- `PERFORM`, `GO TO` and a `WHENEVER`'s `GO TO` land on a section's label when they name one.
- Names are upper-cased in node ids.
- A `PERFORM` that can return has no edge past it. Its node's `resume` names where it
  continues, and the range's `RETURN` edge lands there.
- Two kinds of `PERFORM` keep a `FLOW` edge to the next statement and have no `resume`: one
  whose range the program does not declare, and one whose range end nothing reaches.
- Lowered constructs: `PERFORM` with resume and range end, `GO TO`, `EXIT PARAGRAPH`/`SECTION`/
  `PERFORM [CYCLE]`, `NEXT SENTENCE`, `EVALUATE` with stacked `WHEN`s, the end-of-file, I-O
  error, size error, `CALL` exception, `STRING`/`UNSTRING` overflow and `WRITE` end-of-page arms, CICS raise arms
  and `HANDLE CONDITION` dispatch, and `EXEC SQL WHENEVER` guards.
- `EXEC CICS XCTL` and `RETURN` continue only on the failure path: to the armed handler, or
  under `RESP`/`NOHANDLE` to the next statement. `ABEND` ends the path.

## cobble-srccfg-query

```
cobble-srccfg-query {provenance,guards,coassign} SUBJECT --cfg CFG
    [--min-tier {SAME_STATEMENT,SAME_SOURCE,SAME_GUARD,SAME_PARAGRAPH}]
    [--max-depth N] [--max-paths N]
```

| Query | Subject | Answer |
|---|---|---|
| `guards` | node id | the conditions on each path reaching the node |
| `provenance` | field name | what the field's value derives from, and what it feeds, by name |
| `coassign` | field name | fields assigned together with it, at or above `--min-tier` |

`--max-depth` bounds how far `provenance` follows each direction. `--max-paths` caps the paths
enumerated for reaching conditions (default 64). The queries run per program: a field crossing
a commarea stops at the boundary. Cross-program flow is the [field dataflow](field-dataflow.md).

## cobble-srccfg-reachability-walk

```
cobble-srccfg-reachability-walk --cfg CFG --from SEED
```

Everything that can run from one `PERFORM` node (`--from`, e.g. `MAIN-PARA/0`) in the file's
first program until control returns, and every other way it ends. It walks states of a node
and the `PERFORM`s open there, visiting each state once.

| At | The walk |
|---|---|
| a `PERFORM` | opens a frame for its resume point and enters the range |
| a range end | returns from the innermost open `PERFORM` whose range ends here, else falls through |
| a `GO TO` | follows it; a `GO TO` out of a range keeps the pending return |
| a decision | follows every arm |
| a recursive `PERFORM` | is not entered (`refused`) |
| a `PERFORM` of an undeclared range | is stepped past (`unresolved`) |
| a `CALL` or `LINK` | is stepped past; other programs are not entered |

Output is JSONL on stdout as the walk goes: reached nodes and taken edges in the CFG row
format, `outcome` rows (`returns`, `stop-run`, `goback`, `exit-program`, `abend`, `xctl`,
`cics-return`, `unhandled-condition`, `dead-end`), `unresolved` and `refused` rows, and a last
`summary` row. No summary means the walk did not finish. Rows arrive by distance from the seed.
The graph does not keep the stack, so a paragraph reached from two `PERFORM`s shows both
returns.

## cobble-srccfg-dfs-walk

```
cobble-srccfg-dfs-walk --cfg CFG --from SEED [--mode {primary,tree}]
```

The same stepper (`reach/expand.py`), driven depth-first, for control-flow order.
`primary` (default) takes the first arm at every branch and notes the alternates inline.
`tree` recurses both arms of every branch.

## cobble-srccfg-dot

```
cobble-srccfg-dot --cfg CFG [--output OUTPUT]
```

Graphviz DOT, to stdout by default. A certain dynamic call draws like a literal `CALL` (dashed
orange); other candidates draw as `CALL_CANDIDATE` (dotted grey). A site with no candidates
draws nothing. Use it for one program; `dot` does not finish on a large closure.

## cobble-srccfg-webgl

```
cobble-srccfg-webgl --cfg CFG --output OUTPUT [--program PROGRAM]
```

One self-contained WebGL page. Nodes are namespaced by program and resolved calls become
cross-program edges (`joined.py`). Positions are computed with `sfdp` at build time.
`--program` draws one member of the closure.

## cobble-srccfg-subgraph

```
cobble-srccfg-subgraph --cfg CFG --program PROGRAM [--program ...] --prefix PREFIX [--prefix ...]
    [--drop-suffix SUFFIX ...] [--drop-target ID ...] [--short LONG=SHORT ...] [--balance] --out OUT
```

A hand-picked slice of a CFG, written as `<out>.dot`, `<out>.png` and `<out>.svg`.

| Flag | Meaning |
|---|---|
| `--program` | program in the file; repeat for a cross-program slice |
| `--prefix` | node-id prefix to include, separator-aware; repeatable |
| `--drop-suffix` | node-id suffix to exclude, e.g. `#dispatch`; repeatable |
| `--drop-target` | edge target id to exclude; repeatable |
| `--short` | label replacement, e.g. `VALIDATE-OPTION=VO`; repeatable |
| `--balance` | pipe through `unflatten -f -l 2 -c 5` for wide fan-outs |
| `--out` | output path stem |

Keep `#raise` nodes: each is the decision whether a CICS command raised a condition, and
dropping it cuts the no-error edge. `#dispatch` nodes are the error fan-out and can go.
