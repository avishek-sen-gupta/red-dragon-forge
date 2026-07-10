PROLEAP_BRIDGE_JAR := $(CURDIR)/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
JCL_BRIDGE_JAR     := $(CURDIR)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
BRIDGE_ENV         := PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) JCL_BRIDGE_JAR=$(JCL_BRIDGE_JAR)

ANTLR_VERSION := 4.13.1
ANTLR_JAR     := $(CURDIR)/tools/antlr-$(ANTLR_VERSION)-complete.jar
ANTLR_URL     := https://www.antlr.org/download/antlr-$(ANTLR_VERSION)-complete.jar

.PHONY: all tools hlasm jars codegen parser sym build compare verify clean

## Full run from a fresh clone: submodules -> tools -> codegen -> extract -> verify.
all: ; @./build.sh

## Build every tool from source: the HLASM exporter + the proleap fork + both bridge JARs.
tools: hlasm jars

## Build hlasm_export from the che-che4z-lsp-for-hlasm submodule (cmake + Ninja + LLVM@18).
hlasm:
	cd third-party/che-che4z-lsp-for-hlasm && BUILD_TYPE=Release bash build.sh --target hlasm_export

## Build the proleap-cobol-parser FORK (io.github.uwol:proleap-cobol-parser:4.0.0, NOT on
## Maven Central — install to ~/.m2 first) then the two bridge JARs.
jars:
	cd proleap-bridge/proleap-cobol-parser && mvn -q -DskipTests clean install
	cd proleap-bridge && mvn -q -DskipTests package
	cd jcl-bridge && mvn -q -DskipTests package

## Generate everything that's generated-from-a-grammar: the CICS parser + the BMS copybooks.
codegen: parser sym

## Generate the CICS EXEC parser (Python3) from the ANTLR .g4 grammar.
parser: $(ANTLR_JAR)
	cd cobble/cics/cics_grammar && java -jar $(ANTLR_JAR) -Dlanguage=Python3 -visitor CICSzLexer.g4 CICSzParser.g4

$(ANTLR_JAR):
	mkdir -p tools
	curl -fsSL $(ANTLR_URL) -o $(ANTLR_JAR)

## Stage-0: GENERATE the BMS symbolic copybooks from the CardDemo .bms sources
## (hlasm_export | bms_copybook_gen -> sym/*.cpy). Nothing pre-generated is shipped.
sym:
	uv run python generate_sym.py

## Run the four ported extractors over the corpus -> out/{nodes,edges}.jsonl
build:
	$(BRIDGE_ENV) uv run python build_port.py

## Identity-diff out/ against reference/ (must be an empty diff: 449 nodes / 803 edges).
compare:
	uv run python compare.py

verify: build compare

clean:
	rm -rf out cache sym
	rm -f cobble/cics/cics_grammar/CICSz*.py cobble/cics/cics_grammar/*.interp cobble/cics/cics_grammar/*.tokens
