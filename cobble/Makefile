PROLEAP_BRIDGE_JAR := $(CURDIR)/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
JCL_BRIDGE_JAR     := $(CURDIR)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
BRIDGE_ENV         := PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) JCL_BRIDGE_JAR=$(JCL_BRIDGE_JAR)

ANTLR_VERSION := 4.13.1
ANTLR_JAR     := $(CURDIR)/tools/antlr-$(ANTLR_VERSION)-complete.jar
ANTLR_URL     := https://www.antlr.org/download/antlr-$(ANTLR_VERSION)-complete.jar

.PHONY: all tools hlasm jars codegen parser sym csd build compare verify render render-webgl canonical test fmt lint clean

## Full run from a fresh clone: submodules -> tools -> codegen -> extract -> verify.
all: ; @./build.sh

## Build every tool from source: the HLASM exporter + the proleap fork + both bridge JARs.
tools: hlasm jars

## Build hlasm_export from the che-che4z-lsp-for-hlasm submodule (cmake + Ninja + LLVM@18).
hlasm:
	cd vendor/che-che4z-lsp-for-hlasm && BUILD_TYPE=Release bash build.sh --target hlasm_export

## Build the proleap-cobol-parser FORK (io.github.uwol:proleap-cobol-parser:4.0.0, NOT on
## Maven Central — install to ~/.m2 first) then the two bridge JARs.
jars:
	cd proleap-bridge/proleap-cobol-parser && mvn -q -DskipTests clean install -Dmaven.wagon.http.ssl.insecure=true -Dmaven.wagon.http.ssl.allowall=true -Daether.connector.https.securityMode=insecure
	cd proleap-bridge && mvn -q -DskipTests package -Dmaven.wagon.http.ssl.insecure=true -Dmaven.wagon.http.ssl.allowall=true -Daether.connector.https.securityMode=insecure
	cd jcl-bridge && mvn -q -DskipTests package -Dmaven.wagon.http.ssl.insecure=true -Dmaven.wagon.http.ssl.allowall=true -Daether.connector.https.securityMode=insecure

## Generate everything that's generated-from-a-grammar: the CICS parser + the BMS copybooks.
codegen: parser sym

## Generate the CICS EXEC parser (Python3) from the ANTLR .g4 grammar.
parser: $(ANTLR_JAR)
	cd cobble/cics/cics_grammar && java -jar $(ANTLR_JAR) -Dlanguage=Python3 -visitor CICSzLexer.g4 CICSzParser.g4

$(ANTLR_JAR):
	mkdir -p tools
	curl -fsSL $(ANTLR_URL) -o $(ANTLR_JAR)

## Stage-0: GENERATE the BMS symbolic copybooks from the corpus's .bms sources
## (hlasm_export | bms_copybook_gen -> sym/*.cpy). Nothing pre-generated is shipped.
## Requires CONFIG=<path-to-corpus-yaml>, e.g. make sym CONFIG=config/carddemo.yaml
sym:
	@test -n "$(CONFIG)" || { echo "error: CONFIG is required, e.g. make sym CONFIG=config/carddemo.yaml" >&2; exit 1; }
	uv run python -m cobble.generate_sym --config $(CONFIG)

## Stage-0: GENERATE a synthetic CSD for a corpus that arrived without one, from
## literal transaction ids plus the corpus's own naming convention
## (`transid_rules:` in the config) -> <out_dir>/synthetic.csd. Point the config's
## csd_files at it afterwards; without a CSD the whole CICS flow stage is skipped.
## Requires CONFIG=<path-to-corpus-yaml>, e.g. make csd CONFIG=config/carddemo.yaml
csd:
	@test -n "$(CONFIG)" || { echo "error: CONFIG is required, e.g. make csd CONFIG=config/carddemo.yaml" >&2; exit 1; }
	uv run python -m cobble.generate_csd --config $(CONFIG)

## Run the four ported extractors over the corpus -> out/{nodes,edges}.jsonl
## Requires CONFIG=<path-to-corpus-yaml>, e.g. make build CONFIG=config/carddemo.yaml
build:
	@test -n "$(CONFIG)" || { echo "error: CONFIG is required, e.g. make build CONFIG=config/carddemo.yaml" >&2; exit 1; }
	$(BRIDGE_ENV) uv run python -m cobble.build_graph --config $(CONFIG)

## Identity-diff out/ against reference/ (must be an empty diff: 449 nodes / 803 edges).
compare:
	uv run python -m cobble.compare

verify: build compare

## Render <out_dir>/{nodes,edges}.jsonl as a self-contained interactive HTML graph.
## Requires CONFIG=<path-to-corpus-yaml>, e.g. make render CONFIG=config/carddemo.yaml
render:
	@test -n "$(CONFIG)" || { echo "error: CONFIG is required, e.g. make render CONFIG=config/carddemo.yaml" >&2; exit 1; }
	uv run python -m cobble.render_graph --config $(CONFIG)

## Render the same pair as a WebGL view built for showing a whole corpus-sized
## graph at once (sibling of `render`, which is for navigating one). Lays the
## graph out up front with graphviz's sfdp, so graphviz must be installed and
## the layout takes about a minute at corpus scale.
## Requires CONFIG=<path-to-corpus-yaml>, e.g. make render-webgl CONFIG=config/carddemo.yaml
render-webgl:
	@test -n "$(CONFIG)" || { echo "error: CONFIG is required, e.g. make render-webgl CONFIG=config/carddemo.yaml" >&2; exit 1; }
	uv run python -m cobble.render_graph_webgl --config $(CONFIG)

## Export a nodes/edges.jsonl pair as CodeConcise's canonical manifest.json.
## Requires NODES=, EDGES=, OUTPUT=, PROJECT_NAME= (all explicit, no defaults),
## e.g. make canonical NODES=out/nodes.jsonl EDGES=out/edges.jsonl OUTPUT=out/manifest.json PROJECT_NAME=carddemo
canonical:
	@test -n "$(NODES)" || { echo "error: NODES is required, e.g. make canonical NODES=out/nodes.jsonl ..." >&2; exit 1; }
	@test -n "$(EDGES)" || { echo "error: EDGES is required, e.g. make canonical ... EDGES=out/edges.jsonl ..." >&2; exit 1; }
	@test -n "$(OUTPUT)" || { echo "error: OUTPUT is required, e.g. make canonical ... OUTPUT=out/manifest.json ..." >&2; exit 1; }
	@test -n "$(PROJECT_NAME)" || { echo "error: PROJECT_NAME is required, e.g. make canonical ... PROJECT_NAME=carddemo" >&2; exit 1; }
	uv run python -m cobble.canonical_export --nodes $(NODES) --edges $(EDGES) --output $(OUTPUT) --project-name $(PROJECT_NAME)

## Run the pytest unit suite (pure modules only — no JARs/corpus needed).
test:
	uv run pytest

## Auto-format the codebase with black.
fmt:
	uv run python -m black .

## Run static analysis: import-linter contracts + pyright + python-fp-lint.
lint:
	uv run lint-imports
	uv run pyright
	uv run python -m python_fp_lint check cobble/

clean:
	rm -rf out cache sym
	rm -f cobble/cics/cics_grammar/CICSz*.py cobble/cics/cics_grammar/*.interp cobble/cics/cics_grammar/*.tokens
