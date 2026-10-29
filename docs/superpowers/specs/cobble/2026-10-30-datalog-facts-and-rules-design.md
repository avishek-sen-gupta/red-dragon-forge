# Datalog facts and a generic rule library

**Date:** 2026-10-30. **Package:** cobble (experimental). **Size:** heavy (a new experimental
package, a command, a rule library, one CFG artifact field, a rebuild step).

## Why

An untracked experiment exported a CardDemo run as Soufflé Datalog facts and answered real
questions with rules: who sets the credit limit, which test outcomes guard its write, what a
change to it touches. It worked. The next step is a machine that decomposes a question into
claims and proves each against these facts, so the facts and the rules that are not about
CardDemo become part of cobble. A person never writes a query; the machine writes it, and if
the query is a file, the machine writes the file.

## Goal

1. `cobble-experimental-datalog-facts` reads one cobble run directory and writes Soufflé facts
   and the schema that declares them.
2. A tracked library of generic rules, which a machine-written question includes and points at
   its target by stating facts.
3. `make carddemo-all` writes the facts.

### Non-goals

- The CardDemo questions (credit limit, sign-on, menu, USRSEC) stay in the untracked experiment
  folder, rewritten on top of the library.
- The proof renderer (`proofs.py`) and the proved/refuted/unknown outcome of a claim stay
  untracked; the decomposition engine is a later design.
- No cobble command runs Soufflé. A question is run with plain `souffle`.

### Anti-goals

- Any guess in the facts. The experiment chose a program's entry as "the lowest-numbered label
  with no incoming edge"; cobble is heuristic-free, so the entry becomes a CFG fact (below).
- A relation declared in two places that can drift apart.
- Parsing text the run already holds as structure: every artifact is read through cobble's typed
  reader for it; extents through `extent_text.byte_range`.

## Decided

1. **Command (user's choice: facts plus rules).** `cobble-experimental-datalog-facts --run <run
   dir> --out <dir>`. Writes `<relation>.facts` (tab-separated, Soufflé's default) for every
   relation, and `schema.dl` declaring each with `.decl` and `.input`. Code in
   `cobble/cobble/experimental/datalog/`.
2. **One definition per relation.** Each relation is defined once in Python (name, column names,
   column types, and the rows it takes from the run); that definition writes both its facts file
   and its `schema.dl` line. The library ships no copy of the schema.
3. **Relations:** the 41 the experiment exports, from the knowledge graph, extents, CFGs,
   accesses, fixpoint (counts, defs, sinks, flows), combine links and targets, jumps, partition
   graph and its byte alignments, the name-level dependency graph and aggregate clusters. Origins
   and sinks carry their typed `kind` and `name` columns. `cfg_entry` comes from the CFG's new
   entry field, not from a guess. Columns keep the experiment's encoding, because its rules
   depend on it (my call): `symbol` for text and `number` for offsets, lengths and counts, `yes`
   / `no` for booleans, `-` for an absent PERFORM resume or range end, tabs and newlines in text
   replaced by spaces, rows de-duplicated. An extent splits into name, region, start and end
   through `extent_text.byte_range`, whose `ByteRange` carries all four.
4a. **Typed readers.** Every artifact is read through a Pydantic model. Where none exists
   (expected: extents, knowledge graph, accesses, partition graph alignments, depgraph edges,
   fixpoint aliases), the new model sits beside the code that writes that artifact, so writer
   and reader share it (my call).
4b. **A missing artifact** (a run built without some stage) fails the command with an error
   naming the file; it never writes an empty relation (my call).
4. **CFG entry.** The CFG program row gains `entry`: the label node of the first paragraph in
   source order (`paragraph_order(asg)[0]`), which the builder already computes; an external
   program's is its one node, `%EXTERNAL#label`. On CardDemo this equals the experiment's guess
   for all 31 programs with source and all 7 external ones, so no result moves. The field is
   required (no default): a CFG written before it is rebuilt, as with the typed-origins change,
   and reading one fails validation (my call). `docs/reference/cobble/srccfg.md` documents it.
5. **Library** in `cobble/cobble/experimental/datalog/rules/`, shipped with the package. Each file
   `#include "schema.dl"`, resolved with `souffle --include-dir <facts dir>`.

   | file | derives | the question states |
   |---|---|---|
   | `reach.dl` | valid-path reachability: a PERFORM returns to its caller, no fall-through out of a performed range, RETURN edges never followed; `reach`, `branch` | nothing |
   | `guards.dl` | the test outcomes every valid path to a site takes (`guard`) | `site(program, node)` |
   | `programs.dl` | which programs a transaction can run (`runs`, `hands_to`) | nothing |
   | `bytes.dl` | the byte-precise walk forwards and backwards from some bytes through the partition graph; an unaligned edge means the whole field | `target_bytes(slot, start, end)` |
   | `writers.dl` | every writer of a slot, split into setters (new bytes from a file, screen or literal) and write-backs | `target_slot(slot)` |
   | `guard_reads.dl` | the fields a guard's test reads | builds on `guards.dl` |
   | `gaps.dl` | why an answer about a program may be incomplete: not settled, dead ends, unresolved guards, unmodelled writes | builds on `site` |

   A question is a `.dl` file the machine writes: `#include` lines, the facts above, `.output`
   lines.
6. **Soufflé is optional (user's choice).** The facts command needs no Soufflé. Rule tests run
   Soufflé on small hand-written fact sets and skip when `souffle` is not on PATH, as cobble's
   parser tests skip without the bridge JAR.
7. **`make carddemo-all`** (`tools/rebuild-all.sh`) gains a step writing `$OUT/datalog/`.
8. **Docs:** `docs/reference/cobble/datalog.md` (the command, every relation and its columns, the
   library and how a question states its target), linked from `docs/README.md`; the
   `cobble-artifacts` skill names the facts directory.

## Success

- The CardDemo rebuild's facts give the experiment's results: per relation, the same rows as the
  experiment's `facts/` for the same run, except the origin and sink columns already typed; and
  the untracked credit, sign-on, menu and claims questions, rewritten on the library, reproduce
  their current result rows and the four saved proofs. Rewriting them is part of this work's
  verification but stays untracked (my call).
- No guessed fact: `cfg_entry` equals the CFG's `entry` for every program.
- `schema.dl` and the facts files agree by construction (one definition each).

## Left to the builder

- Module and class names; how relation definitions are grouped into files.
- Which existing typed reader serves each artifact, and writing one where none exists.
- The exact split of rules between files, within the table above.
