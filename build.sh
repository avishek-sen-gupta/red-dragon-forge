#!/usr/bin/env bash
# Build EVERYTHING from a fresh clone and verify the graph, in one command.
#
#   git clone <repo> cobble && cd cobble && ./build.sh
#
# Steps: fetch submodules (CardDemo corpus + the proleap-cobol-parser fork) ->
# build the fork (mvn install) + both bridge JARs -> run the four extractors over
# the corpus -> identity-diff the output against the reference golden (449/803).
#
# Requires: git, JDK 21+, Maven, and uv (https://docs.astral.sh/uv/).
set -euo pipefail
cd "$(dirname "$0")"

echo "==> [1/4] Fetching submodules (CardDemo corpus + proleap-cobol-parser fork)..."
git submodule update --init

echo "==> [2/4] Building the fork + both bridge JARs (Maven)..."
make jars

echo "==> [3/4] Extracting the CardDemo knowledge graph..."
make build

echo "==> [4/4] Verifying against the reference golden (must be 449/803, empty diff)..."
make compare

echo
echo "==> DONE — the standalone port reproduced the production graph (449 nodes / 803 edges)."
