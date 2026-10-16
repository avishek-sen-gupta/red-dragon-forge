<p align="center">
  <img src="docs/assets/banner.png" alt="red-dragon-forge — CICS · SQL · JCL" width="100%">
</p>

# red-dragon-forge

Build, run and analyse a mainframe COBOL application off the mainframe. Declare its datasets,
build its programs into one package, and run that package as a batch program, a JCL job or a CICS
region served to a 3270 terminal, with Db2 behind any of them. The programs execute on the
[RedDragon](https://github.com/avishek-sen-gupta/red-dragon) interpreter. A static analyser reads
the same code without running it.

| Package | What it is |
|---|---|
| [`cicada/`](cicada/) | CICS runtime and TN3270 server |
| [`squall/`](squall/) | EXEC SQL runtime for Db2 programs |
| [`jackal/`](jackal/) | JCL/batch engine |
| [`catnip/`](catnip/) | System catalog: the datasets jobs and CICS regions share |
| [`litter/`](litter/) | Package: COBOL programs lowered once and linked into one image in a zip; `forge-build` writes one, `forge-run` runs it |
| [`red_dragon_forge/`](red_dragon_forge/) | `forge-build` and `forge-run`: build a package from `build.toml`, run it from `env.toml`, composing the runtimes it needs |
| [`cobble/`](cobble/) | Static analyser: knowledge graph, control flow, field dataflow |

CardDemo's online tier served by cicada to a stock `c3270`: a user updates an account, an admin
adds, updates and deletes a user.

<p align="center">
  <img src="docs/presentation/artifacts/cics/carddemo-3270.gif" alt="CardDemo screens in c3270" width="800">
</p>

CardDemo's knowledge graph from cobble, zoomed in on the online programs: programs (blue)
linked to the copybooks (green), maps, transactions and files they use.

<p align="center">
  <img src="docs/assets/carddemo-graph.png" alt="CardDemo knowledge graph, zoomed in" width="100%">
</p>

## Quick start

```bash
git clone --recurse-submodules git@github.com:avishek-sen-gupta/red-dragon-forge.git
cd red-dragon-forge
make setup
```

Then:

- [Run CardDemo in a 3270 terminal](docs/how-to/run-carddemo.md)
- [Run your own COBOL application](docs/how-to/run-your-application.md)
- [Drive forge from Python](docs/how-to/drive-forge-from-python.md)
- [Run a JCL job](docs/how-to/run-jcl-job.md)
- [Analyse a COBOL corpus](docs/how-to/analyse-a-corpus.md)
- [Run the tests](docs/how-to/run-tests.md)

## Documentation

All documentation is indexed in [`docs/README.md`](docs/README.md).
