"""
squall.binding_stores
~~~~~~~~~~~~~~~~~~~~~
The genuinely-mutating writes ``squall.binding`` needs, isolated in their own
leaf module -- mirroring ``squall.backends._stores`` -- so the mutation stays out of ``binding``'s
otherwise FP-linted, pure surface. ``binding`` computes values purely (the
``(offset, bytes)`` writes, the vendor path to add); this module is the one
place that applies them.
"""

from __future__ import annotations

import sys


def apply_writes(region: bytearray, writes: tuple[tuple[int, bytes], ...]) -> None:
    """Apply each ``(offset, data)`` write to *region* in place.

    The single mutation boundary for every WS-region byte write ``binding``
    makes (SQLCODE, SQLERRM, and a planned host-var assignment's bytes) --
    each caller computes its writes purely and hands them here.
    """
    for offset, data in writes:
        region[offset : offset + len(data)] = data


def bootstrap_vendor_path(vendor_path: str) -> None:
    """Prepend *vendor_path* to ``sys.path`` if it is not already present.

    The one process-global mutation ``binding`` needs at import time, so
    ``ByteConstants``/``Address``/``VarName`` (RedDragon's vendored types)
    resolve without installing red-dragon as an editable package in every
    environment.
    """
    if vendor_path not in sys.path:
        sys.path.insert(0, vendor_path)
