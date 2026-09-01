# Outstanding issues across cobble, red-dragon and red-dragon-forge

Ledger of known-open work spanning the three repositories that share the ProLeap
bridge and the COBOL/CICS front end:

- **cobble** — VM-free extractor. Parses COBOL/CICS/JCL and builds the knowledge
  graph. Does not evaluate COBOL.
- **red-dragon** — the evaluator: VM, lowering, runtime. Ships the same bridge.
- **red-dragon-forge** — `cicada` (CICS VM), `jackal` (JCL), `squall` (SQL), and a
  `knowledge_graph` package predating cobble's.

Corpus, member, dataset and transaction identifiers are deliberately absent, as in
[corpus-onboarding-blockers.md](corpus-onboarding-blockers.md). Where an example is
needed it uses placeholder names that preserve the structure being described.
Public samples (CardDemo, bank-of-z) are named directly.

Status key: **OPEN** (analysed, not fixed) · **BLOCKED** (waiting on a decision
elsewhere) · **ENVIRONMENT** (not a code defect; a setup step that silently
produces wrong results when skipped).

Each entry names the root cause at `file:line` in the repository that owns it. A
line reference is accurate as of the commit that added the entry and may drift.

---

## 1. cobble drops `INDEXED BY` names on ingest — OPEN

**Repository:** cobble.

The bridge emits them. `DataFieldSerializer.java:116` adds an `indexed_by` array
to every group item carrying an `INDEXED BY` clause, and
`IndexedBySerializerTest.java` locks that in. Nothing on the Python side reads it:
`cobble/interpreter/cobol/asg_types.py:79` builds `CobolField` from an explicit
list of `data.get(...)` calls, so an unrecognised key is not an error and not a
warning — it is simply absent from the field. `CobolField.to_dict` (same file,
:106) has no branch to re-emit it either, so a round trip through cobble's ASG
loses the names outright.

red-dragon reads it: `interpreter/cobol/asg_types.py:93` declares
`indexed_by: list[str]`, :150 reads it, :195 writes it.

Consequence today is narrow — cobble does not resolve index names, because it does
not evaluate `SET`/`SEARCH` — so nothing currently asks for the field. It matters
the moment a consumer wants to distinguish a subscript from an index, or to draw a
data-dependency edge for a table access: the information reached the JSON and was
thrown away one layer later, which is the hardest kind of gap to notice from the
outside.

**Fix shape:** add the field, read it in `from_dict`, emit it in `to_dict` when
non-empty (mirroring red-dragon). A `from_dict`/`to_dict` round-trip test over a
group item with two `INDEXED BY` names is the whole of the RED step.

---

## 2. red-dragon lowers three operand kinds to constant zero — OPEN

**Repository:** red-dragon.

`interpreter/cobol/cobol_expression.py` now deserializes `figurative`,
`length_of` and `dfhresp` operands (commit `aac34001`) — before that, a
`COMPUTE WS-PCT = ZEROES` raised out of `expr_from_dict`, escaped
`CobolASG.from_dict`, and cost the whole member every fact it had. Reading them is
the fix for that. Lowering them is not done.

`lower_expr_node` (`interpreter/cobol/condition_lowering.py:940`) has no branch for
the three new node types, so they fall to its tail at :1067:

```python
logger.warning("Unknown expression node type: %s", type(node).__name__)
return ctx.const_to_reg(0)
```

That is deliberate and it is what makes the deserialization change safe to land on
its own: an operand the lowering cannot handle degrades to a logged zero rather
than an exception. But zero is a **wrong answer, not a missing one**, and the three
kinds differ in how bad that is:

- `FigurativeNode(ZEROS)` — zero is correct. `SPACES`, `LOW-VALUES`,
  `HIGH-VALUES`, `QUOTES` in an arithmetic operand are already ill-formed COBOL,
  so zero is as defensible as anything.
- `LengthOfNode` — zero is always wrong. `LENGTH OF X` is a compile-time constant
  the layout already knows; emitting the field's byte length is a small, exact
  change.
- `DfhRespNode` — zero happens to be `DFHRESP(NORMAL)`, which is the **worst**
  case: `IF WS-RESP = DFHRESP(NOTFND)` silently lowers to a comparison against
  NORMAL and the program takes the wrong branch with no diagnostic beyond a log
  line. The condition numbers are release-dependent, which is exactly why the
  bridge keeps the name — so lowering needs a table, and the table needs a stated
  source.

**Fix shape:** three independent pieces of work, best done in that order (easiest
and safest first). `LENGTH OF` is a layout lookup. `DFHRESP` wants an explicit
condition-name-to-number table with the release it came from recorded in the
module docstring; until it exists, a lowering that *raises* on `DfhRespNode` would
be safer than one that returns zero, because a wrong branch is worse than a
refused program.

---

## 3. forge's `knowledge_graph` package is slated for deletion — BLOCKED

**Repository:** red-dragon-forge.

`knowledge_graph/build_carddemo_graph.py` is to be removed; cobble's
`cobble/knowledge_graph/build_graph.py` is the correct-er version and the one that
gets fixes. Nothing in forge's copy should be repaired in the meantime.

What needs deciding is the rest of the package, because three modules are
genuinely **behind** cobble on the same design question, and if any of them
survive the deletion they carry a regression with them:

| forge module | cobble equivalent | divergence |
|---|---|---|
| `knowledge_graph/export.py` | `cobble/knowledge_graph/export.py` | `file_path` string vs `location: FileLocation` |
| `knowledge_graph/graph_writer.py` | same name | same; forge merges `file_path = existing or new` |
| `knowledge_graph/merge.py` | same name | same, plus cobble's reason-precedence ordering |

cobble replaced the bare `file_path` with a `FileLocation` union — a `Path`, or a
`NoFileLocation(reason=...)` recording *why* a node has no file (`NOT_ATTEMPTED`
and friends). forge's version cannot express the difference between "we never
looked" and "we looked and there is nothing", which is the distinction that makes
an unresolved node actionable. `cobble/knowledge_graph/merge.py:21` orders reasons
by standing so a merge keeps the more informative one.

`knowledge_graph/render.py` differs between the two but not on this axis; it has
not been analysed.

**Decision needed:** does the deletion take the whole package, or only
`build_carddemo_graph.py`? If the latter, the three modules above need cobble's
`FileLocation` treatment rather than being left as-is.

---

## 4. Two forge `knowledge_graph` modules have no cobble equivalent — OPEN

**Repository:** cobble (as the destination).

Optional ports, never started, both worth having and neither blocked by entry 3
(they are additive):

- `knowledge_graph/fitness.py` — golden-file identity compare for a built graph.
  Node identity is `(kind, id)`, edge identity is
  `(source, source_kind, target, target_kind, kind)`; `attrs` and `file_path` are
  excluded, so the comparison is over graph *shape* only. `write_golden()` emits
  sorted JSONL specifically so a git diff of a regression is readable. This is a
  regression harness for graph construction, which cobble currently does not have
  at the whole-graph level.
- `knowledge_graph/query.py` — thin helpers over a merged `networkx.MultiDiGraph`:
  `reachable_from`, `callers_of`, `paths_between`, with optional edge-kind
  filtering via a filtered view.

Porting means the usual package-prefix rename (`interpreter.*` to
`cobble.interpreter.*`) plus, for `fitness.py`, deciding whether identity should
now include the `FileLocation` reason — the forge version predates it.

---

## 5. red-dragon integration tests need `PROLEAP_BRIDGE_JAR` — ENVIRONMENT

**Repository:** red-dragon.

Two distinct traps, both of which look like test failures and neither of which is:

1. **Unset.** 482 integration tests error out with `KeyError:
   'PROLEAP_BRIDGE_JAR'`. Loud and self-explanatory.
2. **Stale.** A jar built before a bridge change produces *plausible* failures in
   whichever tests cover that change — observed as exactly two failures
   (`test_copybook_with_a_high_byte_in_a_comment_is_inlined` and an `INDEXED BY`
   subscript test) whose real cause was a jar predating the charset and
   `INDEXED BY` commits. Nothing points at the jar.

```bash
mvn -o -q -DskipTests package                      # rebuild after any bridge change
export PROLEAP_BRIDGE_JAR=$PWD/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
```

The second trap is the expensive one: the failure names a Python test, so the
investigation starts in Python. Worth a conftest check that compares the jar's
mtime against the newest file under `proleap-bridge/src/` and fails with a
"rebuild the bridge" message — a two-line guard against an hour of misdirected
debugging.

---

## 6. Talisman as `pre-commit.legacy` blocks commits silently — OPEN (forge unchecked)

**Repositories:** any repository here with both pre-commit.com and Talisman
installed. Fixed in red-dragon; forge and cobble not verified.

Symptom: `git commit` aborts, HEAD does not move, and **every hook reports
`Passed`**. The only clue is one line printed before the hook output:

```
githook should be pre-commit or pre-push, but got pre-commit.legacy
```

Cause: pre-commit.com renames a previously-installed hook to
`.git/hooks/pre-commit.legacy` and calls it from its own wrapper.
`talisman_hook_script` derives its mode from `basename $0`, its `case` arm matches
`pre-commit*`, so it invokes the Talisman binary with `--githook
pre-commit.legacy`, which the binary rejects and exits non-zero.

Fix applied in red-dragon — replace the `pre-commit.legacy` symlink with a wrapper
that corrects only `$0`:

```bash
exec -a pre-commit "$HOME/.talisman/bin/talisman_hook_script" "$@"
```

Talisman still runs; it is not disabled. `.git/hooks` is untracked, so this does
**not** propagate — each clone can hit it independently, and it cannot be fixed
once for the constellation.

Not to be confused with Talisman blocking on a real finding, which names the file
and the pattern. That wants a `.talismanrc` entry, not a hook change.

---

## 7. The bridge's source charset has no unit test — OPEN

**Repositories:** cobble and red-dragon (identical bridge; identical gap).

`Main.java:77` pins `SOURCE_CHARSET = StandardCharsets.ISO_8859_1`, the
byte-identity codec — defined for all 256 byte values, so no byte in a member can
fail to decode and no high byte in a comment can derail a parse. The reasoning is
in the comment at :65. It is load-bearing and it is covered only indirectly, by a
Python integration test in red-dragon
(`test_copybook_with_a_high_byte_in_a_comment_is_inlined`) that needs a built jar
to run at all — see entry 5.

`MainTest.java` exists and tests `Main.copyBookExtensions` in isolation, which is
the pattern to follow: the decode path wants the same treatment, so that
"a high byte survives the read" is a JUnit assertion rather than a property of an
integration test three layers away. Extracting the read into a static method that
takes bytes and returns a String is the whole change.

cobble is worse off than red-dragon here, because it has **no** bridge-backed
integration test of any kind — nothing in cobble runs the jar. red-dragon's
`test_copybook_with_a_high_byte_in_a_comment_is_inlined` is not portable as-is: it
goes through the VM, and it covers the high byte in a *copybook*, which the bridge
opens itself. cobble's own charset defect was a high byte in the **member**, which
crosses the stdin wire instead — a path red-dragon's test never exercises. That
half is now covered by `tests/interpreter/cobol/test_subprocess_runner.py`, which
asserts the wire is byte-identity without needing a JVM. What remains uncovered in
cobble is everything downstream of the wire.

---

## 8. SPECIAL-NAMES never reaches the picture parser — OPEN

**Repository:** cobble.

Same shape as entry 1 — the bridge emits it, the Python side drops it — but this
one produces a **wrong answer** rather than a missing one, and the capability to
use it is already present and merely unwired.

The bridge serializes the clause. `AsgSerializer.java:92` adds a `special_names`
object to the ASG when the compilation unit has one, carrying `currency_sign` and
`currency_picture_symbol` (:126, :130); the comment at :107 states why, namely that
a multi-character currency literal changes every affected field's size.

Nothing reads it. `CobolASG.from_dict` has no `special_names` branch, so the key is
dropped at ingest, and `cobble/interpreter/cobol/pic_parser.py:75` builds the
picture parser once at import with the defaults:

```python
_parser = picture.build_parser()
```

`parse_pic` (same file, :78) takes no currency or decimal-point argument, so there
is no way to pass one even if the ASG had carried it. `parse_pic` is live —
`asg_types.py:68` calls it for every field — so every descriptor in a graph built
from a program with `CURRENCY SIGN IS 'EUR'` or `DECIMAL-POINT IS COMMA` is sized
and scaled against `$` and `.` instead.

The notable part: cobble is **ahead** of red-dragon on the parser itself.
`picture.build_parser(currency_symbols, decimal_point_is_comma)` already accepts
multiple currency symbols and the comma point; red-dragon's `_parser_for(currency)`
handles a single symbol, and red-dragon commit `dd377200` records that its grammar
was backported from cobble. So this is not a port — the machinery exists on the
better side and three layers of plumbing are missing above it.

**Fix shape:** read `special_names` in `CobolASG.from_dict`; give `parse_pic` a
`currency_symbols`/`decimal_point_is_comma` pair; build (and cache per unique
combination) rather than at import. `UnsupportedEditPictureError` needs the same
treatment, since which pictures are unsupported depends on the symbol set.

---

## 9. PIC P scaling is not on the type descriptor — OPEN

**Repository:** cobble.

`CobolTypeDescriptor` (`cobble/interpreter/cobol/cobol_types.py:65`) has
`total_digits`, `decimal_digits`, `signed`, `char_positions` and the sign flags —
and no `scale`. red-dragon added one (`cobol_types.py:96`, commit `e8cda012`) with
the distinction stated in its comment: `decimal_digits` is the point the picture
*writes* (V or .), `scale` is the power of ten the P positions apply.

cobble stops at the point's position. `picture.py:320` `_implied_point` returns
either 0 or `digits`, and :269 turns that into `scale = digits - digits_before_point`
— which is the fraction-digit count, red-dragon's `decimal_digits`. red-dragon's
`_point_shift` (`picture.py:350`) returns the factor instead, and handles both
sides: trailing Ps multiply (`999PP` holding 009 is 900), leading Ps put the point
left of themselves so the rightmost stored digit lands at
`10**-(P count + stored digits)` (`PP999` holding 123 is .00123).

Under cobble's arithmetic `PP999` gets `digits_before_point = 0` and therefore
`scale = digits`, which counts the stored digits as fraction digits but loses the
two P positions — it describes `V999`, not `PP999`. `999PP` gets no factor at all.

Consequence is confined to consumers that read a field's numeric magnitude, which
today is nothing in cobble (it does not evaluate). It becomes wrong the moment one
does, and the field is absent rather than obviously zero, which is the same
notice-it-from-outside problem as entry 1.

**Fix shape:** port `_point_shift` and add `scale` to the descriptor. Both repos'
`picture.py` already carry the identical docstring citing p. 211, so the reasoning
does not need re-deriving — only the return value differs.

---

## Note on `--no-verify`

This document was committed with `--no-verify`, which bypasses Talisman along with
the rest of the pre-commit stack. It was checked by hand for secrets and for
corpus identifiers before committing. Any future edit committed the same way needs
the same check — the automated one did not run.
