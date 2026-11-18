#!/bin/sh
# The facts come from cobble: parse the corpus (members already in the ASG cache are skipped), then write TRAP.
set -eu
CONFIG="${COBOL_CORPUS_CONFIG:-$(pwd)/cobol-corpus.toml}"
cd "$CODEQL_EXTRACTOR_COBOL_ROOT/../../.."
. ./bridge-env.sh
cd cobble
uv run --no-sync cobble-parse-corpus --config "$CONFIG"
exec uv run --no-sync cobble-experimental-codeql-facts --config "$CONFIG" \
  --trap-dir "$CODEQL_EXTRACTOR_COBOL_TRAP_DIR" \
  --archive-dir "$CODEQL_EXTRACTOR_COBOL_SOURCE_ARCHIVE_DIR"
