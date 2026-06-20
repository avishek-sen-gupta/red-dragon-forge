#!/usr/bin/env bash
# Rebuild everything jackal needs to run end to end:
#   1. the vendored red-dragon submodule (recursive, incl. proleap-cobol-parser)
#   2. the ProLeap bridge fat JAR, from source (parser install -> bridge package)
#   3. the Python environment (uv sync, with red-dragon editable)
#
# Run this after bumping the red-dragon submodule or changing the Java/bridge
# sources. The bridge JAR is a gitignored build product, so it must be rebuilt
# locally; jackal's COBOL steps need it via PROLEAP_BRIDGE_JAR.
#
# Usage: ./build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
RD="$ROOT/vendor/red-dragon"
JAR="$RD/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"

echo "==> Initialising the red-dragon submodule (recursive)..."
git -C "$ROOT" submodule update --init --recursive

echo "==> Building the ProLeap bridge JAR (proleap-cobol-parser + bridge)..."
( cd "$RD/proleap-bridge" && ./build.sh )

test -f "$JAR" || { echo "ERROR: bridge JAR not produced at $JAR" >&2; exit 1; }

echo "==> Syncing the Python environment (uv)..."
( cd "$ROOT" && uv sync )

echo
echo "==> Done."
echo "    Bridge JAR: $JAR"
echo "    Run the suite with:"
echo "      PROLEAP_BRIDGE_JAR=\"$JAR\" uv run pytest -q"
