#!/bin/sh
# Runs the demo pack on a database and writes, into one directory, each question's findings as a table and the WebGL page of the graph and its dataflow paths.
set -eu
[ $# -eq 2 ] || { echo "usage: demo.sh DATABASE OUTPUT-DIR" >&2; exit 2; }
DB=$(cd "$1" && pwd)
mkdir -p "$2"
OUT=$(cd "$2" && pwd)
RESULTS="$DB/results/forge/cobol-demo"
cd "$(dirname "$0")"
./tools/codeql/codeql database run-queries "$DB" ql/demo --additional-packs=tools/ql:ql --threads=0
for query in ReadToWriteFindings ReadToDisplayFindings; do
  ./tools/codeql/codeql bqrs decode --format=text "$RESULTS/$query.bqrs" > "$OUT/$query.txt"
  echo "$OUT/$query.txt"
done
mkdir -p "$OUT/results"
for query in CfgNodes CfgEdges ReadToWriteSteps ReadToDisplaySteps; do
  ./tools/codeql/codeql bqrs decode --format=json "$RESULTS/$query.bqrs" > "$OUT/results/$query.json"
done
cd ../cobble
uv run --no-sync cobble-experimental-codeql-demo --results "$OUT/results" --output "$OUT/graph.html"
