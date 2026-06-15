# dclgen / data_layout Category Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fail loud when a dclgen sidecar's COBOL `category` disagrees with ProLeap's parsed `data_layout` category for the same host var (copybook/schema drift), instead of silently mis-binding. (squall-aim.)

**Architecture:** A pure validator `validate_field_meta(data_layout, field_meta)` in `squall/binding.py` raises `FieldMetaMismatch` on any disagreement; for VARCHAR it checks the 49-group children (`len_var` is BINARY, `text_var` is ALPHANUMERIC), for scalars it checks `data_layout[name].category == meta["category"]`. The `__exec_sql` builtin runs it **once**, on its first invocation (the earliest point `vm.data_layout` is populated), guarded by a `nonlocal` flag.

**Tech Stack:** Python; `squall/binding.py`, `squall/builtins/exec_sql.py`; pytest; `python_fp_lint` + `pyright` + `black`.

**Established facts (verified against the code):**
- The dclgen sidecar carries `category` ∈ {`COMP3`, `ALPHANUMERIC`, `BINARY`, `VARCHAR`} plus `len_var`/`text_var` for VARCHAR (`squall/dclgen.py:78-160`); `sql_type` is informational and has no `data_layout` counterpart, so the check is **category-vs-category**, not against `sql_type`.
- ProLeap's `data_layout[name]["category"]` uses the **same** vocabulary — empirically: `test_include_dclgen` decodes `ACCT-BAL` as `COMP3` and `ACCT-ID` as `BINARY`, which `binding._decode_field` only does when `data_layout[...]["category"]` is literally `"COMP3"`/`"BINARY"`. So validation is additive (no current program mismatches).
- `binding._require_field(data_layout, name)` already raises `KeyError` when a field is absent — a missing dclgen host var in `data_layout` is itself the drift we want, so that raise doubles as part of the check.
- Inline ZONED fields (e.g. `WS-ID PIC 9(4)`) have **no** sidecar, so `field_meta` is empty for them and they are never validated (no false positives).
- The builtin closure (`make_exec_sql_builtin`) already closes over `ctx`/`plans`/`field_meta`; `vm.data_layout` is set before the first call (`run_cobol` pre-populates `initial_vm.data_layout`; the unit-test `_FakeVM` sets it in its constructor with `field_meta == {}`).

---

## File Structure

- **Modify** `squall/binding.py` — add `FieldMetaMismatch` exception + `validate_field_meta` (and a small `_require_category` helper). Pure; no new imports beyond what's present.
- **Modify** `squall/builtins/exec_sql.py` — call `validate_field_meta` once on first `__exec_sql` invocation via a `nonlocal` flag.
- **Create** `tests/unit/test_field_meta_validation.py` — unit tests for the validator and the one-shot builtin hook.

---

## Task 1: Pure `validate_field_meta` + `FieldMetaMismatch`

**Files:**
- Modify: `squall/binding.py`
- Test: `tests/unit/test_field_meta_validation.py`

- [ ] **Step 1: Write the failing test** — create `tests/unit/test_field_meta_validation.py`:

```python
"""
tests/unit/test_field_meta_validation.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
dclgen/data_layout category agreement (squall-aim): a host var carrying dclgen
field_meta must match ProLeap's parsed data_layout category, else fail loud.
"""

from __future__ import annotations

import pytest

from squall.binding import FieldMetaMismatch, validate_field_meta


def _scalar_layout() -> dict:
    return {
        "ACCT-ID": {"offset": 0, "length": 4, "category": "BINARY"},
        "ACCT-BAL": {"offset": 4, "length": 4, "category": "COMP3"},
        "ACCT-NAME": {"offset": 8, "length": 20, "category": "ALPHANUMERIC"},
    }


def _varchar_layout() -> dict:
    return {
        "EMP-NAME": {"offset": 0, "length": 11, "category": "ALPHANUMERIC"},
        "EMP-NAME-LEN": {"offset": 0, "length": 2, "category": "BINARY"},
        "EMP-NAME-TEXT": {"offset": 2, "length": 9, "category": "ALPHANUMERIC"},
    }


def test_scalar_categories_agree_does_not_raise():
    field_meta = {
        "ACCT-ID": {"category": "BINARY"},
        "ACCT-BAL": {"category": "COMP3"},
        "ACCT-NAME": {"category": "ALPHANUMERIC"},
    }
    validate_field_meta(_scalar_layout(), field_meta)  # no raise


def test_scalar_category_mismatch_raises():
    field_meta = {"ACCT-BAL": {"category": "BINARY"}}  # layout says COMP3
    with pytest.raises(FieldMetaMismatch):
        validate_field_meta(_scalar_layout(), field_meta)


def test_varchar_children_agree_does_not_raise():
    field_meta = {
        "EMP-NAME": {
            "category": "VARCHAR",
            "len_var": "EMP-NAME-LEN",
            "text_var": "EMP-NAME-TEXT",
        }
    }
    validate_field_meta(_varchar_layout(), field_meta)  # no raise


def test_varchar_len_child_not_binary_raises():
    layout = _varchar_layout()
    layout["EMP-NAME-LEN"]["category"] = "ALPHANUMERIC"  # should be BINARY
    field_meta = {
        "EMP-NAME": {
            "category": "VARCHAR",
            "len_var": "EMP-NAME-LEN",
            "text_var": "EMP-NAME-TEXT",
        }
    }
    with pytest.raises(FieldMetaMismatch):
        validate_field_meta(layout, field_meta)


def test_field_absent_from_layout_raises_keyerror():
    field_meta = {"GHOST": {"category": "BINARY"}}
    with pytest.raises(KeyError):
        validate_field_meta(_scalar_layout(), field_meta)


def test_empty_field_meta_is_noop():
    validate_field_meta(_scalar_layout(), {})  # no raise
```

- [ ] **Step 2: Run it to verify it fails** — `uv run python -m pytest tests/unit/test_field_meta_validation.py -q`. Expected: FAIL — `ImportError: cannot import name 'FieldMetaMismatch'`.

- [ ] **Step 3: Implement** — in `squall/binding.py`, add the exception and validator. Place the exception near `_require_field` (the other fail-loud layout check) and the validator just below it:

```python
class FieldMetaMismatch(Exception):
    """A dclgen sidecar's category disagrees with ProLeap's parsed data_layout —
    copybook/schema drift. Raised loud (not an SQLCODE): a generation/layout bug,
    not a runtime SQL condition."""

    def __init__(self, name: str, expected, actual) -> None:
        super().__init__(
            f"dclgen/copybook drift for {name!r}: dclgen category {expected!r} "
            f"but data_layout category {actual!r}"
        )


def _require_category(data_layout, name: str, expected: str) -> None:
    """Assert ``data_layout[name].category == expected``; raise loud otherwise.

    A missing field raises KeyError via _require_field — itself a drift signal.
    """
    actual = _require_field(data_layout, name).get("category")
    if actual != expected:
        raise FieldMetaMismatch(name, expected, actual)


def validate_field_meta(
    data_layout, field_meta: Mapping[str, FieldMeta]
) -> None:
    """Fail loud if any dclgen field_meta category disagrees with data_layout.

    Scalars: data_layout[name].category must equal the dclgen category. VARCHAR:
    the data_layout cannot mark the 49-group, so the children are checked instead
    (len_var is BINARY, text_var is ALPHANUMERIC). Empty field_meta is a no-op.
    """
    for name, meta in field_meta.items():
        category = meta.get("category")
        if category == "VARCHAR":
            _require_category(data_layout, meta["len_var"], "BINARY")
            _require_category(data_layout, meta["text_var"], "ALPHANUMERIC")
        else:
            _require_category(data_layout, name, category)
```

- [ ] **Step 4: Run to verify it passes** — `uv run python -m pytest tests/unit/test_field_meta_validation.py -q`. Expected: PASS (6 passed).

- [ ] **Step 5: Lint** — `uv run python -m python_fp_lint check squall/binding.py` (no new violations).

- [ ] **Step 6: Commit**

```bash
git add squall/binding.py tests/unit/test_field_meta_validation.py
git commit -m "feat(sql): validate_field_meta — fail loud on dclgen/data_layout category drift"
```

---

## Task 2: Run the validation once on first builtin invocation

**Files:**
- Modify: `squall/builtins/exec_sql.py`
- Test: `tests/unit/test_field_meta_validation.py` (append)

- [ ] **Step 1: Write the failing test** — append (drives the builtin hook with a fake VM + mismatched field_meta):

```python
from interpreter.address import Address
from interpreter.var_name import VarName

from squall.builtins.exec_sql import make_exec_sql_builtin
from squall.parser.parse import parse_exec_sql


class _Addr:
    def __init__(self, value: str):
        self.value = value


class _Frame:
    def __init__(self, addr: str):
        self.local_vars = {VarName("__ws_region"): _Addr(addr)}


class _VM:
    def __init__(self, layout: dict, addr: str = "1"):
        self._region = bytearray(64)
        self.data_layout = layout
        self._addr = Address(addr)
        self.call_stack = [_Frame(addr)]

    def region_get(self, addr):
        assert isinstance(addr, Address)
        return self._region if addr == self._addr else None


class _TV:
    def __init__(self, value: object):
        self.value = value


def _commit_builtin(field_meta):
    """A builtin over an empty registry; the plan is a COMMIT (no backend needed
    to reach the one-shot validation, which runs before dispatch)."""
    plans = [parse_exec_sql("EXEC SQL COMMIT END-EXEC")]
    return make_exec_sql_builtin({}, plans, field_meta), plans


def test_builtin_validates_field_meta_on_first_call():
    vm = _VM({"ACCT-BAL": {"offset": 0, "length": 4, "category": "COMP3"}})
    builtin, _ = _commit_builtin({"ACCT-BAL": {"category": "BINARY"}})  # mismatch
    with pytest.raises(FieldMetaMismatch):
        builtin([_TV(0)], vm)
```

- [ ] **Step 2: Run it to verify it fails** — `uv run python -m pytest tests/unit/test_field_meta_validation.py::test_builtin_validates_field_meta_on_first_call -q`. Expected: FAIL — no exception raised (the builtin does not yet validate; COMMIT on a disconnected run currently just writes SQLCODE -1024).

- [ ] **Step 3: Implement the one-shot hook** — in `squall/builtins/exec_sql.py`, import the validator and call it once. Update the import:

```python
from squall.binding import (
    read_params,
    validate_field_meta,
    write_outputs,
    write_sqlcode,
)
```

Then in `make_exec_sql_builtin`, add a `nonlocal` one-shot guard around the validation, before dispatch:

```python
    ctx = _Ctx(
        connections=connections,
        conn=_ConnState(current=None),
        cursors={},
        field_meta=field_meta,
    )
    validated = False

    def __exec_sql(args: list, vm: object) -> BuiltinResult:
        nonlocal validated
        from interpreter.vm.vm_types import BuiltinResult

        if not validated:
            # First call: data_layout is now populated. Fail loud on any
            # dclgen/copybook category drift before binding anything.
            validate_field_meta(vm.data_layout, field_meta)
            validated = True

        parsed = plans[int(args[0].value)]
        _HANDLERS.get(parsed.kind, _h_query)(ctx, parsed, vm)
        return BuiltinResult(value=None)

    return __exec_sql
```

(`read_params` already imports cleanly; adding `validate_field_meta` to the same `from squall.binding import …` keeps imports sorted.)

- [ ] **Step 4: Run to verify it passes** — `uv run python -m pytest tests/unit/test_field_meta_validation.py -q`. Expected: PASS (7 passed).

- [ ] **Step 5: Full unit suite** — `uv run python -m pytest tests/unit/ -q` (with `PROLEAP_BRIDGE_JAR` + `SQUALL_DB2_DSN` set). Expected: PASS — the existing dclgen unit/builtin tests prove no real mismatch (their `field_meta` validates clean; empty `field_meta` is a no-op).

- [ ] **Step 6: Commit**

```bash
git add squall/builtins/exec_sql.py tests/unit/test_field_meta_validation.py
git commit -m "feat(sql): __exec_sql validates dclgen/data_layout categories once on first call"
```

---

## Task 3: Full regression, lint, close bead

**Files:** none (verification).

- [ ] **Step 1: Format** — `uv run python -m black squall/ tests/`.

- [ ] **Step 2: Full suite** (env set: `PROLEAP_BRIDGE_JAR`, `SQUALL_DB2_DSN`, `SQUALL_DB2_DSN2`):
```bash
uv run python -m pytest tests/ -q
```
Expected: all green (the DCLGEN COMP-3 e2e + VARCHAR e2e exercise the one-shot validation on real ProLeap `data_layout` and must pass — proving the vocabularies agree end-to-end).

- [ ] **Step 3: Lint** — `uv run python -m python_fp_lint check squall/binding.py squall/builtins/exec_sql.py` (no new violations); `uv run pyright squall/binding.py squall/builtins/exec_sql.py` (no new non-import errors).

- [ ] **Step 4: Close the bead**

```bash
bd close squall-aim --reason "validate_field_meta fails loud (FieldMetaMismatch) when a dclgen sidecar's COBOL category disagrees with ProLeap's data_layout: scalars by category equality, VARCHAR by its 49-group children (len_var BINARY, text_var ALPHANUMERIC); a host var missing from data_layout raises via _require_field. Run once on the first __exec_sql call (earliest data_layout is populated). Additive — the COMP-3/VARCHAR e2e prove the vocabularies already agree; empty field_meta is a no-op."
```

---

## Notes for the implementer

- **Category-vs-category, not sql_type.** The bead title says "sql_type" but `data_layout` has no SQL type to compare; the real invariant is the COBOL `category` on both sides.
- **Fail loud, not an SQLCODE.** Drift is a build/generation bug (like `_require_field`'s `KeyError`), so it raises an exception — it must not be swallowed into an SQLCODE.
- **One-shot via `nonlocal`, not per-bind.** Validate all of `field_meta` once on the first call (cheap, catches drift in unused fields too); a `nonlocal` bool is cleaner than re-validating inside every PERFORM-loop pass and adds no shared mutable state beyond the builtin's own closure.
- **Do not** widen scope to validate `data_layout` fields that carry no sidecar (inline ZONED host vars) — only `field_meta` entries are dclgen-generated and in scope.
