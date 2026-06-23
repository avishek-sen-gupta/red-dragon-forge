# Squall local development tasks.
#
# `make build` — rebuild the vendored red-dragon ProLeap bridge JAR (from source,
#                always clean) and sync the Python environment. Run this after
#                bumping the red-dragon submodule or changing the bridge sources.
#                Delegates to ./build.sh (uniform across cicada/jackal/squall).

.PHONY: build

build:
	./build.sh
