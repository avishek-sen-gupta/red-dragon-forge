# red-dragon-forge local development tasks.
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
JCL_BRIDGE_JAR     ?= $(CURDIR)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
HLASM_FORK         := $(CURDIR)/cicada/third-party/che-che4z-lsp-for-hlasm-fork
HLASM_EXPORT       := $(HLASM_FORK)/build/bin/hlasm_export

PYTEST = uv run --no-sync python -m pytest

.PHONY: help setup hlasm jar jar-force python test test-all fmt

help:
	@echo "make setup     - init submodules + build hlasm_export + bridge JARs + uv sync"
	@echo "make hlasm     - build hlasm_export from the HLASM fork (skipped if already built)"
	@echo "make jar       - build ProLeap + JCL bridge JARs (skipped if already built)"
	@echo "make jar-force - force-rebuild both bridge JARs"
	@echo "make python    - uv sync (all workspace members)"
	@echo "make test      - full test suite (needs jar)"
	@echo "make test-all  - jar once, then run every package's full suite (cicada, squall, jackal, cobble, forge)"
	@echo "make fmt       - black-format the codebase"

setup:
	git submodule update --init --recursive
	$(MAKE) hlasm
	$(MAKE) jar
	$(MAKE) python

$(HLASM_EXPORT):
	@for tool in cmake ninja $${CXX:-c++}; do \
	  command -v $$tool >/dev/null || { echo "error: hlasm_export needs $$tool (CMake + Ninja + a C++ toolchain, e.g. LLVM@18)" >&2; exit 1; }; \
	done
	cd $(HLASM_FORK) && BUILD_TYPE=Release ./build.sh --target hlasm_export

hlasm: $(HLASM_EXPORT)

$(PROLEAP_BRIDGE_JAR):
	cd vendor/red-dragon/proleap-bridge && ./build.sh

# JCL bridge = jackal's own mapa ANTLR grammar + serializer; mvn is
# incremental and skips recompilation when sources are unchanged.
.PHONY: _jcl_bridge
_jcl_bridge:
	cd jackal/jcl-bridge && mvn -DskipTests package -q

jar: $(PROLEAP_BRIDGE_JAR) _jcl_bridge

jar-force:
	cd vendor/red-dragon/proleap-bridge && ./build.sh
	cd jackal/jcl-bridge && mvn -DskipTests package -q

python:
	uv sync --all-packages

test: jar
	export PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) JCL_BRIDGE_JAR=$(JCL_BRIDGE_JAR) SQUALL_DIR=squall; \
	  . squall/db2/dsn-env.sh && $(PYTEST) tests/ $(PYTEST_ARGS)

test-all: jar
	PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) $(MAKE) -C cicada test
	PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) $(MAKE) -C squall test
	PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) JCL_BRIDGE_JAR=$(JCL_BRIDGE_JAR) $(MAKE) -C jackal test
	cd cobble && $(PYTEST)
	$(MAKE) test

fmt:
	uv run --no-sync python -m black red_dragon_forge tests
