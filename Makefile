# red-dragon-forge local development tasks.
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
JCL_BRIDGE_JAR     ?= $(CURDIR)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
HLASM_FORK         := $(CURDIR)/vendor/red-dragon/hlasm-bridge/che4z
HLASM_EXPORT       := $(HLASM_FORK)/build/bin/hlasm_export

PYTEST = uv run --no-sync python -m pytest
# Make's /bin/sh is dash on Linux, which bridge-env.sh cannot locate itself from.
BRIDGE_ENV = FORGE_ROOT=$(CURDIR) . ./bridge-env.sh
BLACK_PATHS = cicada/cics cicada/bms_copybook_gen cicada/tests squall/squall squall/tests \
  catnip/catnip catnip/tests litter/litter litter/tests jackal/jackal jackal/tests red_dragon_forge cobble/cobble cobble/tests tools tests
DB2_COMPOSE = docker compose -f squall/docker-compose.yml

.PHONY: help setup hlasm jar jar-force python test test-all fmt partition-traces partition-graph partition-clusters partition-render db2-up db2-seed db2-status db2-restart db2-stop db2-clean

help:
	@echo "make setup     - init submodules + build hlasm_export + rebuild bridge JARs + uv sync"
	@echo "make hlasm     - build hlasm_export from the HLASM fork (skipped if already built)"
	@echo "make jar       - build ProLeap + JCL bridge JARs (skipped if already built)"
	@echo "make jar-force - force-rebuild both bridge JARs"
	@echo "make python    - uv sync (all workspace members)"
	@echo "make test      - root composition-layer suite (needs jar, Db2 DSN)"
	@echo "make test-all  - jar once, then run every package's full suite (cicada, squall, catnip, litter, jackal, cobble, forge)"
	@echo "make fmt       - black-format the codebase"
	@echo "make partition-traces   - experimental: parse, extents, call targets and one path trace per member (PARTITION_CONFIG, PARTITION_ASG)"
	@echo "make partition-graph    - experimental: the field graph of those traces (PARTITION_BARRIER, PARTITION_FANOUT)"
	@echo "make partition-clusters - experimental: clusters of fields inside each program, and their report"
	@echo "make partition-render   - experimental: the WebGL page of the graph and its clusters"
	@echo "make db2-up    - start squall's Db2 container and wait until healthy (idempotent)"
	@echo "make db2-seed  - create and seed CardDemo's Db2 schema (the only DROP TABLE)"
	@echo "make db2-status - does Db2 actually answer? (container up != instance alive)"
	@echo "make db2-restart - restart the Db2 instance without re-initialising (revives a killed instance)"
	@echo "make db2-stop  - stop Db2, keeping container and volume"
	@echo "make db2-clean - remove Db2 container and volume (next up re-inits)"

setup:
	git submodule update --init --recursive
	$(MAKE) hlasm
	$(MAKE) jar-force
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
	$(BRIDGE_ENV) && export SQUALL_DIR=squall && . squall/db2/dsn-env.sh && $(PYTEST) tests/ $(PYTEST_ARGS)

test-all: jar hlasm
	$(BRIDGE_ENV) && cd cicada && $(PYTEST)
	$(BRIDGE_ENV) && cd squall && . db2/dsn-env.sh && $(PYTEST)
	cd catnip && $(PYTEST)
	$(BRIDGE_ENV) && cd litter && $(PYTEST)
	$(BRIDGE_ENV) && cd jackal && $(PYTEST)
	cd cobble && $(PYTEST)
	$(MAKE) test

fmt:
	uv run --no-sync python -m black $(BLACK_PATHS)

# Experimental field partitions (docs/reference/cobble/partition.md). Paths are
# relative to cobble/, where every recipe runs. PARTITION_ASG must be the
# asg_dir PARTITION_CONFIG names: the parse writes it and every later stage reads it.
PARTITION_CONFIG  ?= config/carddemo-partition.toml
PARTITION_ASG     ?= out-partition/asg
PARTITION_DIR     ?= out-partition
PARTITION_PATHS   ?= 3000
PARTITION_BARRIER ?= fanout
PARTITION_FANOUT  ?= 8
COBBLE = cd cobble && uv run --no-sync

partition-traces: jar
	$(BRIDGE_ENV) && $(COBBLE) cobble-parse-corpus --config $(PARTITION_CONFIG)
	$(COBBLE) cobble-extents --asg-dir $(PARTITION_ASG) --out $(PARTITION_DIR)/extents.jsonl
	$(COBBLE) cobble-dataflow-area-need --asg-dir $(PARTITION_ASG) --extents $(PARTITION_DIR)/extents.jsonl --config $(PARTITION_CONFIG) --out $(PARTITION_DIR)/area-need.jsonl
	$(COBBLE) cobble-dataflow-fixpoint --asg-dir $(PARTITION_ASG) --extents $(PARTITION_DIR)/extents.jsonl --out-dir $(PARTITION_DIR)/fixpoint --call-targets-only --narrow-areas $(PARTITION_DIR)/area-need.jsonl --all
	$(COBBLE) cobble-dataflow-combine --config $(PARTITION_CONFIG) --fixpoint-dir $(PARTITION_DIR)/fixpoint --out-dir $(PARTITION_DIR)/combine --all --max-hops 5
	mkdir -p cobble/$(PARTITION_DIR)/traces
	cd cobble && for member in $(PARTITION_ASG)/*.json; do \
	  name=$$(basename $$member .json); \
	  uv run --no-sync cobble-fields-trace $$name --asg-dir $(PARTITION_ASG) --out $(PARTITION_DIR)/traces/$$name.jsonl --paths $(PARTITION_PATHS) || exit 1; \
	done

partition-graph: partition-traces
	$(COBBLE) cobble-experimental-partition-graph --extents $(PARTITION_DIR)/extents.jsonl --traces $(PARTITION_DIR)/traces --links $(PARTITION_DIR)/combine/links.jsonl --barrier $(PARTITION_BARRIER) --fanout-limit $(PARTITION_FANOUT) --out $(PARTITION_DIR)/graph.json

partition-clusters: partition-graph
	$(COBBLE) cobble-experimental-partition-clusters --graph $(PARTITION_DIR)/graph.json --out $(PARTITION_DIR)/clusters.json --report $(PARTITION_DIR)/clusters.md

partition-render: partition-clusters
	$(COBBLE) cobble-experimental-partition-render --graph $(PARTITION_DIR)/graph.json --clusters $(PARTITION_DIR)/clusters.json --out $(PARTITION_DIR)/partition.html

# squall's Db2 test database (official icr.io image). The compose project stays
# squall/, so the squall-db2 container and its named volume are the same ones.
#
# IMPORTANT: keep the container RUNNING between test runs. The full first init
# is slow (minutes; much slower under amd64 emulation on Apple Silicon), so you
# pay it ONCE. `db2-up` is idempotent: it returns immediately if the container is
# already healthy. Do NOT `compose down` between runs — that removes the
# container (and the db2inst1 user in its filesystem), forcing a full re-init on
# the next up even though the named volume persists the data. Use `db2-stop`
# only when you actually want it off; `db2-clean` for a full reset.
db2-up:
	$(DB2_COMPOSE) up -d db2
	@echo "Waiting for DB2 healthy (first init can take several minutes; fast if already up)..."
	@for i in $$(seq 1 160); do \
	  status=$$(docker inspect -f '{{.State.Health.Status}}' squall-db2 2>/dev/null); \
	  if [ "$$status" = "healthy" ]; then echo "DB2 healthy."; exit 0; fi; \
	  if [ "$$status" = "unhealthy" ]; then echo "DB2 unhealthy:"; docker logs --tail 80 squall-db2; exit 1; fi; \
	  sleep 10; \
	done; \
	echo "DB2 did not become healthy in time:"; docker logs --tail 80 squall-db2; exit 1

# Create and seed CardDemo's Db2 schema. Deliberately its OWN target, not a flag
# on the server: this is the only thing that issues DROP TABLE, and a server does
# not need that authority on every routine start. Calls the same apply_schema the
# integration fixture calls, so the green screen cannot show data the tests never
# exercised.
db2-seed:
	@FORGE_ROOT=$(CURDIR) SQUALL_DIR=squall sh -c '. ./carddemo-env.sh >/dev/null 2>&1; . tests/integration/db2_env.sh >/dev/null 2>&1; uv run --no-sync python -m red_dragon_forge.carddemo_db2_seed'

# Connect-and-query, because `docker ps` reports the container healthy while the
# instance inside is dead -- every Db2 test then fails SQL30081N with nothing
# obviously wrong (forge-zka). Also reports the seeded row count, which says
# whether `make db2-seed` has run.
db2-status:
	@FORGE_ROOT=$(CURDIR) SQUALL_DIR=squall sh -c '. ./bridge-env.sh >/dev/null 2>&1; . squall/db2/dsn-env.sh >/dev/null 2>&1; uv run --no-sync python -m red_dragon_forge.db2_status'

# Restart the Db2 instance without re-initialising. Under emulation db2sysc's
# private memory grows past INSTANCE_MEMORY until the VM kills it, leaving the
# container up and tests failing with SQL30081N (docs/how-to/db2.md).
# A restart revives a killed instance and resets the growth; the forge test hook
# runs it before the root suite.
db2-restart:
	docker exec squall-db2 bash -lc "su - db2inst1 -c 'db2 force applications all >/dev/null 2>&1; db2stop force; db2start'"
	@echo "DB2 restarted; verifying TCP listener..."
	@docker exec squall-db2 bash -c '(exec 3<>/dev/tcp/localhost/50000)' && echo "TCP listener up." || { echo "TCP still down"; exit 1; }

# Stop but KEEP the container + volume (re-up still re-runs DB2's configure phase,
# so prefer leaving it up). Removes nothing.
db2-stop:
	$(DB2_COMPOSE) stop db2

# Full reset: remove the container AND the named volume (next up re-inits).
db2-clean:
	$(DB2_COMPOSE) down -v
