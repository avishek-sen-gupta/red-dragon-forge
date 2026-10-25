# cobble

cobble is the forge's static analyser for COBOL, CICS and JCL corpora. It parses a corpus once
into an ASG cache, then builds a knowledge graph, per-program control-flow graphs and a
byte-level field dataflow from that cache, without running any program.

- Run it end to end: [analyse a corpus](../docs/how-to/analyse-a-corpus.md).
- Entry points and configuration: [config](../docs/reference/cobble/config.md).
- Reference: [diagnostics](../docs/reference/cobble/diagnostics.md),
  [knowledge graph](../docs/reference/cobble/knowledge-graph.md),
  [srccfg](../docs/reference/cobble/srccfg.md),
  [field dataflow](../docs/reference/cobble/field-dataflow.md),
  [viz](../docs/reference/cobble/viz.md).
- Open work: [roadmap](../docs/roadmaps/cobble.md).

MIT; see [LICENSE.md](LICENSE.md). The JCL and `EXEC CICS` grammars come from
[mapa](https://github.com/cschneid-the-elder/mapa) (see
[PROVENANCE.md](../jackal/jcl-bridge/PROVENANCE.md)). The vendored JavaScript libraries carry
their licenses in `cobble/knowledge_graph/vendor/`.
