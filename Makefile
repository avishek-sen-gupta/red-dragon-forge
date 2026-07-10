PROLEAP_BRIDGE_JAR := $(CURDIR)/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
JCL_BRIDGE_JAR     := $(CURDIR)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
BRIDGE_ENV         := PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) JCL_BRIDGE_JAR=$(JCL_BRIDGE_JAR)

.PHONY: all jars build compare verify clean

## Full run from a fresh clone: build the bridge JARs, extract the graph, check it.
all: ; @./build.sh

## Build the Java bridge JARs (Maven). The proleap-cobol-parser FORK (submodule,
## published as io.github.uwol:proleap-cobol-parser:4.0.0 — NOT on Maven Central)
## must be installed to the local ~/.m2 first, then the bridge resolves it.
jars:
	cd proleap-bridge/proleap-cobol-parser && mvn -q -DskipTests clean install
	cd proleap-bridge && mvn -q -DskipTests package
	cd jcl-bridge && mvn -q -DskipTests package

## Run the four ported extractors over the CardDemo corpus -> out/{nodes,edges}.jsonl
build:
	$(BRIDGE_ENV) uv run python build_port.py

## Identity-diff out/ against reference/ (must be an empty diff: 449 nodes / 803 edges).
compare:
	uv run python compare.py

## build + compare
verify: build compare

clean:
	rm -rf out cache
