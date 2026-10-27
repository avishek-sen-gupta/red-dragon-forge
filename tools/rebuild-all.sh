#!/usr/bin/env bash
# Rebuilds every cobble static-analysis artefact for one corpus config into one directory.
set -euo pipefail

usage() {
  echo "usage: tools/rebuild-all.sh CONFIG OUT_DIR [SWEEPS]" >&2
  echo "  CONFIG   corpus TOML, relative to cobble/ (e.g. config/carddemo-partition.toml)" >&2
  echo "  OUT_DIR  where every artefact goes; created if missing, files in it overwritten" >&2
  echo "  SWEEPS   the fixpoint's --sweeps; omit for its worklist walk" >&2
  exit 2
}

[ $# -ge 2 ] || usage
CONFIG=$1
OUT=$(mkdir -p "$2" && cd "$2" && pwd)
SWEEPS=${3:-}
FORGE=$(cd "$(dirname "$0")/.." && pwd)
cd "$FORGE/cobble"
ASG=$(uv run --no-sync python -c "from pathlib import Path; from cobble.corpus_config import load_corpus_config; print(load_corpus_config(Path('$CONFIG')).asg_dir)")

step() {
  echo
  echo "=== $(date +%H:%M:%S) $*"
}

run() {
  echo "+ $*"
  uv run --no-sync "$@"
}

programs() {
  find "$ASG" -maxdepth 1 -name '*.json' -exec basename {} .json \; | sort
}

step "BMS symbolic copybooks, and the CICS resource definitions synthesised from the programs"
run cobble-sym --config "$CONFIG"
run cobble-csd --config "$CONFIG" --out "$OUT/csd/synthesised.csd"

step "Parse: one ASG per member"
. "$FORGE/bridge-env.sh"
run cobble-parse-corpus --config "$CONFIG" --force

step "Extents, declaring every name a program uses but never declares"
run cobble-extents --asg-dir "$ASG" --out "$OUT/extents.jsonl" --synthesize-undeclared

step "Fixpoint: byte provenance, reaching definitions, dynamic targets"
run cobble-dataflow-fixpoint --asg-dir "$ASG" --extents "$OUT/extents.jsonl" \
  --out-dir "$OUT/fixpoint" --all --force ${SWEEPS:+--sweeps "$SWEEPS"}

step "Combine: cross-program links"
run cobble-dataflow-combine --config "$CONFIG" --fixpoint-dir "$OUT/fixpoint" \
  --out-dir "$OUT/combine" --all --max-hops 5

step "Knowledge graph"
run cobble-build --config "$CONFIG" --output "$OUT/knowledge-graph.jsonl" \
  --dynamic-call-targets "$OUT/combine/targets.jsonl"
run cobble-render-webgl --graph "$OUT/knowledge-graph.jsonl" --out "$OUT/knowledge-graph.html"

step "CFG closures, one per program, with their pages and field accesses"
mkdir -p "$OUT/srccfg"
printf '[srccfg]\nasg_dir = "%s"\n' "$ASG" > "$OUT/srccfg/srccfg.toml"
for program in $(programs); do
  run cobble-srccfg-build --config "$OUT/srccfg/srccfg.toml" "$program" \
    --dynamic-call-targets "$OUT/combine/targets.jsonl" --output "$OUT/srccfg/cfg-$program.jsonl"
  run cobble-srccfg-webgl --cfg "$OUT/srccfg/cfg-$program.jsonl" --output "$OUT/srccfg/cfg-$program.html"
  run cobble-fields-access --cfg "$OUT/srccfg/cfg-$program.jsonl" --asg-dir "$ASG" \
    --out "$OUT/accesses/$program.jsonl"
  run cobble-viz-callgraph --graph "$OUT/knowledge-graph.jsonl" --cfg "$OUT/srccfg/cfg-$program.jsonl" \
    --out "$OUT/viz/$program"
  run cobble-viz-sequence --cfg "$OUT/srccfg/cfg-$program.jsonl" --out "$OUT/viz/$program"
done

step "Name-level dependency graph"
printf '[output]\nasg_dir = "%s"\ngraph_dir = "%s"\n' "$ASG" "$OUT/depgraph" > "$OUT/depgraph.toml"
run cobble-depgraph --config "$OUT/depgraph.toml"
run cobble-depgraph-render --config "$OUT/depgraph.toml"

step "BMS maps"
run cobble-bms-metadata --config "$CONFIG" --output "$OUT/bms/metadata.json"
run cobble-bms-render --config "$CONFIG" --format html --out-dir "$OUT/bms"

step "Partition graph, its file-site census and its pages"
run cobble-experimental-partition-graph --extents "$OUT/extents.jsonl" --fixpoint "$OUT/fixpoint" \
  --links "$OUT/combine/links.jsonl" --knowledge-graph "$OUT/knowledge-graph.jsonl" \
  --targets "$OUT/combine/targets.jsonl" --barrier fanout --fanout-limit 8 --out "$OUT/graph.jsonl"
run cobble-experimental-partition-file-sites --fixpoint "$OUT/fixpoint" \
  --knowledge-graph "$OUT/knowledge-graph.jsonl" --targets "$OUT/combine/targets.jsonl"
run cobble-experimental-partition-render --graph "$OUT/graph.jsonl" --out "$OUT/render"

step "Aggregates: exact classes, the field matrix, its factors and their scores"
run cobble-experimental-aggregate-unify --graph "$OUT/graph.jsonl" --out "$OUT/aggregates/unified.jsonl"
run cobble-experimental-aggregate-matrix --defs "$OUT/fixpoint/defs.jsonl" --extents "$OUT/extents.jsonl" \
  --unified "$OUT/aggregates/unified.jsonl" \
  --out-matrix "$OUT/aggregates/matrix.npz" --out-meta "$OUT/aggregates/meta.json"
run cobble-experimental-aggregate-decompose --matrix "$OUT/aggregates/matrix.npz" \
  --meta "$OUT/aggregates/meta.json" --min-occurrences 4 2 --k 30 10 --out-dir "$OUT/aggregates/decompose"
run cobble-experimental-aggregate-class-share --matrix "$OUT/aggregates/matrix.npz" \
  --meta "$OUT/aggregates/meta.json" --unified "$OUT/aggregates/unified.jsonl" \
  --graph "$OUT/graph.jsonl" --min-occurrences 4 2
run cobble-experimental-aggregate-scorecard --matrix "$OUT/aggregates/matrix.npz" \
  --meta "$OUT/aggregates/meta.json" --unified "$OUT/aggregates/unified.jsonl" \
  --min-occurrences 4 2 --k 30 10

step "Done: every artefact is under $OUT"
