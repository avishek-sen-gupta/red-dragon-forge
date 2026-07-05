#!/usr/bin/env bash
# Rebuild everything cicada needs to run end to end:
#   1. the vendored red-dragon submodule (recursive, incl. proleap-cobol-parser)
#   2. the ProLeap bridge fat JAR, from source (parser install -> bridge package)
#   3. the hlasm_export binary (BMS macro assembler) — built only if missing
#   4. the Python environment (uv sync)
#
# Run this after bumping the red-dragon submodule or changing the Java/bridge
# sources. The bridge JAR is a gitignored build product, so it must be rebuilt
# locally; cicada's COBOL/CICS steps need it via PROLEAP_BRIDGE_JAR. red-dragon's
# proleap-bridge/build.sh does a clean `mvn package`, so the JAR is always
# rebuilt from the current submodule source (no stale-JAR mismatch).
#
# hlasm_export is heavy and unaffected by red-dragon bumps, so it is built only
# when absent — force a rebuild with `make hlasm-force` when its sources change.
#
# Usage: ./build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
RD="$ROOT/../vendor/red-dragon"
JAR="$RD/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
HLASM="$ROOT/third-party/che-che4z-lsp-for-hlasm-fork/build/bin/hlasm_export"

echo "==> Initialising submodules (recursive)..."
git -C "$ROOT" submodule update --init --recursive

echo "==> Building the ProLeap bridge JAR (proleap-cobol-parser + bridge)..."
( cd "$RD/proleap-bridge" && ./build.sh )
test -f "$JAR" || { echo "ERROR: bridge JAR not produced at $JAR" >&2; exit 1; }

if [ -x "$HLASM" ]; then
  echo "==> hlasm_export already built (skipping; 'make hlasm-force' to rebuild)."
else
  echo "==> Building the hlasm_export binary..."
  ( cd "$ROOT/third-party/che-che4z-lsp-for-hlasm-fork" && ./build.sh )
fi

echo "==> Syncing the Python environment (uv)..."
( cd "$ROOT" && uv sync )

echo
echo "==> Done."
echo "    ProLeap bridge JAR: $JAR"
echo "    hlasm_export:       $HLASM"
echo "    Run the suite with: make test"
