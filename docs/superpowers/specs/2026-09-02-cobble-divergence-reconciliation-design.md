# Reconciling cobble's divergences: one canonical version of each module

**Date:** 2026-09-02
**Status:** executed (forge ca7a6c26..a413494b, red-dragon 0301168a and 265b6aa6)
**Follows:** `2026-09-01-delete-stale-graph-stack-design.md` (deleted forge's graph
stack) and the wave-1 integration commit `ca7a6c26` (landed cobble as a workspace
member and deleted its identical copies).

## Problem

Cobble is a workspace member and its byte-identical copies are gone. Thirteen
modules remain duplicated, and every one of them genuinely differs. Until each
has a single canonical version, the workspace has two answers to the same
question and the backporting this consolidation exists to end continues.

The direction of the divergence is not uniform, which is why a blanket rule —
"cobble is the successor, take cobble" or "red-dragon is canonical, take
red-dragon" — is wrong for this set. Six modules have red-dragon ahead, five have
cobble ahead, and three are neither.

## Method

Raw diffs mislead here. Cobble and red-dragon are formatted by different Black
versions, so import wrapping alone reports a module as differing by six lines
when it is identical (`ref_mod` was exactly this). Every comparison below is
taken after normalising the `cobble.*` namespace away and running both sides
through Black at line length 88. What survives that is a real difference.

Claims about whether a thing is used were checked against the code rather than
taken from either side's comments — see `ast_store` and `proc_expand` below.

## The assessment

### red-dragon is ahead — delete cobble's copy

Cobble is behind the recent edit-picture, index-items and SEARCH work. Nothing
here needs an upstream change; the copies simply go.

| Module | What red-dragon has that cobble lacks |
| --- | --- |
| `interpreter/cobol/asg_types.py` | SPECIAL-NAMES currency sign, refusing the multi-character form that would change every field's width; `indexed_by` from `OCCURS ... INDEXED BY`, whose order a Format 1 SEARCH depends on; `UnsupportedEditPictureError` re-raised with the field name |
| `interpreter/cobol/cobol_types.py` | `currency` and `scale` (PIC P decimal scaling) on the descriptor; `holds_characters` and `_CHARACTER_CATEGORIES`; a deliberately coarser category set, with ALPHABETIC and EXTERNAL_FLOAT refused at `pic_parser` rather than given members; a `byte_length` fallback for descriptors built without a picture |
| `interpreter/cobol/edit_picture.py` | +305 lines net |
| `interpreter/cobol/pic_parser.py` | +117 lines net |
| `interpreter/cobol/picture.py` | +53 lines net |
| `interpreter/cobol/cobol_statements.py` | Style only — `collections.abc.Sequence`, bare annotations, `_serialize_ref_mod_expr` lifted to module level. No semantic divergence |

### cobble is ahead — port into the canonical module

| Module | What cobble has | Canonical home |
| --- | --- | --- |
| `interpreter/cobol/cobol_expression.py` | `_BUILDERS` dispatch table keyed by the bridge's `kind`; `FigurativeNode`, `LengthOfNode`, `DfhRespNode`; `ToFieldEnd` sentinel replacing `RefModNode.ref_mod_length = None` | red-dragon |
| `interpreter/cobol/ast_store.py` | `AsgJsonParser` protocol replacing `Any`; `AstParseError` carrying the member name; a tqdm bar with a `desc` naming the phase; `temp_ast_store`; the dead MEMORY strategy removed | red-dragon |
| `interpreter/cobol/subprocess_runner.py` | `SubprocessRunner.run`'s `command` widened to `Sequence[str]`; a comment recording why the codec is latin-1 | red-dragon |
| `jackal/jcl/bridge_parser.py` | `_from_bridge_json` de-duplicating the decode-and-wrap that `parse` and `parse_proc` each repeat; `parse_to_json` and `job_from_bridge_json`, which `jcl_store` needs | jackal |
| `jackal/jcl/parser.py` | `bridge_parser()` factory, for a caller driving many members through one parser rather than one text through `parse_jcl` | jackal |
| `jackal/jcl/proc_expand.py` | `dataclasses.replace` in place of positional rebuilds of `Step`/`DD`/`Job`; the substitution and override logic decomposed into named functions | jackal |

Two of these carry a claim that was checked rather than believed:

**`ast_store` and the MEMORY strategy.** Cobble removed `AstStrategy` on the
grounds that nothing constructed MEMORY. That is still true: `AstStrategy.MEMORY`
appears only in red-dragon's own `tests/unit/cobol/test_ast_store.py`, and the
single production call site, `interpreter/project/cobol_compile.py:54`, asks for
DISK. Adopting cobble's version means `cobol_compile.py` must follow the rename
of the private `_key` to `_digest`, which it imports directly.

**`proc_expand` and the positional rebuilds.** Jackal's version rebuilds `DD`,
`Step` and `Job` by listing their fields positionally, which would silently drop
any field added later. It is **not** dropping one today — `DD`, `Step` and `Job`
have exactly 5, 6 and 3 fields and all are passed. The bug is latent, and
cobble's `replace` closes it before it can bite.

### Neither ahead

| Module | Resolution |
| --- | --- |
| `interpreter/cobol/cobol_parser.py` | The same feature under two names: cobble's `copybook_extensions` is red-dragon's `copybook_exts`. Take red-dragon's name and its `collections.abc` style, and add the parameter to `make_cobol_parser`, which red-dragon does not expose it on at all |
| `jackal/dsn.py` | **jackal** is ahead: a 3.12 `type` statement and a `match`, where cobble has `TypeAlias` and a dispatch dict because its own lint config parses as 3.11. Delete cobble's |
| `sql/statements.py` | Identical code; the docstrings differ only in describing the port versus describing squall. Delete cobble's |

## Correction to the wave-1 commit

`ca7a6c26`'s message states that the wave deleted "only copies that are
byte-identical to the canonical module". That is wrong for one file:
`interpreter/cobol/subprocess_runner.py` had cobble's `Sequence[str]` widening
and its latin-1 comment, and deleting it dropped both. The functional effect is
nil — every caller passes a list, and the suites were green — but the claim
overstated, and the widening is restored as part of the cobble-ahead ports above.

## Sequencing

Cheapest first, cobble's own suite as the gate at every step. A failure is a real
divergence to decide, not a mechanical fix to paper over.

1. **Delete the six red-dragon-ahead copies.** Pure deletion; no upstream commit.
2. **Delete `jackal/dsn.py` and `sql/statements.py`.** Same.
3. **Port the three jackal modules** into `jackal/`, then delete cobble's. Each
   is additive or behaviour-preserving, so jackal's own suite must stay green.
4. **Port `ast_store` and `subprocess_runner` into red-dragon**, and add the
   copybook-extension parameter to `make_cobol_parser`. Land in `~/code/red-dragon`,
   push, bump forge's submodule. `cobol_compile.py` follows the `_key` rename.
5. **Reconcile `cobol_expression`** (tracked as `forge-jtu`). Last, because it is
   the only one needing a decision beyond the port, and because it unblocks the
   whole EXEC CICS parsing layer — `ref_mod`, `cics_visitor`, `statements` and
   `cics_parser` all pull the expression vocabulary in with them, and both CICS
   grammars are already byte-identical.

## Correction: what step 5 actually found

The assessment above says cobble's `cobol_expression` carries three node kinds
red-dragon lacks. That was wrong. red-dragon already read `figurative`,
`length_of` and `dfhresp` — commit `aac34001`, "read the three operand kinds the
bridge already emits" — so the whole-program ASG loss was already fixed there.
What cobble actually adds is the `_BUILDERS` dispatch table replacing the
if-chain, and the typed `JsonExpr` reading helpers.

Chasing that difference turned up a live defect neither side had diagnosed, and
it is the one the reasoning below was written for after all, just one layer
down. red-dragon could **parse** all three kinds and **lower** none: each fell
through `lower_expr_node`'s "Unknown expression node type" branch to the constant
0, so `COMPUTE WS-N = LENGTH OF WS-A` silently computed 0. Reading a kind without
lowering it is exactly the crash-traded-for-a-wrong-answer this design warned
about — it had simply already happened. Fixed in red-dragon `265b6aa6`, with a
test per kind; four of the eight fail against the unfixed lowering.

`ToFieldEnd` was **not** adopted. Nothing outside cobble's own
`cobol_expression` reads it — cobble never lowers — while taking it would
rewrite `ref_mod_length is not None` at eight sites in executing lowering paths.
red-dragon keeps `None`.

## The `cobol_expression` decision

Adopting cobble's expression module makes `CobolASG.from_dict` accept three node
kinds the bridge already emits and red-dragon currently rejects. Cobble validates
against one consumer — it parses and walks, never lowers — and red-dragon has
two more.

`condition_lowering.py` already has fallbacks for an `ExprNode` it does not
recognise: a warning and `const_to_reg(0)`, or a `{"kind": "ref", "name": ""}`.
Adding the three node types without teaching the lowering what they mean
converts a loud `ValueError` into silently wrong IR — a figurative constant
lowers to `0`, correct for `ZEROS` and wrong for `SPACES`, `HIGH-VALUES`,
`LOW-VALUES` and `ALL` literals; `LENGTH OF` becomes a reference to a field named
`""`. Trading a crash for a wrong answer is a regression for a consumer that
executes.

So this step is not done when the parse succeeds. It is done when the lowering
has been given an explicit answer for `FigurativeNode`, `LengthOfNode` and
`DfhRespNode`, and for `ToFieldEnd` where `RefModNode.ref_mod_length` used to be
`None`, with a test for each.

## Verification

- Cobble's suite passes at every step — the falsification experiment for the
  premise that a copy was redundant.
- Jackal's, cicada's and red-dragon's own suites stay green across steps 3–5,
  since those steps change modules those packages execute.
- `uv run lint-imports` and Black stay clean.
- After step 5, nothing under `cobble/cobble/` shadows a canonical module: the
  remaining tree is cobble's own corpus tooling and the graph stack it now owns.
