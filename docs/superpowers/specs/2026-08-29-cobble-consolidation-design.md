# Consolidating cobble into red-dragon-forge

**Date:** 2026-08-29
**Status:** design, approved in outline; not yet planned or implemented

## Problem

`~/code/cobble` is a fork of the RedDragon/forge parsing stack, made to run a
large client COBOL/JCL corpus. Corpus pressure has made it the place where
grammar and parser defects are found first, so fixes accumulate there and have
to be carried back by hand. One such sweep (2026-08-28/29) moved nine ProLeap
grammar commits, the JCL bridge grammar and its two-stage parse, XML GENERATE
through the COBOL bridge, `-copybook-ext`, CICS `LINK APPLID/RETCODE`, latin-1
source decoding, and z/OS DISP defaulting. Every item was mechanical to port and
none was hard to find; the cost is that the sweep has to happen at all, and that
half-ported coupled changes are easy to miss — the DISP defaults were the other
half of a grammar fix, and porting only the grammar left JCL that parsed and
then failed in the model.

The backporting is a symptom. The cause is that cobble holds **copies** of code
that red-dragon and forge already own.

### Drift observed while this design was being written

Cobble states its own invariant, in `cics/verb_source_asg.py`: *"THIS IS THE ONE
SEAM FILE — the only ported module permitted to contain real logic changes
(everything else in cobble/ is byte-for-byte + import-rewrite)."* That invariant
no longer holds. In the hours between the backport sweep and this document, eight
commits landed in cobble, and four modules that are meant to be identical copies
diverged:

| Module | Changed lines vs. canonical |
| --- | --- |
| `cics/flow_map.py` | 239 |
| `cics/flow_graph_core.py` | 172 |
| `knowledge_graph/render.py` | 96 |
| `interpreter/project/graph_types.py` | 20 |

This is not an argument against the design; it is the strongest argument for it,
and it changes two things below. The reconciliation list is no longer short, and
it grows with elapsed time — so the cutover is time-sensitive in a way a
structural refactor normally is not. Deletion can no longer be assumed safe for
the CICS graph layer, because there the copies genuinely differ.

## The key observation

There is no duplication between red-dragon and forge. Forge consumes red-dragon
as a submodule; cicada, jackal, and knowledge_graph exist in exactly one place.
**Every duplicated module in the workspace is a cobble copy**, including its
`sql/statements.py`, whose own docstring records that it was ported from Squall.

So the "common thing all three depend on" already exists — it is red-dragon plus
the forge workspace members. Cobble keeps copies only because it is a separate
repository that wanted a thin dependency set (`lark`, `networkx`, `antlr4`,
`pyyaml`, `tqdm`) rather than red-dragon's `pydantic` / `litellm` / `tree-sitter`
/ `mcp`. Inside forge that reason disappears.

An earlier draft of this design extracted a shared `core` repository holding
grammars, both Java bridges, the ASG model, CICS EXEC parsing, the JCL model and
knowledge-graph primitives. It was rejected as solving a problem the workspace
does not have: it would have created a third repository and a new pinning
workflow to de-duplicate code that is only duplicated in one direction, from one
consumer.

## Decision

**Fold cobble into red-dragon-forge as a uv workspace member, delete its
duplicated packages, and constrain what it may import.** No new repository, no
extraction. red-dragon stays a separate repository, vendored as today.

## Scope

### What cobble keeps

Its own work, which exists nowhere else:

| Module | What it is |
| --- | --- |
| `diagnosis/` | Parse-only corpus sweeps: `diagnose-cobol`, `diagnose-jcl`, `diagnose-copybooks` |
| `corpus_config.py` | Corpus YAML — the directories and globs a run walks |
| `cli_logging.py` | The stdout-is-JSON / stderr-is-summary channel split |
| `matching_files.py` | Glob resolution over a corpus |
| `jcl/jcl_store.py` | Parsed-JCL cache, so a corpus parses each member once |
| `canonical_export.py` | Canonical knowledge-graph export |
| `build_graph.py` | Corpus-generic graph build (forge's `build_carddemo_graph` is corpus-specific) |
| `cics/synth_csd.py`, `generate_csd.py` | Synthetic CSD for a corpus that arrived without one |

Its corpus assets move with it: `config/*.yaml`, `sym/`, `bms-macros/`,
`cics-copybooks/`, `reference/`.

The three `[project.scripts]` entry points stay on cobble's own `pyproject.toml`,
so `uv run diagnose-jcl` keeps working from the workspace root. That requires
cobble to remain an installed (editable) package rather than a bare directory —
the same arrangement it has today, for the same reason.

### What cobble deletes

Copies, in every case, of something the workspace already owns:

| Deleted from cobble | Canonical home |
| --- | --- |
| `proleap-bridge/` + its ProLeap fork submodule | `vendor/red-dragon/proleap-bridge/` |
| `jcl-bridge/` | `jackal/jcl-bridge/` |
| `interpreter/` | `vendor/red-dragon/interpreter/` |
| `cics/` | `cicada/cics/` |
| `jackal/` except `jcl/jcl_store.py` | `jackal/jackal/` |
| `knowledge_graph/` except `canonical_export.py` | `knowledge_graph/` |
| `bms_copybook_gen/` | `cicada/cics/bms/` |
| `sql/statements.py` | `squall/squall/statements.py` |

Imports rewrite mechanically: `cobble.interpreter.cobol.*` → `interpreter.cobol.*`,
`cobble.cics.*` → `cics.*`, `cobble.jackal.*` → `jackal.*`,
`cobble.knowledge_graph.*` → `knowledge_graph.*`,
`cobble.bms_copybook_gen` → `cics.bms`, `cobble.sql.statements` → `squall.statements`.

### What moves into cicada rather than staying in cobble

Two cobble modules are not corpus tooling and do not belong behind the cobble
boundary:

**`cics/verb_source_asg.py`** is the VM-free, ASG-walk source of `CicsVerb`
values. Cicada already documents this exact seam from the other side — its
`verb_source_lowering.py` says the knowledge-graph pipeline "sources the same
`{program: [CicsVerb]} shape from a typed-ASG walk instead", which is precisely
this module. It is the second implementation of a two-implementation seam cicada
already owns, so it lands beside its sibling and shares `cics.flow_graph_core`.

**`cics/asg_dialect_scope.py`** registers the coprocessor dialect parsers around
ASG construction. `parse_statement` resolves coprocessor statement types through
the `_dialect_parsers` ContextVar, whose default is empty, and an unregistered
type is fatal to the whole program's ASG rather than to the one statement. Any
path that turns bridge JSON into a `CobolASG` needs this, not just cobble's.

Forge has the same defect latently. `knowledge_graph/build_carddemo_graph.py`'s
`_build_cobol_file_graph` builds ASGs through `AstStore.get` without registering
dialect parsers; it escapes today only because it filters CICS programs out by
name using the CSD-derived set, and because each program is wrapped in
`except Exception` that downgrades the failure to a logged warning. A batch
program with embedded `EXEC SQL` and no CICS would still raise
`Unknown COBOL statement type: 'EXEC_SQL'` and be silently absent from the graph.
On cobble's corpus the equivalent defect accounted for 2,129 of 3,779 members.
This is tracked as a bug in its own right, fixable before or independently of the
consolidation.

### Out of scope

red-dragon's repository boundary; extraction of a shared core (see *Future
optionality*); any change to cicada, squall, or jackal beyond the reconciliations
listed below.

## Architecture

Cobble becomes a workspace member beside `cicada/`, `squall/`, `jackal/`,
`knowledge_graph/`, with its own `Makefile` and `pyproject.toml` per the
workspace's existing independently-buildable convention. It sits in the same
tier as `red_dragon_forge`: a composition layer permitted to import several
packages, which nothing else may import.

```
red-dragon (own repo)          VM, IR, lowering, LLM tooling
  └── vendored by forge
red-dragon-forge
  ├── cicada     CICS runtime            ─┐
  ├── squall     EXEC SQL runtime         │ static surface exposed to cobble
  ├── jackal     JCL/batch runtime        │ (parsing, model, graph only)
  ├── knowledge_graph                    ─┘
  ├── red_dragon_forge   composition layer
  └── cobble             corpus onboarding + analysis
```

### The import contract

The contract names the **static surface** rather than granting cobble blanket
access, because the set of modules cobble may touch is exactly the content a
future shared core would need.

Import-linter enforces prohibitions, not permissions, so only the forbidden list
below is machine-checked. The allowed list states intent and is what a future
extraction would read; keeping the two in step is a review obligation, not an
automated one.

Allowed: `interpreter.cobol.*`; `cics.cics_parser`, `cics.cics_visitor`,
`cics.csd_parse`, `cics.cics_grammar`, `cics.bms`, `cics.statements`;
`jackal.model`, `jackal.dsn`, `jackal.value_parts`, `jackal.jcl.*`,
`jackal.jcl_graph`, `jackal.cobol_file_graph`; `squall.statements`;
`knowledge_graph`.

Forbidden: cicada's runtime (`dispatcher`, `vsam`, `builtins`, `bootstrap`,
`conversational`, `strategy`, `coprocessor`, `terminal`, `le_stubs`, `vm_init`);
jackal's execution layers (`runner`, `cli`, `cobol_step`, `catalog`, `idcams`,
`utilities`, `results`); squall beyond `statements`; and `red_dragon_forge`.
Additionally, nothing may import `cobble`.

Implemented as `forbidden` contracts in `.importlinter`, with `cobble` added to
`root_packages` (and `red_dragon_forge` added so it can be named as a forbidden
target). `uv run lint-imports` already runs in pre-commit and CI.

## Reconciliation

Cobble has moved ahead of the canonical modules in two distinct ways, and the two
need opposite treatment.

**Group A — copies that genuinely differ.** `cics/flow_map.py`,
`cics/flow_graph_core.py`, `knowledge_graph/render.py`, and
`interpreter/project/graph_types.py` carry real changes (see *Drift observed*
above): a `START_TRANSID` edge kind for `EXEC CICS START TRANSID`, an `AttrValue`
type replacing `Any` on graph attributes, a CICS-flow pass that accounts for
itself, collision reporting restricted to transactions the corpus names, and an
invariant that every CICS program is defined.

For these, **reconcile before deleting, not after**. Deleting cobble's copy and
repointing imports would silently drop the newer behaviour, and the suite would
not necessarily catch it — cobble's tests would move to the canonical module and
fail, but only if they were ported in the same step. Each of these four is a
merge decision taken with both versions in hand, landed into the canonical module
first, with cobble's copy deleted only once its tests pass against the canonical
one.

**Group B — cobble-only additions with a coupling.** Each is a one-time decision,
not ongoing maintenance, and each lands as its own commit **after** the
deletions:

1. **`ast_store`** — cobble removed a `MEMORY` strategy it found dead and
   introduced an `AsgJsonParser` protocol. Whether `MEMORY` is dead is a question
   about red-dragon's callers, not cobble's; resolve it in red-dragon or keep
   red-dragon's version.
2. **`CsdParseError`** — wraps lark's `UnexpectedInput` so consumers need not
   catch bare `Exception`. Changes an exception contract; tracked as a filed
   issue.
3. **`canonical_export`** — cobble-only. Decide whether it is a knowledge_graph
   concern or corpus-specific; default to leaving it in cobble.
4. **`jcl_store`** — depends on `parse_to_json`, `job_from_bridge_json`, and the
   `_from_bridge_json` deduplication in cobble's `bridge_parser`. If `jcl_store`
   stays in cobble, jackal must adopt those three. This is the remainder of the
   file whose DISP half was already ported.

Mechanical cleanup during the import rewrite: cobble's `typing.Callable` and
string annotations become the workspace's `collections.abc` style; `tqdm` joins
the dependency set.

## Sequencing

Incremental, with a green suite at every step:

1. Land cobble as a workspace member with its copies **intact**. Baseline.
2. Delete the two Maven bridges and the ProLeap submodule. Pure deletion — only
   JAR paths change, no Python coupling to unpick, and it is where the largest
   share of the manual backporting went.
3. Delete and repoint the layers whose copies are still identical, one per step:
   `interpreter` (excluding `project/graph_types.py`), `jackal`,
   `bms_copybook_gen`, `sql`.
4. Reconcile Group A, one module per step, then delete cobble's copy: `flow_map`,
   `flow_graph_core`, `render`, `graph_types`. Move `verb_source_asg` and
   `asg_dialect_scope` into cicada.
5. Delete and repoint the rest of `cics` and `knowledge_graph`.
6. Add the import contract once the copies are gone.
7. Reconcile Group B.

**Freeze cobble's shared copies for the duration.** Group A exists because
development continued in copies during a window when nobody had decided the
copies were frozen. Changes to a shared module made in cobble after this design
is approved should land in the canonical module instead — otherwise step 4's
merge list grows underneath the work.

## Verification

Cobble's own suite, run against the canonical modules instead of its copies, is
the falsification experiment for this design. If it passes, the copies were
redundant and the premise holds. **Every failure is a genuine divergence
requiring a decision, not a mechanical fix to paper over** — that suite is the
gate on each deletion step, and a failure should stop the step rather than be
patched around.

Supporting gates: `uv run lint-imports` for the contract; `make test-all` and CI
extended to cover cobble; the existing per-package suites unchanged, since
nothing outside cobble changes except the four reconciliations.

## Consequences

**Gained.** Backporting stops by construction rather than by discipline. Coupled
changes cannot be half-ported, because there is only one copy to change. The
import contract makes the static/runtime boundary continuously verified rather
than conventional.

**Lost.** Cobble stops being independently thin: a uv workspace has one venv, so
red-dragon's heavier dependencies are installed even though cobble never calls
them. Its *declared* dependencies stay honest and the contract stays enforced, so
this is an installation-weight cost, not an architectural one.

**Also lost.** Cobble's separate repository, release cadence, and Beads database.
Its issues merge into forge's.

**Cost of delay, measured.** Between the backport sweep and this document, four
shared modules diverged by roughly 530 lines, turning a four-item reconciliation
into an eight-item one with a merge phase it did not previously need. That rate
is the price of leaving the copies live, and it is why the sequencing above puts
a freeze on shared modules ahead of the mechanical work.

## Future optionality

Should cobble ever need to run somewhere lean — a client machine, constrained CI,
shipping without the VM and LLM stack — the thin core becomes worth extracting.
The import contract is what makes that cheap: the modules cobble is permitted to
import *are* the core's contents, and CI proves continuously that the list is
both sufficient and closed. Extraction becomes mechanical rather than
archaeological. This is deliberately deferred, not designed in.
