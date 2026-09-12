"""The byte-extent dataflow fixpoint: the corpus pass and the queries over it.

The solver itself (``fixpoint``), what the caller chose about a run
(``options``, ``config``), the pass that writes the graph halves and side tables
(``build_corpus``), and the reads back out of them (``query``, ``rows``).

The alias algebra, extents, transfer functions and emitters those build on stay
in ``cobble.dataflow.fields``, which the path-sampling trace shares.

See docs/superpowers/specs/2026-09-05-field-level-byte-dataflow-design.md.
"""
