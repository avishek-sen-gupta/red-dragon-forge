# cobble: Consolidate Build Dependencies into Forge

**Date:** 2026-09-16
**Status:** planned

---

## Goal

`make setup` at the forge root is the only build step. It builds every tool cobble uses — both
bridge JARs and `hlasm_export` — and never delegates to cobble's Makefile. Cobble's Makefile is
reduced to operations over a corpus (`sym`, `csd`, `parse`, `build`, `compare`, `render`, …) and
builds nothing.

## Already done (`b0139eed`)

Cobble's copies of the proleap bridge, JCL bridge, CardDemo corpus and HLASM fork, and
`cobble/.gitmodules`, are deleted. Cobble's `PROLEAP_BRIDGE_JAR` / `JCL_BRIDGE_JAR` and
`generate_sym.py`'s `_HLASM` point at forge's copies; the HLASM fork is already the forge
submodule `cicada/third-party/che-che4z-lsp-for-hlasm-fork` (branch `krakatoa-1.22.1`). The graph
was verified unchanged (449/803, empty `make compare` diff). The proleap drift noted in earlier
drafts is moot: cobble already consumes forge's JAR.

What remains is that `hlasm_export` is built only by cobble's `make hlasm` or by CI directly, and
cobble still carries build targets, a standalone `build.sh`, and README text for the old layout.

---

## 1 — Root `Makefile` builds `hlasm_export`

```makefile
HLASM_FORK   := $(CURDIR)/cicada/third-party/che-che4z-lsp-for-hlasm-fork
HLASM_EXPORT := $(HLASM_FORK)/build/bin/hlasm_export

$(HLASM_EXPORT):
	@for tool in cmake ninja $${CXX:-c++}; do \
	  command -v $$tool >/dev/null || { echo "error: hlasm_export needs $$tool (CMake + Ninja + a C++ toolchain, e.g. LLVM@18)" >&2; exit 1; }; \
	done
	cd $(HLASM_FORK) && BUILD_TYPE=Release ./build.sh --target hlasm_export

hlasm: $(HLASM_EXPORT)
```

- A file target, like `$(PROLEAP_BRIDGE_JAR)`: `setup` skips it once built.
- The toolchain check fails fast with a named missing tool, before the CMake configure (decision:
  hard requirement with a clear message, not a silent skip).
- `setup` becomes: submodules → `hlasm` → `jar` → `python`.
- Add `hlasm` to `.PHONY` and `help`. `jar-force` is unchanged; no `hlasm-force` (delete
  `build/` to rebuild).

## 2 — CI uses the root target

In `.github/workflows/ci.yml`, the "Build hlasm_export" step calls `make hlasm` from the repo root
(keeping `CC=clang`, `CXX=clang++`) instead of invoking the fork's `build.sh` directly. The apt
install step stays.

## 3 — Cobble's `Makefile` builds nothing

- Remove `all`, `tools`, `hlasm`, `jars` and the `HLASM_FORK` variable, plus their `.PHONY`
  entries. Add the missing `parse` to `.PHONY`.
- Keep `FORGE`, `PROLEAP_BRIDGE_JAR`, `JCL_BRIDGE_JAR`, `BRIDGE_ENV` — `parse`/`build` still pass
  the JAR paths to the stages.
- `generate_sym.py`'s missing-binary error names the root target:
  `run \`make setup\` (or \`make hlasm\`) at the forge root`.

## 4 — Delete `cobble/build.sh`

It fetched cobble-local submodules and ran `make tools`. The end-to-end sequence it scripted
(`sym` → `parse` → `build` → `compare` → `render`) moves into the README as a command list after
root `make setup`.

## 5 — `cobble/README.md`

Rewrite every section describing the standalone layout:

- Intro / prerequisites / quick start (~L14–53): prerequisite is root `make setup`; drop
  `./build.sh`, `make tools`, the `tools` row of the target table and the cobble submodule fetch.
- Manual bridge invocation (~L321–324): JAR paths become forge's.
- Layout tables (~L780–796): drop `proleap-bridge/`, `jcl-bridge/`, `vendor/carddemo/`,
  `vendor/che-che4z-lsp-for-hlasm/` and the submodule table; state which forge paths provide them.
- JCL grammar provenance (~L817–831): point at `jackal/jcl-bridge/PROVENANCE.md` and `LICENSE`.

## 6 — Local cleanup

Remove the empty, untracked `cobble/vendor/` directory.

---

## Verification

```bash
rm -rf cicada/third-party/che-che4z-lsp-for-hlasm-fork/build
make setup                              # builds hlasm_export, both JARs, uv sync
make setup                              # second run: hlasm and ProLeap JAR skipped
PATH=/usr/bin:/bin make hlasm           # with the binary removed: fails naming cmake/ninja
cd cobble
make sym CONFIG=config/carddemo.toml
make parse CONFIG=config/parse-carddemo.toml
make build CONFIG=config/carddemo.toml
make compare                            # empty diff
make test lint
grep -rn "build\.sh\|make tools\|make jars" cobble   # no hits
```

CI's workflow must stay green with the `make hlasm` step.
