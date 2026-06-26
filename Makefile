# Squall local development tasks.
#
# `make jar`       — build ALL Java artefacts: the ProLeap bridge (parser +
#                    bridge, from the vendored red-dragon submodule). Skipped if
#                    already built; use `make jar-force` after a red-dragon bump.
# `make build`     — ./build.sh: force-rebuild the JAR + uv sync (uniform across
#                    cicada/jackal/squall).
# `make test`      — full suite (needs the ProLeap JAR; integration also needs
#                    SQUALL_DB2_DSN for the Db2 contract tests).
#
# Override any path via the environment.
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar

PYTEST       = uv run --no-sync python -m pytest
PYTEST_PATHS ?= tests/
PYTEST_ARGS  ?=

.PHONY: help setup build python jar jar-force test test-unit fmt lint db2-up db2-restart db2-stop db2-clean

help:
	@echo "make setup       - init submodules + build all Java + uv sync (run once after clone)"
	@echo "make jar         - build all Java: ProLeap bridge (parser+bridge) (skipped if built)"
	@echo "make jar-force   - force-rebuild all Java artefacts"
	@echo "make build       - ./build.sh: force-rebuild the JAR + uv sync"
	@echo "make python      - uv sync (install / refresh Python deps)"
	@echo "make test        - full suite (needs ProLeap JAR + SQUALL_DB2_DSN for Db2 tests)"
	@echo "make test-unit   - unit tests only"
	@echo "make fmt         - black-format squall + tests"
	@echo "make lint        - import-linter architectural contracts"
	@echo ""
	@echo "  PROLEAP_BRIDGE_JAR = $(PROLEAP_BRIDGE_JAR)"

setup:
	git submodule update --init --recursive
	$(MAKE) build

python:
	uv sync

# ProLeap bridge = the red-dragon submodule's parser + the bridge (build.sh does both).
$(PROLEAP_BRIDGE_JAR):
	cd vendor/red-dragon/proleap-bridge && ./build.sh

jar: $(PROLEAP_BRIDGE_JAR)

jar-force:
	cd vendor/red-dragon/proleap-bridge && ./build.sh

build:
	./build.sh

test: jar
	. db2/dsn-env.sh && $(PYTEST) $(PYTEST_PATHS) $(PYTEST_ARGS)

# DB2 test database via docker-compose (official icr.io image).
#
# IMPORTANT: keep the container RUNNING between test runs. The full first init
# is slow (minutes; much slower under amd64 emulation on Apple Silicon), so you
# pay it ONCE. `db2-up` is idempotent: it returns immediately if the container is
# already healthy. Do NOT `compose down` between runs — that removes the
# container (and the db2inst1 user in its filesystem), forcing a full re-init on
# the next up even though the named volume persists the data. Use `db2-stop`
# only when you actually want it off; `db2-clean` for a full reset.
db2-up:
	docker compose up -d db2
	@echo "Waiting for DB2 healthy (first init can take several minutes; fast if already up)..."
	@until [ "$$(docker inspect -f '{{.State.Health.Status}}' squall-db2 2>/dev/null)" = "healthy" ]; do \
	  sleep 5; \
	  [ "$$(docker inspect -f '{{.State.Health.Status}}' squall-db2 2>/dev/null)" = "unhealthy" ] && { echo "DB2 unhealthy — see 'docker logs squall-db2'"; exit 1; }; \
	done
	@echo "DB2 healthy."

# Rebind DB2's TCP listener without re-initialising. Under emulation the listener
# can occasionally drop (port 50000 stops accepting inside the container) while a
# local connect still works — tests then fail with SQL30081N. This rebinds it.
db2-restart:
	docker exec squall-db2 bash -lc "su - db2inst1 -c 'db2 force applications all >/dev/null 2>&1; db2stop force; db2start'"
	@echo "DB2 restarted; verifying TCP listener..."
	@docker exec squall-db2 bash -c '(exec 3<>/dev/tcp/localhost/50000)' && echo "TCP listener up." || { echo "TCP still down"; exit 1; }

# Stop but KEEP the container + volume (re-up still re-runs DB2's configure phase,
# so prefer leaving it up). Removes nothing.
db2-stop:
	docker compose stop db2

# Full reset: remove the container AND the named volume (next up re-inits).
db2-clean:
	docker compose down -v

test-unit:
	$(PYTEST) tests/unit $(PYTEST_ARGS)

fmt:
	uv run --no-sync python -m black squall tests

lint:
	uv run --no-sync lint-imports
