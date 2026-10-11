"""Asserting final state: reading field values back out of either a
rendered screen (SEND MAP output) or a program's own WORKING-STORAGE after
a run.  Agnostic to any one program.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def find_screen(screens: Sequence[dict], map_name: str, *, last: bool = True) -> dict | None:
    """The first (or, by default, last) SEND MAP in ``screens`` whose
    ``map`` matches ``map_name``, or None.  A program can SEND the same map
    more than once in a turn (e.g. re-displaying after a validation
    error); ``last=True`` (the default) gets the final rendering."""
    matches = [s for s in screens if s.get("map") == map_name]
    if not matches:
        return None
    return matches[-1] if last else matches[0]


def screen_field(screens: Sequence[dict], map_name: str, field_name: str, default: str = "") -> str:
    """Convenience: ``find_screen(...).fields[field_name]``, defaulted."""
    screen = find_screen(screens, map_name)
    return (screen or {}).get("fields", {}).get(field_name, default)


def read_vm_field(vm: Any, field_name: str) -> bytes:
    """Raw bytes for ``field_name`` from ``vm``'s own WORKING-STORAGE,
    looked up via ``vm.data_layout`` (must already be set -- true for any
    VMState returned by ``run_linked``/``run_cics``). For inspecting
    program state directly rather than through a rendered screen.

    Raises KeyError if ``field_name`` isn't in the layout, RuntimeError if
    no region is large enough to contain it.
    """
    layout: Mapping[str, dict] | None = getattr(vm, "data_layout", None)
    if layout is None:
        raise RuntimeError("vm.data_layout is not set -- was this VMState produced by run_linked/run_cics?")
    fld = layout.get(field_name)
    if fld is None:
        raise KeyError(f"{field_name!r} not in data_layout: {sorted(layout)[:40]}")
    off, sz = fld["offset"], fld["length"]
    for rk in vm.region_keys():
        rgn = vm.region_get(rk)
        if rgn is not None and len(rgn) >= off + sz:
            return bytes(rgn[off : off + sz])
    raise RuntimeError(f"no region large enough for {field_name!r} (offset={off}, length={sz})")

def summarize_fields(vm: Any, field_names: Sequence[str]) -> dict[str, str]:
    """Read several WORKING-STORAGE fields at once and decode each as
    EBCDIC text (stripped), for a single compact log line showing exactly
    what the program's own state held at the point you called this.

    A field that errors (not in layout, no region big enough) maps to
    ``f"<error: {exc}>"`` rather than raising, so one bad field name
    doesn't blow up an otherwise-useful summary during debugging.
    """
    from .vsam import from_ebcdic

    out: dict[str, str] = {}
    for name in field_names:
        try:
            out[name] = from_ebcdic(read_vm_field(vm, name)).strip()
        except Exception as exc:  # noqa: BLE001
            out[name] = f"<error: {exc}>"
    return out
