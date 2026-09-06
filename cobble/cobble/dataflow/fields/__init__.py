"""Field-level byte dataflow: which bytes a field's value came from.

Cobble's source CFG chains statements by matching operand name strings, so a
write to a group member and a read of the group are unrelated events and
INITIALIZE kills nothing. A MOVE copies a byte range, and stating the analysis
over byte extents makes group containment, REDEFINES aliasing, OCCURS striding
and reference modification fall out of range overlap rather than needing a rule
each.

The alias algebra is cobol_memory's, extracted from the interpreter's own
field-level dataflow: may_alias over-approximates, so an edge survives when
overlap is uncertain; must_cover under-approximates, so only an EXACT extent
may kill a definition and a computed subscript never does. The extents come
from cobble.dataflow.layout, the control flow from cobble.dataflow.srccfg.

See docs/superpowers/specs/2026-09-05-field-level-byte-dataflow-design.md.
"""
