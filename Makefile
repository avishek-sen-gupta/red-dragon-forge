# red-dragon-forge local development tasks.
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar

PYTEST = uv run --no-sync python -m pytest

.PHONY: help setup jar jar-force python test test-all fmt

help:
	@echo "make setup     - init submodules + build bridge JAR + uv sync"
	@echo "make jar       - build ProLeap bridge JAR (skipped if already built)"
	@echo "make jar-force - force-rebuild ProLeap bridge JAR"
	@echo "make python    - uv sync (all workspace members)"
	@echo "make test      - full test suite (needs jar)"
	@echo "make test-all  - jar once, then run every package's full suite (cicada, squall, jackal, forge)"
	@echo "make fmt       - black-format the codebase"

setup:
	git submodule update --init --recursive
	$(MAKE) jar
	$(MAKE) python

$(PROLEAP_BRIDGE_JAR):
	cd vendor/red-dragon/proleap-bridge && ./build.sh

jar: $(PROLEAP_BRIDGE_JAR)

jar-force:
	cd vendor/red-dragon/proleap-bridge && ./build.sh

python:
	uv sync --all-packages

test: jar
	PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) $(PYTEST) tests/ $(PYTEST_ARGS)

test-all: jar
	PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) $(MAKE) -C cicada test
	PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) $(MAKE) -C squall test
	PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) $(MAKE) -C jackal test
	$(MAKE) test

fmt:
	uv run --no-sync python -m black red_dragon_forge tests
