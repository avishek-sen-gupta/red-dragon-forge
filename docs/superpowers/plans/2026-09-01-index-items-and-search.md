# Index items, SEARCH and the unknown-name policy — Implementation Plan

> **COMPLETE (2026-09-02).** All eight tasks landed; red-dragon is pushed and the
> forge pointer bumped (`7130300`, `21fa444`, and later). Commit-by-commit mapping and
> the three deviations from this plan are recorded in the spec's *Status* section.
> Two of them matter to anyone reading the steps below as instructions: Task 5's index
> items needed their **own region**, not the sibling scope written here (in LINKAGE
> they corrupt the caller's argument storage — `db7b9c63`), and Task 6's bound had to
> read the **index value** rather than iterations performed, since `SET ix TO 5` can
> start the loop anywhere but 1 (`968e4bf8`). Task 3's `getIndexNames()` does not
> exist; the real chain is `getOccursIndexed()` → `getIndices()`, corrected in place
> at Task 3 Step 4.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `OCCURS ... INDEXED BY` tables searchable and subscriptable correctly, so a `SEARCH` over a real table returns a real answer instead of a silent false match.

**Architecture:** Four layers in dependency order. First remove the silence (one unknown-name policy shared by both expression lowerers), then stop `SET` writing operand names, then carry index names bridge → ASG → layout so index items exist at all, then make `SEARCH` use the table it was given for its bound and its implicit index.

**Tech Stack:** Python 3.13, Java 17 + Maven (ProLeap bridge), pytest, Graphviz-free. Red-dragon's own test harness (`_run_cobol` / `_first_region` / `_decode_alpha`).

**Spec:** `docs/analysis/2026-09-01-index-items-search-and-cics-verb-gaps.md` (defects A, B, C, D; steps 1–5 of its Suggested Order)

## Global Constraints

- **All code changes land in `~/code/red-dragon`, not in `vendor/red-dragon`.** The
  submodule here is a read-through checkout. Commit and push in the standalone
  clone, then bump this repo's pointer (Task 8).
- **Red-dragon issues go in red-dragon's Beads DB**, not forge's: `bd -C ~/code/red-dragon`.
  Anything under `interpreter/**` or `proleap-bridge/**` is a red-dragon issue.
- Formatting: Black, line length 88. Run `uv run black <files>` before committing.
- Invoke tooling as `uv run --no-sync …` in cicada; plain `uv run …` is fine in red-dragon.
- Java changes require `cd proleap-bridge && ./build.sh` before any Python test that
  parses COBOL will see them.
- Occurrence semantics: index items store an **occurrence number** (1-based), not an
  IBM-style byte displacement. Nothing reads their raw bytes, and the difference is
  unobservable unless a program REDEFINES an index or group-MOVEs one — both illegal.
  Say so in a comment wherever it is assumed.

## Out of scope

Defects E and F (CICS verbs, `HANDLE CONDITION`) — those are cicada, not red-dragon,
and get their own plans. `SEARCH ALL` (spec defect C4) — zero occurrences in the
corpus; the spec says explicitly not to sequence work behind it.

---

### Task 1: One unknown-name policy, shared by both expression lowerers

Defect B. Do this first even though it fixes no program: it converts every defect
below from a wrong answer into a diagnosable one.

**Files:**
- Modify: `interpreter/cobol/condition_lowering.py` (both lowerers, ~`:770` and ~`:952`)
- Test: `tests/integration/test_cobol_programs.py`

**Interfaces:**
- Consumes: nothing
- Produces: `_unresolvable_operand(ctx, name: str) -> Register` in
  `interpreter/cobol/condition_lowering.py`

- [x] **Step 1: Write the failing test**

In `tests/integration/test_cobol_programs.py`, add to the end of the file:

```python
class TestUnresolvableNamePolicy:
    """An undeclared data-name must not become a string literal.

    Both expression lowerers must agree. They did not: the dict-based one emitted
    a sentinel while the node-based one produced the name as a string, and because
    subscripts lower through the node path, an unresolvable subscript compared
    equal to everything and silently produced false matches.
    """

    def test_unresolvable_subscript_does_not_compare_equal(self):
        vm = _run_cobol(
            [
                "IDENTIFICATION DIVISION.",
                "PROGRAM-ID. TEST-UNRESOLVABLE.",
                "DATA DIVISION.",
                "WORKING-STORAGE SECTION.",
                "01 TBL-BYTES.",
                "   05 FILLER PIC X(3) VALUE 'AAA'.",
                "   05 FILLER PIC X(3) VALUE 'BBB'.",
                "01 TBL REDEFINES TBL-BYTES.",
                "   05 TBL-ROW OCCURS 2 TIMES.",
                "      10 TBL-KEY PIC X(3).",
                "77 WS-FOUND PIC 9(4) VALUE 0.",
                "PROCEDURE DIVISION.",
                "MAIN-PARA.",
                "    IF TBL-KEY (NO-SUCH-NAME) = 'ZZZ'",
                "        MOVE 1 TO WS-FOUND",
                "    END-IF.",
                "    STOP RUN.",
            ],
            max_steps=2000,
        )
        region = _first_region(vm)
        # An unresolvable subscript must NOT yield a value that matches 'ZZZ'.
        assert _decode_zoned_unsigned(region, 6, 4) == 0
```

- [x] **Step 2: Run test to verify it fails**

```bash
cd ~/code/red-dragon
uv run pytest tests/integration/test_cobol_programs.py::TestUnresolvableNamePolicy -v
```

Expected: FAIL — `WS-FOUND` is 1, because the symbolic subscript compares equal to `'ZZZ'`.

- [x] **Step 3: Extract the shared policy**

In `interpreter/cobol/condition_lowering.py`, add above `_lower_expr_dict`:

```python
def _unresolvable_operand(ctx: EmitContext, name: str) -> Register:
    """Lower a data-name that is not in the layout.

    The bridge sometimes tags a numeric literal as a ref (an abbreviated-condition
    operand "1"), so try the literal reading first. Anything else is a genuinely
    unresolvable name: emit an obviously-wrong sentinel rather than coercing the
    name to a string literal, so the failure is visible in the log and in the IR.

    Both expression lowerers route here on purpose. They disagreed once — the
    node-based one produced the bare name, and since subscripts lower through that
    path, `TBL-KEY (UNKNOWN-IX)` became string arithmetic yielding a SymbolicValue,
    which compares equal to anything. The divergence was the root cause, not either
    branch, so there is now one policy and one place to change it.
    """
    parsed = ctx.parse_literal(name)
    if isinstance(parsed, (int, float)):
        return ctx.const_to_reg(parsed)
    logger.warning("unresolvable field reference %r — emitting sentinel", name)
    return ctx.const_to_reg(f"UNRESOLVABLE__{name}")
```

- [x] **Step 4: Route both lowerers through it**

In `_lower_expr_dict`, replace the five lines from `# The bridge sometimes tags` through
`return ctx.const_to_reg(f"UNRESOLVABLE__{name}")` with:

```python
        return _unresolvable_operand(ctx, name)
```

In `lower_expr_node`'s `FieldRefNode` branch, replace:

```python
        return ctx.const_to_reg(ctx.parse_literal(node.name))
```

with:

```python
        return _unresolvable_operand(ctx, node.name)
```

- [x] **Step 5: Run the test and the surrounding suite**

```bash
uv run pytest tests/integration/test_cobol_programs.py::TestUnresolvableNamePolicy -v
uv run pytest tests/unit -q -p no:randomly
```

Expected: new test PASSES; unit suite unchanged. If existing tests fail, they were
relying on a name-as-string coercion — read each one; that reliance is the bug.

- [x] **Step 6: Commit**

```bash
uv run black interpreter/cobol/condition_lowering.py tests/integration/test_cobol_programs.py
git add interpreter/cobol/condition_lowering.py tests/integration/test_cobol_programs.py
git commit -m "fix(cobol): one unknown-name policy for both expression lowerers"
```

---

### Task 2: `SET target TO <data-item>` reads the item, not its name

Defect D. Must land **with or before** Task 5, or allocating index items turns a
masked defect into an active one: every `SET idx TO some-field` starts writing the
two characters of a name into a numeric field, which encodes as `0` and looks fine.

**Files:**
- Modify: `interpreter/cobol/lower_arithmetic.py:1768-1800` (both `TO` and `BY` branches)
- Test: `tests/integration/test_cobol_programs.py`

**Interfaces:**
- Consumes: nothing
- Produces: no new names; behaviour change only

- [x] **Step 1: Write the failing test**

```python
class TestSetFromDataItem:
    """SET A TO B must read B, not write the two characters "B"."""

    def test_set_to_data_item_reads_the_item(self):
        vm = _run_cobol(
            [
                "IDENTIFICATION DIVISION.",
                "PROGRAM-ID. TEST-SET-FIELD.",
                "DATA DIVISION.",
                "WORKING-STORAGE SECTION.",
                "77 WS-A PIC 9(4) VALUE 0.",
                "77 WS-B PIC 9(4) VALUE 7.",
                "PROCEDURE DIVISION.",
                "MAIN-PARA.",
                "    SET WS-A TO WS-B.",
                "    STOP RUN.",
            ],
            max_steps=2000,
        )
        region = _first_region(vm)
        assert _decode_zoned_unsigned(region, 0, 4) == 7

    def test_set_up_by_data_item_reads_the_item(self):
        vm = _run_cobol(
            [
                "IDENTIFICATION DIVISION.",
                "PROGRAM-ID. TEST-SET-BY-FIELD.",
                "DATA DIVISION.",
                "WORKING-STORAGE SECTION.",
                "77 WS-A PIC 9(4) VALUE 10.",
                "77 WS-B PIC 9(4) VALUE 3.",
                "PROCEDURE DIVISION.",
                "MAIN-PARA.",
                "    SET WS-A UP BY WS-B.",
                "    STOP RUN.",
            ],
            max_steps=2000,
        )
        region = _first_region(vm)
        assert _decode_zoned_unsigned(region, 0, 4) == 13
```

- [x] **Step 2: Run to verify both fail**

```bash
uv run pytest tests/integration/test_cobol_programs.py::TestSetFromDataItem -v
```

Expected: FAIL. The `TO` case yields 0 (the name `"WS-B"` encoded into a numeric
field). The `BY` case yields 10 or errors (`parse_literal("WS-B")` is not a number).

- [x] **Step 3: Read the source when it resolves — `TO` branch**

In `lower_arithmetic.py`, in the `if stmt.set_type == "TO":` branch, replace:

```python
            value_str_reg = ctx.const_to_reg(str(value_str))
```

with:

```python
            # SET A TO B is legal when B is a data item; stmt.values[0] is raw
            # operand text from the bridge and is never tested for being a name.
            # Untested, it wrote the two characters "B" — which encodes into a
            # numeric field as 0, so the symptom is a plausible zero, not a crash.
            if ctx.has_field(str(value_str), materialised):
                src_ref, src_rr = ctx.resolve_field_ref(str(value_str), materialised)
                value_str_reg = ctx.emit_decode_field(
                    src_rr, src_ref.fl, src_ref.offset_reg
                )
            else:
                value_str_reg = ctx.const_to_reg(str(value_str))
```

- [x] **Step 4: Same for the `BY` branch**

Replace:

```python
            step_reg = ctx.const_to_reg(ctx.parse_literal(step_val))
```

with:

```python
            # SET ... UP/DOWN BY <data-item> takes the same path as TO above.
            if ctx.has_field(str(step_val), materialised):
                step_ref, step_rr = ctx.resolve_field_ref(str(step_val), materialised)
                step_reg = ctx.emit_decode_field(
                    step_rr, step_ref.fl, step_ref.offset_reg
                )
            else:
                step_reg = ctx.const_to_reg(ctx.parse_literal(step_val))
```

- [x] **Step 5: Run tests**

```bash
uv run pytest tests/integration/test_cobol_programs.py::TestSetFromDataItem -v
uv run pytest tests/unit -q -p no:randomly
```

Expected: both new tests PASS, unit suite unchanged.

- [x] **Step 6: Commit**

```bash
uv run black interpreter/cobol/lower_arithmetic.py tests/integration/test_cobol_programs.py
git add interpreter/cobol/lower_arithmetic.py tests/integration/test_cobol_programs.py
git commit -m "fix(cobol): SET TO/BY a data item reads the item, not its name"
```

---

### Task 3: The bridge emits `INDEXED BY` names

Defect A, part 1 of 3. `OccursClause.getIndexNames()` is never called; a grep for
`IndexName` in `proleap-bridge/src/main/java/` returns nothing.

**Files:**
- Modify: `proleap-bridge/src/main/java/org/reddragon/bridge/DataFieldSerializer.java` (near `:100`, where `occurs` is added)
- Test: `proleap-bridge/src/test/java/org/reddragon/bridge/IndexedBySerializerTest.java` (create)
- Test fixture: `proleap-bridge/src/test/resources/fixtures/indexed_by.cbl` (create)

**Interfaces:**
- Consumes: nothing
- Produces: bridge JSON key `"indexed_by": ["MSG-IX", ...]` on a group carrying `OCCURS ... INDEXED BY`

- [x] **Step 1: Write the fixture**

`proleap-bridge/src/test/resources/fixtures/indexed_by.cbl`:

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IDXBY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  TBL-BYTES        PIC X(18).
       01  TBL REDEFINES TBL-BYTES.
           05  TBL-ROW OCCURS 3 TIMES INDEXED BY TBL-IX, TBL-JX.
               10  TBL-KEY  PIC X(3).
               10  TBL-VAL  PIC X(3).
       PROCEDURE DIVISION.
           STOP RUN.
```

- [x] **Step 2: Write the failing Java test**

`proleap-bridge/src/test/java/org/reddragon/bridge/IndexedBySerializerTest.java`, modelled
on the existing `XmlGenerateSerializerTest`:

```java
package org.reddragon.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.junit.Test;

import static org.junit.Assert.*;

/** OCCURS ... INDEXED BY names must reach the JSON; they are the only declaration
 *  an index item ever gets, so if they are dropped here nothing downstream can
 *  allocate the item and every subscript using it is unresolvable. */
public class IndexedBySerializerTest {

    @Test
    public void indexNamesAreEmittedOnTheOccursGroup() {
        JsonObject group = TestFixtures.findField(
                TestFixtures.serializeFixture("indexed_by.cbl"), "TBL-ROW");
        assertNotNull("TBL-ROW not found in serialized ASG", group);
        assertTrue("no indexed_by key emitted", group.has("indexed_by"));
        JsonArray names = group.getAsJsonArray("indexed_by");
        assertEquals(2, names.size());
        assertEquals("TBL-IX", names.get(0).getAsString());
        assertEquals("TBL-JX", names.get(1).getAsString());
    }

    @Test
    public void aTableWithoutIndexedByEmitsNoKey() {
        JsonObject group = TestFixtures.findField(
                TestFixtures.serializeFixture("xml_generate.cbl"), "SOME-RECORD");
        if (group != null) {
            assertFalse(group.has("indexed_by"));
        }
    }
}
```

If `TestFixtures` does not exist, read `XmlGenerateSerializerTest.java` and inline the
same fixture-loading and field-walking it uses; do not invent a helper class that the
build does not have.

- [x] **Step 3: Run to verify it fails**

```bash
cd ~/code/red-dragon/proleap-bridge
mvn -q -B test -Dtest=IndexedBySerializerTest
```

Expected: FAIL — `no indexed_by key emitted`.

- [x] **Step 4: Emit the names**

In `DataFieldSerializer.java`, immediately after the `occurs` block near `:100`:

```java
        List<String> indexNames = extractIndexNames(group);
        if (!indexNames.isEmpty()) {
            JsonArray arr = new JsonArray();
            for (String n : indexNames) {
                arr.add(n);
            }
            obj.add("indexed_by", arr);
        }
```

and add the extractor alongside `extractOccurs`:

```java
    /**
     * The INDEXED BY names on a group's OccursClause, in declaration order.
     *
     * <p>An index declared this way is compiler-allocated: there is deliberately no
     * `01 IX PIC ...` anywhere, so this clause is the item's only declaration. Order
     * matters — a Format 1 SEARCH with no VARYING advances the FIRST index.
     */
    private static List<String> extractIndexNames(DataDescriptionEntryGroup group) {
        List<String> names = new ArrayList<>();
        try {
            List<OccursClause> clauses = group.getOccursClauses();
            if (clauses == null || clauses.isEmpty()) {
                return names;
            }
            OccursIndexed indexed = clauses.get(0).getOccursIndexed();
            if (indexed == null || indexed.getIndices() == null) {
                return names;
            }
            for (Index ix : indexed.getIndices()) {
                if (ix.getName() != null) {
                    names.add(ix.getName().toUpperCase());
                }
            }
        } catch (Exception e) {
            LOG.fine("No INDEXED BY names: " + e.getMessage());
        }
        return names;
    }
```

Add the two imports beside the existing `OccursClause` one at `DataFieldSerializer.java:10`:

```java
import io.proleap.cobol.asg.metamodel.data.datadescription.Index;
import io.proleap.cobol.asg.metamodel.data.datadescription.OccursIndexed;
```

> **Correction to the spec.** The analysis doc's fix shape says to call
> `OccursClause.getIndexNames()`. **That method does not exist.** The real chain in the
> vendored ProLeap fork is `OccursClause.getOccursIndexed()` → `OccursIndexed.getIndices()`
> → `List<Index>`, where `Index extends NamedElement` and so has `getName()`. The code
> above uses the real API; the spec's grep evidence ("`grep -rn "IndexName"` returns
> nothing") still stands and its conclusion is unaffected.

- [x] **Step 5: Build and run**

```bash
cd ~/code/red-dragon/proleap-bridge && ./build.sh
mvn -q -B test -Dtest=IndexedBySerializerTest
```

Expected: PASS. `./build.sh` must succeed — later Python tasks parse COBOL through
this JAR and will not see the change otherwise.

- [x] **Step 6: Commit**

```bash
cd ~/code/red-dragon
git add proleap-bridge/src/main/java/org/reddragon/bridge/DataFieldSerializer.java \
        proleap-bridge/src/test/java/org/reddragon/bridge/IndexedBySerializerTest.java \
        proleap-bridge/src/test/resources/fixtures/indexed_by.cbl
git commit -m "feat(bridge): emit OCCURS ... INDEXED BY index names"
```

---

### Task 4: The ASG carries `indexed_by`

Defect A, part 2 of 3.

**Files:**
- Modify: `interpreter/cobol/asg_types.py` (`CobolField` dataclass ~`:81-90`, plus `from_dict` and `to_dict`)
- Test: `tests/unit/test_asg_types.py`

**Interfaces:**
- Consumes: bridge key `"indexed_by"` from Task 3
- Produces: `CobolField.indexed_by: list[str]`

- [x] **Step 1: Write the failing round-trip test**

Append to `tests/unit/test_asg_types.py`:

```python
def test_indexed_by_round_trips():
    """INDEXED BY names survive from_dict -> to_dict.

    They are the only declaration a compiler-allocated index gets; dropping them
    here leaves data_layout with nothing to allocate.
    """
    d = {
        "name": "TBL-ROW",
        "level": 5,
        "picture": "",
        "usage": "DISPLAY",
        "offset": 0,
        "occurs": 3,
        "indexed_by": ["TBL-IX", "TBL-JX"],
    }
    f = CobolField.from_dict(d)
    assert f.indexed_by == ["TBL-IX", "TBL-JX"]
    assert f.to_dict()["indexed_by"] == ["TBL-IX", "TBL-JX"]


def test_absent_indexed_by_defaults_empty_and_is_omitted():
    f = CobolField.from_dict(
        {"name": "X", "level": 5, "picture": "X(3)", "usage": "DISPLAY", "offset": 0}
    )
    assert f.indexed_by == []
    assert "indexed_by" not in f.to_dict()
```

- [x] **Step 2: Run to verify it fails**

```bash
cd ~/code/red-dragon
uv run pytest tests/unit/test_asg_types.py -k indexed_by -v
```

Expected: FAIL — `CobolField` has no attribute `indexed_by`.

- [x] **Step 3: Add the field**

In `asg_types.py`, beside `occurs_min` in the `CobolField` dataclass:

```python
    # Compiler-allocated index names from OCCURS ... INDEXED BY, in declaration
    # order. Order is load-bearing: a Format 1 SEARCH advances the first one.
    indexed_by: list[str] = field(default_factory=list)
```

In `from_dict`, beside the `occurs_min` read:

```python
            indexed_by=list(data.get("indexed_by", [])),
```

In `to_dict`, beside the `occurs_min` write:

```python
        if self.indexed_by:
            result["indexed_by"] = list(self.indexed_by)
```

- [x] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_asg_types.py -k indexed_by -v
uv run pytest tests/unit -q -p no:randomly
```

Expected: new tests PASS, unit suite unchanged.

- [x] **Step 5: Commit**

```bash
uv run black interpreter/cobol/asg_types.py tests/unit/test_asg_types.py
git add interpreter/cobol/asg_types.py tests/unit/test_asg_types.py
git commit -m "feat(cobol): carry INDEXED BY names on the ASG"
```

---

### Task 5: Allocate an index item per `INDEXED BY` name

Defect A, part 3 of 3. After this, `MaterialisedSectionedLayout.has_field("TBL-IX")`
is true and the Task 1 sentinel stops firing for index subscripts.

**Files:**
- Modify: `interpreter/cobol/data_layout.py` (`_flatten_field`, ~`:432`)
- Test: `tests/unit/test_data_layout.py`, `tests/integration/test_cobol_programs.py`

**Interfaces:**
- Consumes: `CobolField.indexed_by` from Task 4
- Produces: a 4-byte binary `FieldLayout` per index name, in the same layout scope as
  the table; and `DataLayout.index_owner: dict[str, str]` mapping index name → table
  group name, which Task 7 reads to find a Format 1 `SEARCH`'s implicit index

- [x] **Step 1: Write the failing tests**

In `tests/unit/test_data_layout.py`:

```python
def test_indexed_by_allocates_an_index_item():
    """An INDEXED BY name becomes a real 4-byte item, and records its table.

    It holds an occurrence NUMBER, not an IBM byte displacement. Nothing reads the
    raw bytes, and the difference is unobservable unless a program REDEFINES an
    index or group-MOVEs one, both of which are illegal COBOL.
    """
    fields = [
        CobolField.from_dict(
            {
                "name": "TBL",
                "level": 1,
                "picture": "",
                "usage": "DISPLAY",
                "offset": 0,
                "children": [
                    {
                        "name": "TBL-ROW",
                        "level": 5,
                        "picture": "",
                        "usage": "DISPLAY",
                        "offset": 0,
                        "occurs": 3,
                        "indexed_by": ["TBL-IX"],
                        "children": [
                            {
                                "name": "TBL-KEY",
                                "level": 10,
                                "picture": "X(3)",
                                "usage": "DISPLAY",
                                "offset": 0,
                            }
                        ],
                    }
                ],
            }
        )
    ]
    layout = build_data_layout(fields)
    assert layout.lookup("TBL-IX") is not None
    assert layout.lookup("TBL-IX").byte_length == 4
    assert layout.index_owner["TBL-IX"] == "TBL-ROW"
```

`build_data_layout` and `DataLayout.lookup(name) -> FieldLayout | None` are the real
names — `tests/unit/test_data_layout.py` already imports `build_data_layout` from
`interpreter.cobol.data_layout`, so add the test to that file and reuse its imports.
Note `lookup` raises on an ambiguous bare name; `exists(name)` is the non-raising
existence check if you need one.

And in `tests/integration/test_cobol_programs.py`:

```python
class TestIndexItemAllocation:
    def test_index_subscript_resolves(self):
        """MSG-KEY (MSG-IX) must read the table, not a sentinel."""
        vm = _run_cobol(
            [
                "IDENTIFICATION DIVISION.",
                "PROGRAM-ID. TEST-IDX-SUB.",
                "DATA DIVISION.",
                "WORKING-STORAGE SECTION.",
                "01 MSG-BYTES.",
                "   05 FILLER PIC X(4) VALUE 'E401'.",
                "   05 FILLER PIC X(4) VALUE 'E408'.",
                "01 MSG-TAB REDEFINES MSG-BYTES.",
                "   05 MSG-ROW OCCURS 2 TIMES INDEXED BY MSG-IX.",
                "      10 MSG-KEY PIC X(4).",
                "01 OUT-KEY PIC X(4) VALUE SPACES.",
                "PROCEDURE DIVISION.",
                "MAIN-PARA.",
                "    SET MSG-IX TO 2.",
                "    MOVE MSG-KEY (MSG-IX) TO OUT-KEY.",
                "    STOP RUN.",
            ],
            max_steps=2000,
        )
        region = _first_region(vm)
        assert _decode_alpha(region, 8, 4) == "E408"
```

- [x] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/unit/test_data_layout.py -k indexed_by -v
uv run pytest tests/integration/test_cobol_programs.py::TestIndexItemAllocation -v
```

Expected: FAIL — no `TBL-IX` in the layout; `OUT-KEY` is spaces or a sentinel.

- [x] **Step 3: Allocate in `_flatten_field`**

In `data_layout.py`, where a group's children are flattened, after the group's own
extent is computed, add an index item per name into the *sibling* scope (indexes are
not inside the table — they are separate storage the table merely names):

```python
    # OCCURS ... INDEXED BY declares compiler-allocated index items. They live
    # outside the table's own bytes: an index is not an occurrence of anything,
    # it selects one. Four bytes each, holding an occurrence NUMBER (1-based) —
    # IBM stores a byte displacement, but nothing here reads the raw bytes, and
    # a program cannot legally observe the difference (REDEFINES of an index and
    # group MOVE of one are both errors).
    for index_name in cobol_field.indexed_by:
        sibling_fields[index_name] = FieldLayout(
            name=index_name,
            type_descriptor=CobolTypeDescriptor(
                category=CobolDataCategory.BINARY, total_digits=9
            ),
            offset=_allocate_index_offset(),
            byte_length=4,
            occurs_count=0,
        )
```

The offset must come from the same allocator the surrounding scope uses — read how
`_flatten_field` assigns offsets to ordinary siblings and use that, appending after
the last placed sibling. Do **not** overlay the table.

Record ownership on the `DataLayout` that holds the table:

```python
        # index name -> the OCCURS group it indexes. A Format 1 SEARCH names only
        # the table, so this is how the implicit index is found (see lower_search).
        index_owner: dict[str, str] = field(default_factory=dict)
```

- [x] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_data_layout.py -k indexed_by -v
uv run pytest tests/integration/test_cobol_programs.py::TestIndexItemAllocation -v
uv run pytest tests/unit -q -p no:randomly
```

Expected: all PASS. The `WARNING ... SET target MSG-IX not found in layout` from the
spec's reproduction should no longer appear.

- [x] **Step 5: Commit**

```bash
uv run black interpreter/cobol/data_layout.py tests/unit/test_data_layout.py \
              tests/integration/test_cobol_programs.py
git add interpreter/cobol/data_layout.py tests/unit/test_data_layout.py \
        tests/integration/test_cobol_programs.py
git commit -m "feat(cobol): allocate an index item per INDEXED BY name"
```

---

### Task 6: `SEARCH` bounds on the real `OCCURS` count

Defects C2 and C3. Independent of Tasks 3–5 — do it in either order. Fixes both the
false hit past the end of a short table and the blind spot above 256.

**Files:**
- Modify: `interpreter/cobol/lower_search.py:37` and the loop bound at `:44`
- Test: `tests/integration/test_cobol_programs.py`

**Interfaces:**
- Consumes: `SearchStatement.table`; `DataLayout` occurrence counts
- Produces: no new names

- [x] **Step 1: Write the failing tests**

```python
class TestSearchBounds:
    def test_short_table_ends_at_its_own_length(self):
        """A 3-occurrence table must not be walked to 256."""
        vm = _run_cobol(
            [
                "IDENTIFICATION DIVISION.",
                "PROGRAM-ID. TEST-SHORT-TBL.",
                "DATA DIVISION.",
                "WORKING-STORAGE SECTION.",
                "01 TBL-BYTES.",
                "   05 FILLER PIC X(3) VALUE 'K01'.",
                "   05 FILLER PIC X(3) VALUE 'K02'.",
                "   05 FILLER PIC X(3) VALUE 'K03'.",
                "01 TBL REDEFINES TBL-BYTES.",
                "   05 TBL-ROW OCCURS 3 TIMES.",
                "      10 TBL-KEY PIC X(3).",
                "77 WS-SUB PIC 9(4) VALUE 1.",
                "PROCEDURE DIVISION.",
                "MAIN-PARA.",
                "    MOVE 1 TO WS-SUB.",
                "    SEARCH TBL-ROW VARYING WS-SUB",
                "        AT END CONTINUE",
                "        WHEN TBL-KEY (WS-SUB) = 'ZZZ' CONTINUE",
                "    END-SEARCH.",
                "    STOP RUN.",
            ],
            max_steps=5000,
        )
        region = _first_region(vm)
        # AT END must fire just past the last occurrence, not at 257.
        assert _decode_zoned_unsigned(region, 9, 4) == 4

    def test_table_larger_than_256_is_fully_searched(self):
        vm = _run_cobol(
            [
                "IDENTIFICATION DIVISION.",
                "PROGRAM-ID. TEST-BIG-TBL.",
                "DATA DIVISION.",
                "WORKING-STORAGE SECTION.",
                "01 BIG-BYTES PIC X(1500).",
                "01 BIG REDEFINES BIG-BYTES.",
                "   05 BIG-ROW OCCURS 300 TIMES.",
                "      10 BIG-CELL PIC X(5).",
                "77 WS-N PIC 9(4) VALUE 0.",
                "PROCEDURE DIVISION.",
                "MAIN-PARA.",
                "    MOVE 1 TO WS-N.",
                "    SEARCH BIG-ROW VARYING WS-N",
                "        AT END CONTINUE",
                "        WHEN BIG-CELL (WS-N) = 'NEVER' CONTINUE",
                "    END-SEARCH.",
                "    STOP RUN.",
            ],
            max_steps=20000,
        )
        region = _first_region(vm)
        assert _decode_zoned_unsigned(region, 1500, 4) == 301
```

- [x] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/integration/test_cobol_programs.py::TestSearchBounds -v
```

Expected: FAIL with 257 in both — exactly the spec's observed `G-AT-END-AT-SUB=257`
and `F-AT-END-AT-N=257`.

- [x] **Step 3: Derive the bound from the table**

In `lower_search.py`, replace `max_iterations = 256` with a lookup of `stmt.table`:

```python
    # Real SEARCH terminates when the index passes the table's occurrence count,
    # and only then runs AT END. The old hard-coded 256 was wrong in both
    # directions: a shorter table was subscripted past its end into adjacent
    # storage (a WHEN could match whatever followed it), and a longer one had its
    # occurrences beyond 256 silently unreachable with AT END reporting
    # not-found. The corpus has 45 OCCURS clauses above 256.
    occurs = _table_occurrence_count(ctx, stmt.table, materialised)
    if occurs is None:
        logger.warning(
            "SEARCH table %r not found in layout — falling back to the runaway "
            "guard; the loop bound is not the table's own length",
            stmt.table,
        )
        occurs = _RUNAWAY_GUARD
    max_iterations = occurs
```

with, at module level:

```python
# Only a runaway guard, never the intended terminating condition. If a SEARCH ever
# stops here it means the table could not be resolved, which is logged above.
_RUNAWAY_GUARD = 100_000
```

and a resolver that reads the occurrence count from the materialised layout. Model it
on how `EmitContext.resolve_field_ref` reaches the layout; return `None` when the name
does not resolve rather than guessing.

- [x] **Step 4: Run tests**

```bash
uv run pytest tests/integration/test_cobol_programs.py::TestSearchBounds -v
uv run pytest tests/unit -q -p no:randomly
uv run pytest tests/integration/test_cobol_programs.py::TestSearchStatement -v
```

Expected: new tests PASS. `TestSearchStatement`'s two existing tests search a scalar
`77` item with no `OCCURS` — they will hit the `None` branch and the runaway guard.
That is correct behaviour for a nonsense "table", and they should still pass; if they
do not, read them before changing anything.

- [x] **Step 5: Commit**

```bash
uv run black interpreter/cobol/lower_search.py tests/integration/test_cobol_programs.py
git add interpreter/cobol/lower_search.py tests/integration/test_cobol_programs.py
git commit -m "fix(cobol): bound SEARCH by the table's OCCURS count"
```

---

### Task 7: Format 1 `SEARCH` advances the table's implicit index

Defect C1. **Requires Tasks 3–5** — until index items exist there is no implicit index
to advance.

**Files:**
- Modify: `interpreter/cobol/lower_search.py:94` (the `stmt.varying` guard)
- Test: `tests/integration/test_cobol_programs.py`

**Interfaces:**
- Consumes: `DataLayout.index_owner` from Task 5; `stmt.table`
- Produces: no new names

- [x] **Step 1: Write the failing test — the spec's own reproduction**

```python
class TestSearchImplicitIndex:
    def test_plain_search_advances_the_tables_index(self):
        """SEARCH tbl with no VARYING advances the table's first INDEXED BY index.

        This is the overwhelmingly common form and the shape of the observed
        production failure: the WHEN matched entry 1 regardless of contents.
        """
        vm = _run_cobol(
            [
                "IDENTIFICATION DIVISION.",
                "PROGRAM-ID. TEST-IMPLICIT-IX.",
                "DATA DIVISION.",
                "WORKING-STORAGE SECTION.",
                "01 MSG-BYTES.",
                "   05 FILLER PIC X(14) VALUE 'E401MSG-FOR-401'.",
                "   05 FILLER PIC X(14) VALUE 'E408MSG-FOR-408'.",
                "   05 FILLER PIC X(14) VALUE 'E409MSG-FOR-409'.",
                "01 MSG-TAB REDEFINES MSG-BYTES.",
                "   05 MSG-ROW OCCURS 3 TIMES INDEXED BY MSG-IX.",
                "      10 MSG-KEY PIC X(4).",
                "      10 MSG-TEXT PIC X(10).",
                "01 IN-CODE PIC X(4) VALUE 'E408'.",
                "01 OUT-TEXT PIC X(10) VALUE SPACES.",
                "PROCEDURE DIVISION.",
                "MAIN-PARA.",
                "    SET MSG-IX TO 1.",
                "    SEARCH MSG-ROW",
                "        AT END MOVE 'NOTFOUND  ' TO OUT-TEXT",
                "        WHEN MSG-KEY (MSG-IX) = IN-CODE",
                "            MOVE MSG-TEXT (MSG-IX) TO OUT-TEXT",
                "    END-SEARCH.",
                "    STOP RUN.",
            ],
            max_steps=5000,
        )
        region = _first_region(vm)
        # Assert the DATA, not that some branch ran: the old defect reported a hit
        # on entry 1 while leaving the target untouched.
        assert _decode_alpha(region, 46, 10) == "MSG-FOR-40"

    def test_plain_search_reaches_at_end_on_a_genuine_miss(self):
        vm = _run_cobol(
            [
                "IDENTIFICATION DIVISION.",
                "PROGRAM-ID. TEST-IMPLICIT-MISS.",
                "DATA DIVISION.",
                "WORKING-STORAGE SECTION.",
                "01 MSG-BYTES.",
                "   05 FILLER PIC X(14) VALUE 'E401MSG-FOR-401'.",
                "   05 FILLER PIC X(14) VALUE 'E408MSG-FOR-408'.",
                "01 MSG-TAB REDEFINES MSG-BYTES.",
                "   05 MSG-ROW OCCURS 2 TIMES INDEXED BY MSG-IX.",
                "      10 MSG-KEY PIC X(4).",
                "      10 MSG-TEXT PIC X(10).",
                "01 IN-CODE PIC X(4) VALUE 'E999'.",
                "01 OUT-TEXT PIC X(10) VALUE SPACES.",
                "PROCEDURE DIVISION.",
                "MAIN-PARA.",
                "    SET MSG-IX TO 1.",
                "    SEARCH MSG-ROW",
                "        AT END MOVE 'NOTFOUND  ' TO OUT-TEXT",
                "        WHEN MSG-KEY (MSG-IX) = IN-CODE",
                "            MOVE MSG-TEXT (MSG-IX) TO OUT-TEXT",
                "    END-SEARCH.",
                "    STOP RUN.",
            ],
            max_steps=5000,
        )
        region = _first_region(vm)
        assert _decode_alpha(region, 32, 10) == "NOTFOUND  "
```

- [x] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/integration/test_cobol_programs.py::TestSearchImplicitIndex -v
```

Expected: FAIL — the first asserts spaces (the false-hit-writes-nothing symptom); the
second may spuriously "hit" entry 1.

- [x] **Step 3: Advance the implicit index**

In `lower_search.py`, replace the `if stmt.varying and ctx.has_field(...)` guard with a
resolution that falls back to the table's first index:

```python
    # Format 1 SEARCH names only the table and advances its FIRST INDEXED BY
    # index. That form is the common one; the explicit VARYING operand is not.
    # Until index items were allocated there was nothing to advance, so the loop
    # re-tested occurrence 1 until the bound.
    advance_name = stmt.varying or _implicit_index_for(ctx, stmt.table, materialised)
    if advance_name and ctx.has_field(advance_name, materialised):
        # ... existing increment body, using advance_name in place of stmt.varying
    else:
        logger.warning(
            "SEARCH over %r has no index to advance (no VARYING, and the table "
            "declares no INDEXED BY) — the loop cannot progress",
            stmt.table,
        )
```

`_implicit_index_for` reads `DataLayout.index_owner` (Task 5) in reverse: find the
first index name whose owner is `stmt.table`. Return `None` when there is none.

- [x] **Step 4: Run tests, including the spec's full reproduction**

```bash
uv run pytest tests/integration/test_cobol_programs.py::TestSearchImplicitIndex -v
uv run pytest tests/integration/test_cobol_programs.py -k Search -v
uv run pytest tests/unit -q -p no:randomly
```

Expected: all PASS.

- [x] **Step 5: Run the spec's SRCHPROBE end to end**

Paste the spec's `SRCHPROBE` program (§ Defect B, Reproduction) through the probe
harness. Expected, versus the spec's recorded output:

- `C-IDX-KEY=` is `E401` (was a `SymbolicValue`)
- `B-WHEN-HIT` still appears, but `B-OUT-TEXT=MSG-FOR-40` is now non-empty
- no `SET target MSG-IX not found in layout` warning

- [x] **Step 6: Commit**

```bash
uv run black interpreter/cobol/lower_search.py tests/integration/test_cobol_programs.py
git add interpreter/cobol/lower_search.py tests/integration/test_cobol_programs.py
git commit -m "fix(cobol): advance the table's implicit index in a Format 1 SEARCH"
```

---

### Task 8: Push red-dragon and bump the forge pointer

**Files:**
- Modify: `vendor/red-dragon` pointer in `~/code/red-dragon-forge`

- [x] **Step 1: Run red-dragon's full suite**

```bash
cd ~/code/red-dragon
uv run pytest tests/unit -q -p no:randomly
cd proleap-bridge && mvn -q -B test && cd ..
```

Expected: green.

- [x] **Step 2: Push**

```bash
cd ~/code/red-dragon && git push origin main
```

- [x] **Step 3: Bump the pointer and rebuild the JAR**

```bash
cd ~/code/red-dragon-forge/vendor/red-dragon
git fetch origin && git checkout main && git pull --ff-only origin main
cd proleap-bridge && ./build.sh && cd ../../..
```

- [x] **Step 4: Run the consuming suites**

```bash
cd ~/code/red-dragon-forge
export PROLEAP_BRIDGE_JAR=$PWD/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
export JCL_BRIDGE_JAR=$PWD/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
cd squall && . db2/dsn-env.sh && cd ..
make test
cd cicada && make test && cd ..
```

Expected: green. If Db2 refuses the connection, `cd squall && make db2-restart` — the
container's TCP listener drops under emulation.

- [x] **Step 5: Commit the bump**

```bash
git add vendor/red-dragon
git commit -m "chore: bump vendor/red-dragon (index items, SEARCH bounds, SET from field)"
git push origin main
```

---

## Verification of the whole plan

The single acceptance test is the spec's own opening claim: a program whose error path
is `SET ix TO 1` / `SEARCH tbl` / `WHEN key(ix) = code` must either move the matching
message text or take `AT END`. It must not report a hit and leave the target blank.

Task 7's `test_plain_search_advances_the_tables_index` is exactly that program, and it
asserts the resulting **data** rather than that a branch ran — which is the specific
weakness that let the original defect through the existing `SEARCH` tests.
