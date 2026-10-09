# Documentation

## How-to

| Page | Use it to |
|---|---|
| [Set up a fresh clone](how-to/setup.md) | Install, build the JARs and native tool, set up beads |
| [Run the tests](how-to/run-tests.md) | Run every suite, one suite, or the pre-commit checks |
| [Db2](how-to/db2.md) | Start, seed, check and repair the Db2 container |
| [Run CardDemo over TN3270](how-to/run-carddemo.md) | Serve CardDemo to a 3270 emulator, with or without Db2 |
| [Run a JCL job](how-to/run-jcl-job.md) | Run a CardDemo batch job with jackal |
| [Analyse a corpus with cobble](how-to/analyse-a-corpus.md) | Take a COBOL corpus from source to knowledge graph and dataflow |

## Reference

| Area | Pages |
|---|---|
| Forge | [Architecture](reference/forge/architecture.md): packages, the `CoprocessorSpec` seam, composition, package boundaries |
| cicada | [Architecture](reference/cicada/architecture.md), [TN3270 server and config](reference/cicada/tn3270-config.md), [architecture overview (HTML)](reference/cicada/cicada-architecture.html), [conversational suspend/resume (HTML)](reference/cicada/conversational-suspend-resume.html) |
| squall | [Architecture](reference/squall/architecture.md) |
| jackal | [Architecture](reference/jackal/architecture.md), [CLI](reference/jackal/cli.md), [IDCAMS reference (PDF)](reference/jackal/idcams-ref.pdf) |
| cobble | [Entry points and configuration](reference/cobble/config.md), [knowledge graph](reference/cobble/knowledge-graph.md), [source control-flow graphs](reference/cobble/srccfg.md), [field dataflow](reference/cobble/field-dataflow.md), [path traces](reference/cobble/trace.md), [pre-flight diagnoses](reference/cobble/diagnostics.md), [views and screens](reference/cobble/viz.md) |

## Roadmaps

What each package supports and what is open, by issue ID: [cicada](roadmaps/cicada.md),
[jackal](roadmaps/jackal.md), [cobble](roadmaps/cobble.md).

## Explainers

[Explainers](explainers/index.html) teach the program-analysis ideas behind cobble's dataflow:
reaching definitions, fixpoints, dominance, loops, and related topics, and the techniques that
make the dynamic-call-target pipeline finish on a large corpus: area need, local site resolution,
rounds, sweeps, memoised reachability and hop limits.

## Presentation

[The deck](presentation/index.html). To view it:

```bash
make -C docs/presentation serve
```

Then open `http://127.0.0.1:8000`. `make -C docs/presentation artifacts` regenerates its
evidence; the Makefile header lists what that needs.

## Records

Dated and frozen. Never edited after they are written.

- [Specs and plans](superpowers/README.md)
- [Design records and analyses](records/README.md)

## Project

- [Philosophy](philosophy.md)
- Rules for contributors and agents: [`CLAUDE.md`](../CLAUDE.md) and [`guidelines/`](../guidelines/)
- Issues: tracked with `bd`; see [Set up a fresh clone](how-to/setup.md), step 5
