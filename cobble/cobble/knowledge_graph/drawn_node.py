"""DrawnNode — any graph's (kind, id), as the layout and the renderers take it.

The merged graph indexes its nodes by its own NodeKind; a source CFG indexes its by
the CFG's. A Mapping cannot be widened in what it is indexed by, so the layout and
the renderers name the shape they need — an enum kind and an id — rather than the
merged graph's.
"""

from __future__ import annotations

from enum import Enum
from typing import TypeAlias

DrawnNode: TypeAlias = tuple[Enum, str]
