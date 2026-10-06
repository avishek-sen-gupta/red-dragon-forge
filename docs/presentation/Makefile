# Regenerate the deck's evidence under artifacts/. Run from this directory.
# Needs the bridge JARs (root `make jar`), hlasm_export, and for db2 a running Db2
# (`make -C ../../squall db2-up`). Artifacts are committed, so presenting needs none of this.

ROOT := $(abspath ../..)
export PROLEAP_BRIDGE_JAR ?= $(ROOT)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
export CARDDEMO_HOME ?= $(ROOT)/vendor/carddemo/app

REVEAL_VERSION := 6.0.2

.PHONY: vendor artifacts cobble srccfg cobble-features cics headless jcl db2 serve

# reveal.js is fetched rather than versioned; the deck needs only these dist files.
vendor: vendor/reveal.js/reveal.js

vendor/reveal.js/reveal.js:
	rm -rf .reveal-pkg && mkdir -p .reveal-pkg vendor/reveal.js/plugin
	cd .reveal-pkg && npm pack reveal.js@$(REVEAL_VERSION) --silent && tar -xzf reveal.js-$(REVEAL_VERSION).tgz
	cp .reveal-pkg/package/dist/reset.css .reveal-pkg/package/dist/reveal.css .reveal-pkg/package/dist/reveal.js .reveal-pkg/package/LICENSE vendor/reveal.js/
	cp .reveal-pkg/package/dist/plugin/notes.js vendor/reveal.js/plugin/
	rm -rf .reveal-pkg

artifacts: cobble srccfg cobble-features cics headless jcl db2

cobble:
	cd $(ROOT) && bash docs/presentation/capture/cobble.sh

srccfg: cobble
	cd $(ROOT) && bash docs/presentation/capture/srccfg.sh

cobble-features: cobble
	cd $(ROOT) && bash docs/presentation/capture/cobble_features.sh

cics:
	cd $(ROOT) && uv run --no-sync python docs/presentation/capture/cics_flow.py
	cd $(ROOT)/cobble && for f in html text; do uv run --no-sync python -m cobble.bms_render --config config/carddemo.toml --values ../docs/presentation/artifacts/cics/0*.json --format $$f --out-dir ../docs/presentation/artifacts/cics; done

headless:
	cd $(ROOT) && bash docs/presentation/capture/headless.sh

jcl:
	cd $(ROOT) && bash docs/presentation/capture/jcl.sh

db2:
	cd $(ROOT) && SQUALL_DIR=squall . squall/db2/dsn-env.sh && uv run --no-sync python docs/presentation/capture/db2_inqcust_capture.py

serve: vendor
	python3 -m http.server 8000 --bind 127.0.0.1
