#!/usr/bin/env bash
# Build EVERYTHING from a fresh clone and verify the graph, in one command.
#
#   git clone <repo> cobble && cd cobble && ./build.sh
#
# Steps: fetch submodules (CardDemo corpus + the proleap-cobol-parser fork + the
# che-che4z HLASM fork) -> build the HLASM exporter, the parser fork, and both
# bridge JARs from source -> GENERATE the BMS symbolic copybooks from the .bms
# sources (nothing pre-generated is shipped) -> run the four extractors over the
# corpus -> identity-diff against the reference golden (449/803).
#
# Requires: git, JDK 21+, Maven, CMake, Ninja, LLVM@18 (for hlasm_export), and uv.
set -euo pipefail
cd "$(dirname "$0")"

CONFIG=config/carddemo.yaml

echo "==> [1/5] Fetching submodules (CardDemo corpus + proleap fork + che-che4z HLASM fork)..."
git submodule update --init

echo "==> [2/5] Building tools from source (hlasm_export + proleap fork + both bridge JARs)..."
make tools

echo "==> [3/5] Generating from grammars: the CICS parser (ANTLR) + the BMS copybooks..."
make codegen CONFIG="$CONFIG"

echo "==> [4/5] Extracting the CardDemo knowledge graph..."
make build CONFIG="$CONFIG"

echo "==> [5/5] Verifying against the reference golden (must be 449/803, empty diff)..."
make compare

echo
echo "==> DONE — the standalone port reproduced the production graph (449 nodes / 803 edges)"
echo "    from source: parsers, bridges, and BMS copybooks all built/generated here."
