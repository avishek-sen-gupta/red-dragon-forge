# Set up a fresh clone

## Prerequisites

- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- JDK 17+ and Maven (the two bridge JARs)
- CMake, Ninja and a C++ toolchain (`hlasm_export`)
- Docker, only for the Db2-backed tests and the Db2 CardDemo server
- [bd](https://github.com/gastownhall/beads), only if you work on issues

## Steps

1. Clone with submodules.

   ```bash
   git clone --recurse-submodules git@github.com:avishek-sen-gupta/red-dragon-forge.git
   cd red-dragon-forge
   ```

2. Build everything: submodules, `hlasm_export`, both bridge JARs, and the uv workspace.

   ```bash
   make setup
   ```

   If a native tool is missing, the build stops with `error: hlasm_export needs <tool>`.

3. Export the JAR paths into your shell. Do this in every new shell before running a runtime
   or its tests by hand.

   ```bash
   . ./bridge-env.sh
   ```

   It prints nothing when both JARs exist, and `warning: … not built` otherwise.

4. Check the install by running the static analyser's suite, which needs no JVM or Db2.

   ```bash
   (cd cobble && uv run --no-sync python -m pytest -q)
   ```

   Expect it to pass. For the other suites, see [Run the tests](run-tests.md).

5. Optional: rebuild the local issue database. Run each `bd` command separately.

   ```bash
   bd init --prefix red-dragon-forge --non-interactive --quiet --skip-hooks --skip-agents --role maintainer
   bd import issues/issues.jsonl
   bd config set export.auto true
   bd config set export.path "../issues/issues.jsonl"
   bd config set export.git-add false
   bd config set import.auto false
   ```

   `bd ready` then lists open work.

## After pulling a new `vendor/red-dragon`

```bash
git submodule update --init --recursive
make jar-force
make python
```
