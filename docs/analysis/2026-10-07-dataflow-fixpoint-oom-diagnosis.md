# Dataflow Fixpoint OOM & Non-Convergence Diagnosis

**Date:** 2026-10-07
**Component:** `cobble-dataflow-fixpoint` (cobble/cobble/dataflow/fixpoint/)
**Symptom:** Workers consume 3+ GB RAM each, never converge on large CICS online programs, ultimately OOM with 4 workers (~12+ GB peak).

---

## 1. Observed Behaviour

The worklist fixpoint exhibits pathological revisiting on large CICS online programs. Representative log extract for a ~4300-node program:

```
fields:   PROG_A 306000 dequeues, 3167/4310 nodes reached, 62 queued, ~0m left
fields:   PROG_A 400000 dequeues, 3801/4310 nodes reached, 92 queued, queue not draining
```

| Program   | CFG Nodes | Dequeues | Ratio  | Status          |
|-----------|-----------|----------|--------|-----------------|
| PROG_A    | 4,310     | 400,000+ | **92x** | Not converging |
| PROG_B    | 3,674     | 228,000  | **62x** | Slow           |
| PROG_C    | 3,873     | 154,000  | **39x** | Slow           |
| PROG_D    | 2,777     | 8,000    | 2x     | Early stage    |

Cap is `ITERATION_FACTOR * num_nodes` = `150 * 4310` = **646,500** dequeues (options.py:11). PROG_A would hit this, burn through ~3 GB, and OOM before the other workers finish.

Program sizes after copybook expansion: 8,000–14,000 effective lines, 120–270 PERFORM statements, 13–39 COPY directives. Large but not extraordinary. The problem is algorithmic, not data size.

---

## 2. Architecture Summary

### Worklist Algorithm (fixpoint.py:401–463)

Reverse-postorder priority worklist. Each step:
1. Dequeue earliest RPO-position node (`_step`, line 410)
2. Compute transfer function for that node's statement (`_after`, line 329–333)
3. Join exit state into each successor's entry state (`_grown`, line 346–358)
4. Re-enqueue any successor whose state grew (line 416)

Termination check (line 431–432): queue empty or `dequeues >= cap`.

### Lattice (state.py:99–118)

```python
@dataclass(frozen=True, slots=True)
class State:
    sources: Mapping[FieldExtent, frozenset[Source]]  # provenance
    values:  Mapping[FieldExtent, ValueSet]            # concrete values
```

- `sources`: maps each extent to the set of `Source` objects that may have written it
- `values`: maps each extent to a `ValueSet` (concrete literal bytes + reason flags)
- Join is set union for sources (state.py:129–154), value merge for values (state.py:207–253)

### Transfer (transfer.py:518–539, 553+)

Dispatches by statement kind: `MoveStatement`, `InitializeStatement`, `ArithmeticStatement`, `ComputeStatement`, `StringStatement`, `ReadStatement`, `CallStatement`, `ExecCicsStatement`.

Unrecognised verbs and EXEC CICS statements produce `UnmodelledWrite` objects, which use `weak=True` writes.

---

## 3. Root Cause #1: Non-Convergence (Lattice Height Explosion)

The fixpoint docstring (line 30–37) correctly notes the lattice is finite:

> "every extent a transfer can construct is fixed by the statement set before iteration begins, so the lattice has finite height and join is monotone"

However, the practical height is `O(nodes × extents × distinct_sources)`. For large CICS online programs this product is enormous, driven by two mechanisms that prevent source-set shrinkage:

### 3a. `weak_write` Never Kills (state.py:499–528)

```python
def weak_write(state, target, sources, doubt):
    """sources may reach target, which may or may not have changed.
    Nothing is killed: the write may leave the target as it was..."""
    return State(
        sources=MappingProxyType(
            {**state.sources, target: state.sources.get(target, frozenset()) | sources}
        ),
        ...
    )
```

Every `UnmodelledWrite` (including all EXEC CICS statements) calls `weak_write`. This **only adds** sources to the target extent — never removes any. A CICS LINK inside a loop adds one new Source per back-edge traversal. The source set at COMMAREA extents grows monotonically, one Source per worklist cycle through the loop.

The affected programs have 85+ `EXEC CICS` / `CALL` sites and 5 large COMMAREA copybooks (hundreds of extent entries each). Each CICS call site contributes a distinct Source to each COMMAREA extent, and loop back-edges propagate these sources to nodes that feed back into the loop entry, creating an ever-growing join.

### 3b. CLAMPED Extents Cannot Kill (field_extent.py:84–91, state.py:465–496)

```python
def must_cover(self, other):
    ...
    if self.precision is not Precision.EXACT:
        return False       # <-- CLAMPED can never kill
    ...
```

A computed-subscript MOVE produces a CLAMPED extent (extent.py:302–313). CLAMPED extents span all occurrences of a table entry. In `write()` (state.py:465–496), the kill step filters with `must_cover`:

```python
kept_sources = {
    extent: held
    for extent, held in _split(target, state.sources, ...).items()
    if not target.must_cover(extent)    # <-- CLAMPED target: always True, nothing killed
}
```

Three-quarters of the corpus's subscripted MOVE operands have computed subscripts (extent.py:5–6), so CLAMPED is the common case. These writes add sources but never remove any — same accumulation pattern as `weak_write`.

### Combined Effect

A loop body with CICS LINKs and computed-subscript MOVEs targeting COMMAREA fields produces this cycle:

1. Node N executes CICS LINK → `weak_write` adds `Source(node=N)` to COMMAREA extents
2. Loop back-edge carries enlarged state to loop header
3. Loop header joins old state (small source set) with new state (one more Source)
4. State grew → re-enqueue all successors
5. Successors re-compute, propagate enlarged state forward
6. Reach node N again → step 1 with yet another Source (from a different worklist iteration context)

The queue hovers at 55–110 entries because only the ~100 nodes near CICS call sites in loops are being churned. The remaining ~500 unreached nodes sit behind those churning nodes.

---

## 4. Root Cause #2: OOM (Memory Pressure)

### 4a. Immutable Dict Rebuild Per Step (fixpoint.py:414–415)

```python
stepped = _Worklist(
    states=MappingProxyType({**run.states, **grown}),  # copies ALL 3800 entries
    ...
)
```

Every dequeue creates a **new dict** by unpacking all existing states plus the grown ones. At 400K dequeues × ~3800 entries × ~200 bytes per entry overhead = massive allocation churn. While old dicts become GC-eligible, Python's memory allocator fragments badly under this pattern.

### 4b. frozenset Union Allocations (state.py:147–148)

```python
grown = {
    extent: held | prior           # new frozenset per union
    for extent, held in right.items()
    for prior in (left.get(extent, _NO_SOURCE_SET),)
    if (prior is not held and not held <= prior) or ...
}
```

Every join that detects growth creates a new `frozenset` per extent. With 400K+ dequeues, each touching 5–20 successors with 100+ extents per join, that is **millions** of frozenset allocations. Old sets are GC'd but heap fragmentation accumulates.

### 4c. State Object Size

Each `State` with ~400 extents × ~50 Sources/extent:
- `sources` dict: 400 entries × (FieldExtent key + frozenset of 50 Sources) ≈ 200–500 KB
- `values` dict: similar structure, smaller per entry
- Total per State: **500 KB – 1 MB**

With 3800+ reached nodes: **2–4 GB per worker** just for the states mapping.

### 4d. Worker Multiplier (build_corpus.py:1104–1108)

```python
parser.add_argument(
    "--max-workers", type=worker_count, default=4,
    help="worker processes analysing members in parallel (default 4)",
)
```

4 workers at 3+ GB each = 12+ GB peak. If multiple workers hit pathological programs simultaneously, the system OOMs.

---

## 5. Existing Escape Hatch: Sweep Mode

The codebase already has a sweep-based alternative (fixpoint.py:497–558):

```python
def _swept(cfg, statements, index, entry, budget, entry_state):
    """Sweep until nothing grows or the budget is spent..."""
```

**Sweeps mode** runs N reverse-postorder passes instead of the worklist. Cost is `O(N × nodes)` — for 3 sweeps on PROG_A: `3 × 4310 = 12,930` steps vs 400,000+ worklist dequeues.

Invoked via `--sweeps N` (mutually exclusive with `--iteration-factor`). The docstring says 2 sweeps is the useful floor (one sweep loses loop-carried flow).

**Trade-off:** Sweeps produce an under-approximation — every reported edge is real, but some real edges may be missing if the lattice hasn't settled. The `settled` flag in the output says which happened.

---

## 6. Proposed Fixes

### Tier 1: Configuration (No Code Changes)

| Fix | Command | Effect |
|-----|---------|--------|
| Use sweep mode | `--sweeps 3` | Caps work at `3 × nodes` steps. 30x cheaper for PROG_A. |
| Reduce workers | `--max-workers 2` | Halves peak memory. |
| Lower factor | `--iteration-factor 30` | Caps at 30 × nodes = ~130K dequeues. Still may not converge but OOMs later. |

**Recommendation:** `--sweeps 3 --max-workers 2` for immediate relief. Sweep mode was designed for exactly this scenario.

### Tier 2: Source-Set Widening (Code Change — Highest Impact)

Add a per-extent source-set cap. When a frozenset exceeds the cap, collapse to a TOP element representing "too many sources to track precisely."

**Where to implement:** `_joined_sources` in state.py:129–154.

```python
SOURCE_CAP = 64  # configurable

def _joined_sources(left, right):
    ...
    grown = {
        extent: _capped(held | prior)
        for extent, held in right.items()
        ...
    }

def _capped(sources: frozenset[Source]) -> frozenset[Source]:
    if len(sources) <= SOURCE_CAP:
        return sources
    # Collapse: keep one synthetic TOP source
    return frozenset({Source(origin="TOO_MANY_SOURCES", extent=NOWHERE, node="*")})
```

This bounds the lattice height at `O(nodes × extents × SOURCE_CAP)` and guarantees convergence within that budget. Every edge reported is still real (over-approximation is safe).

**Testing approach:** Run the pathological programs with and without the cap. Compare the output edge sets — the capped version should be a superset (more imprecise but no false negatives). Check that smaller programs (which converge today) produce identical output.

### Tier 3: Mutable State Dict (Code Change — Memory)

Replace the immutable `MappingProxyType({**run.states, **grown})` in `_step` (fixpoint.py:414–415) with in-place mutation.

**Current:**
```python
stepped = _Worklist(
    states=MappingProxyType({**run.states, **grown}),
    queue=(run.queue - {earliest}) | {rank[target] for target in grown},
    ...
)
```

**Proposed:**
```python
# In _settled, use a mutable dict and update in-place:
states = dict(start.states)
queue = set(start.queue)

while queue and dequeues < cap:
    earliest = min(queue)
    node_id = order.ordered[earliest]
    after = _after(statements, node_id, states[node_id], index)
    grown = _grown(cfg, node_id, after, states)
    states.update(grown)
    queue.discard(earliest)
    queue.update(rank[target] for target in grown)
    dequeues += 1
```

This eliminates the 400K × O(n) dict copies. The immutability serves no purpose inside `_settled` since nothing reads intermediate states.

**Risk:** The current functional style makes debugging easier (every step is a snapshot). Consider keeping the old path behind a flag for debugging.

### Tier 4: Adaptive Iteration Factor (Code Change — Ergonomics)

Scale the factor inversely with node count so large programs get a proportionally lower budget:

```python
def adaptive_factor(nodes: int, base: int = 150) -> int:
    return min(base, max(10, 50_000 // max(nodes, 1)))
```

For 4310 nodes: `min(150, 50000 // 4310)` = `min(150, 11)` = **11**, giving a cap of ~47K. Smaller programs keep the full 150.

---

## 7. Testing Methodology

### Reproducing the Problem

```bash
# Run fixpoint on a single pathological member with verbose logging
python -m cobble.dataflow.fixpoint.build_corpus \
    --member PROG_A \
    --iteration-factor 150 \
    --max-workers 1 \
    --extents-dir <extents-dir> \
    --out-dir <out-dir>
```

Watch for: dequeues climbing while nodes-reached plateaus, "queue not draining" messages, RSS growing past 2 GB.

### Measuring Memory

```bash
# Track RSS of the worker process
/usr/bin/time -l python -m cobble.dataflow.fixpoint.build_corpus \
    --member PROG_A --max-workers 1 ...
```

Or instrument with `tracemalloc`:
```python
import tracemalloc
tracemalloc.start()
# ... after fixpoint ...
snapshot = tracemalloc.take_snapshot()
for stat in snapshot.statistics('lineno')[:20]:
    print(stat)
```

Expected hot spots: `state.py` (frozenset/dict allocations), `fixpoint.py:414` (dict copy).

### Validating Fixes

1. **Sweep mode baseline:** Run `--sweeps 3` on pathological members. Record edge count, settled status, wall time, peak RSS.
2. **Source-set cap:** Run worklist with `SOURCE_CAP=64` on same members. Compare edge count against sweep baseline — should be a superset. Verify small programs produce identical output to uncapped.
3. **Mutable state dict:** Run worklist on small programs, diff output against immutable version — must be identical. Measure peak RSS reduction on pathological members.
4. **Regression:** Run full corpus with each fix. Compare `member_counts` output against the current baseline for any member that was already converging.

### Key Metrics to Track

| Metric | Where | Current (PROG_A) | Target |
|--------|-------|-------------------|--------|
| Dequeues | heartbeat log | 400K+ (still growing) | <50K or sweep mode |
| Peak RSS per worker | `/usr/bin/time -l` | 3+ GB | <1 GB |
| Wall time per member | log timestamps | 10+ min (hits cap) | <1 min |
| Nodes reached | heartbeat log | 3801/4310 (88%) | 4310/4310 (100%) |
| Edge count | output | N/A (never finished) | Comparable to sweep baseline |

---

## 8. File Reference

| File | Key Lines | Role |
|------|-----------|------|
| `cobble/cobble/dataflow/fixpoint/fixpoint.py` | 401–463 | Worklist step loop, dict copy per step |
| `cobble/cobble/dataflow/fixpoint/fixpoint.py` | 497–558 | Sweep mode (the escape hatch) |
| `cobble/cobble/dataflow/fixpoint/fixpoint.py` | 569 | Cap = factor × nodes |
| `cobble/cobble/dataflow/fixpoint/options.py` | 11, 25–26 | `ITERATION_FACTOR = 150`, `AnalysisOptions` |
| `cobble/cobble/dataflow/fixpoint/build_corpus.py` | 998–999 | `ProcessPoolExecutor(max_workers=4)` |
| `cobble/cobble/dataflow/fixpoint/build_corpus.py` | 1074–1108 | CLI arg definitions for factor, sweeps, workers |
| `cobble/cobble/dataflow/fields/state.py` | 99–118 | `State` dataclass (sources + values lattice) |
| `cobble/cobble/dataflow/fields/state.py` | 129–154 | `_joined_sources` — frozenset union, key growth site |
| `cobble/cobble/dataflow/fields/state.py` | 465–496 | `write()` — strong write, copies sources dict |
| `cobble/cobble/dataflow/fields/state.py` | 499–528 | `weak_write()` — never kills, only accumulates |
| `cobble/cobble/dataflow/fields/transfer.py` | 518–539 | `_unmodelled_writes` — produces `weak=True` for EXEC CICS |
| `cobble/cobble/dataflow/fields/extent.py` | 302–313 | `_clamped()` — computed subscript extent generation |
| `vendor/.../cobol_memory/field_extent.py` | 84–91 | `must_cover()` — CLAMPED returns False, can never kill |

---

## 9. Priority Order

1. **Immediate:** Try `--sweeps 3 --max-workers 2` on the pathological members. This requires zero code changes and the mode already exists. Verify output quality.
2. **If sweep quality is insufficient:** Implement source-set cap (Tier 2). This is the smallest code change with the largest convergence impact.
3. **Regardless:** Implement mutable state dict (Tier 3) to reduce memory pressure for both walk modes.
4. **Nice to have:** Adaptive factor (Tier 4) so the default configuration handles large programs without manual tuning.
