<p align="center">
  <img src="docs/assets/banner.png" alt="red-dragon-forge — CICS · SQL · JCL" width="100%">
</p>

# red-dragon-forge

Runtimes that execute mainframe COBOL programs on the
[RedDragon](https://github.com/avishek-sen-gupta/red-dragon) interpreter, a layer that composes
them, and a static analyser for the same code.

| Package | What it is |
|---|---|
| [`cicada/`](cicada/) | CICS runtime and TN3270 server |
| [`squall/`](squall/) | EXEC SQL runtime for Db2 programs |
| [`jackal/`](jackal/) | JCL/batch engine |
| [`red_dragon_forge/`](red_dragon_forge/) | Composition layer |
| [`cobble/`](cobble/) | Static analyser: knowledge graph, control flow, field dataflow |

## Quick start

```bash
git clone --recurse-submodules git@github.com:avishek-sen-gupta/red-dragon-forge.git
cd red-dragon-forge
make setup
```

Then:

- [Run CardDemo in a 3270 terminal](docs/how-to/run-carddemo.md)
- [Run a JCL job](docs/how-to/run-jcl-job.md)
- [Analyse a COBOL corpus](docs/how-to/analyse-a-corpus.md)
- [Run the tests](docs/how-to/run-tests.md)

## Documentation

All documentation is indexed in [`docs/README.md`](docs/README.md).
