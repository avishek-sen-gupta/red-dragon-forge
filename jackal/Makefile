# Jackal local development tasks.
#
# `make jar`       — build ALL Java artefacts: the ProLeap bridge (parser +
#                    bridge, from the vendored red-dragon submodule) and the
#                    JCL bridge (mapa ANTLR grammar + serializer). Skipped if
#                    already built; use `make jar-force` after a red-dragon bump.
# `make build`     — ./build.sh: force-rebuild both JARs + uv sync (uniform
#                    across cicada/jackal/squall).
# `make test`      — full suite (needs the JARs + CARDDEMO_HOME for the gated e2e).
#
# Override any path via the environment.
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
JCL_BRIDGE_JAR     ?= $(CURDIR)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
CARDDEMO_HOME      ?= $(CURDIR)/third-party/carddemo/app

E2E_ENV = PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) JCL_BRIDGE_JAR=$(JCL_BRIDGE_JAR) CARDDEMO_HOME=$(CARDDEMO_HOME)
PYTEST       = uv run --no-sync python -m pytest
PYTEST_PATHS ?= tests/
PYTEST_ARGS  ?=

.PHONY: help setup build python jar jar-force test test-unit fmt lint

help:
	@echo "make setup       - init submodules + build all Java + uv sync (run once after clone)"
	@echo "make jar         - build all Java: ProLeap bridge (parser+bridge) + JCL bridge (skipped if built)"
	@echo "make jar-force   - force-rebuild all Java artefacts"
	@echo "make build       - ./build.sh: force-rebuild both JARs + uv sync"
	@echo "make python      - uv sync (install / refresh Python deps)"
	@echo "make test        - full suite (JARs + CARDDEMO_HOME wired up)"
	@echo "make test-unit   - unit tests only"
	@echo "make fmt         - black-format jackal + tests"
	@echo "make lint        - import-linter architectural contracts"
	@echo ""
	@echo "  PROLEAP_BRIDGE_JAR = $(PROLEAP_BRIDGE_JAR)"
	@echo "  JCL_BRIDGE_JAR     = $(JCL_BRIDGE_JAR)"
	@echo "  CARDDEMO_HOME      = $(CARDDEMO_HOME)"

setup:
	git submodule update --init --recursive
	$(MAKE) build

python:
	uv sync

# ProLeap bridge = the red-dragon submodule's parser + the bridge (build.sh does both).
$(PROLEAP_BRIDGE_JAR):
	cd ../vendor/red-dragon/proleap-bridge && ./build.sh

# JCL bridge = jackal's own mapa ANTLR grammar + serializer.
# Always run mvn — it is incremental and skips recompilation when sources are unchanged.
.PHONY: _jcl_bridge
_jcl_bridge:
	cd jcl-bridge && mvn -DskipTests package -q

jar: $(PROLEAP_BRIDGE_JAR) _jcl_bridge

jar-force:
	cd ../vendor/red-dragon/proleap-bridge && ./build.sh
	cd jcl-bridge && mvn -DskipTests package -q

build:
	./build.sh

test: jar
	$(E2E_ENV) $(PYTEST) $(PYTEST_PATHS) $(PYTEST_ARGS)

test-unit:
	$(PYTEST) tests/unit $(PYTEST_ARGS)

fmt:
	uv run --no-sync python -m black jackal tests

lint:
	uv run --no-sync lint-imports --config ../.importlinter
