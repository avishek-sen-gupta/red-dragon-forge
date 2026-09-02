# The bridges, the corpus and the HLASM exporter are the workspace's, not
# cobble's: cobble carried its own copies of all three as a standalone repo, and
# every one pointed at the same upstream forge already vendors.
FORGE              := $(CURDIR)/..
PROLEAP_BRIDGE_JAR := $(FORGE)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
JCL_BRIDGE_JAR     := $(FORGE)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
HLASM_FORK         := $(FORGE)/cicada/third-party/che-che4z-lsp-for-hlasm-fork
BRIDGE_ENV         := PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) JCL_BRIDGE_JAR=$(JCL_BRIDGE_JAR)

.PHONY: all tools hlasm jars codegen sym csd build compare verify render render-webgl test fmt lint clean

## Full run from a fresh clone: submodules -> tools -> codegen -> extract -> verify.
all: ; @./build.sh

## Build every tool from source: the HLASM exporter + the proleap fork + both bridge JARs.
tools: hlasm jars

## Build hlasm_export from the workspace's fork (cmake + Ninja + LLVM@18).
hlasm:
	cd $(HLASM_FORK) && BUILD_TYPE=Release bash build.sh --target hlasm_export

## Build both bridge JARs via the workspace's own target, which also installs the
## proleap-cobol-parser FORK (not on Maven Central) into ~/.m2 first.
jars:
	$(MAKE) -C $(FORGE) jar

## Generate everything that's generated-from-a-grammar: the BMS copybooks.
## The EXEC CICS parser is no longer generated here -- cobble uses cicada's,
## whose grammar this one was byte-identical to.
codegen: sym

## Stage-0: GENERATE the BMS symbolic copybooks from the corpus's .bms sources
## (hlasm_export | bms_copybook_gen -> sym/*.cpy). Nothing pre-generated is shipped.
## Requires CONFIG=<path-to-corpus-yaml>, e.g. make sym CONFIG=config/carddemo.yaml
sym:
	@test -n "$(CONFIG)" || { echo "error: CONFIG is required, e.g. make sym CONFIG=config/carddemo.yaml" >&2; exit 1; }
	uv run --no-sync cobble-sym --config $(CONFIG)

## Stage-0: GENERATE a synthetic CSD for a corpus that arrived without one, from
## literal transaction ids plus the corpus's own naming convention
## (`transid_rules:` in the config) -> <out_dir>/synthetic.csd. Point the config's
## csd_files at it afterwards; without a CSD the whole CICS flow stage is skipped.
## Requires CONFIG=<path-to-corpus-yaml>, e.g. make csd CONFIG=config/carddemo.yaml
csd:
	@test -n "$(CONFIG)" || { echo "error: CONFIG is required, e.g. make csd CONFIG=config/carddemo.yaml" >&2; exit 1; }
	uv run --no-sync cobble-csd --config $(CONFIG)

## Run the four ported extractors over the corpus -> out/{nodes,edges}.jsonl
## Requires CONFIG=<path-to-corpus-yaml>, e.g. make build CONFIG=config/carddemo.yaml
build:
	@test -n "$(CONFIG)" || { echo "error: CONFIG is required, e.g. make build CONFIG=config/carddemo.yaml" >&2; exit 1; }
	$(BRIDGE_ENV) uv run --no-sync cobble-build --config $(CONFIG)

## Identity-diff out/ against reference/ (must be an empty diff: 449 nodes / 803 edges).
compare:
	uv run --no-sync cobble-compare

verify: build compare

## Render <out_dir>/{nodes,edges}.jsonl as a self-contained interactive HTML graph.
## Requires CONFIG=<path-to-corpus-yaml>, e.g. make render CONFIG=config/carddemo.yaml
render:
	@test -n "$(CONFIG)" || { echo "error: CONFIG is required, e.g. make render CONFIG=config/carddemo.yaml" >&2; exit 1; }
	uv run --no-sync cobble-render --config $(CONFIG)

## Render the same pair as a WebGL view built for showing a whole corpus-sized
## graph at once (sibling of `render`, which is for navigating one). Lays the
## graph out up front with graphviz's sfdp, so graphviz must be installed and
## the layout takes about a minute at corpus scale.
## Requires CONFIG=<path-to-corpus-yaml>, e.g. make render-webgl CONFIG=config/carddemo.yaml
render-webgl:
	@test -n "$(CONFIG)" || { echo "error: CONFIG is required, e.g. make render-webgl CONFIG=config/carddemo.yaml" >&2; exit 1; }
	uv run --no-sync cobble-render-webgl --config $(CONFIG)

## Run the pytest unit suite (pure modules only — no JARs/corpus needed).
test:
	uv run --no-sync python -m pytest $(PYTEST_ARGS)

## Auto-format the codebase with black.
fmt:
	uv run --no-sync python -m black cobble tests

## Run static analysis: import-linter contracts + pyright + python-fp-lint.
lint:
	uv run --no-sync lint-imports
	uv run --no-sync pyright
	uv run --no-sync python -m python_fp_lint check cobble/

## Drop this corpus's generated output. NOTE: sym/ is a copybook_dirs entry, so
## `make sym` has to run again before the next `make build`.
clean:
	rm -rf out cache sym
