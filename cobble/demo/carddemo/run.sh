#!/usr/bin/env bash
# CardDemo through cobble, every generated artefact under output/ in this directory.
set -euo pipefail

export COBBLE_DEMO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COBBLE="$(cd "$COBBLE_DEMO/../.." && pwd)"
OUT="$COBBLE_DEMO/output"
SRCCFG_PROGRAM="${SRCCFG_PROGRAM:-COSGN00C}"

cd "$COBBLE"
. ../bridge-env.sh
run() { echo "==> $*"; uv run --no-sync "$@"; }

run cobble-sym --config "$COBBLE_DEMO/carddemo.toml"
run cobble-parse-corpus --config "$COBBLE_DEMO/carddemo.toml"

run cobble-extents --asg-dir "$OUT/parsed" \
  --out "$OUT/fixpoint/extents.jsonl"
run cobble-dataflow-fixpoint --asg-dir "$OUT/parsed" \
  --out-dir "$OUT/fixpoint" \
  --extents "$OUT/fixpoint/extents.jsonl" --all --force

run cobble-dataflow-combine --config "$COBBLE_DEMO/carddemo.toml" \
  --fixpoint-dir "$OUT/fixpoint" \
  --out-dir "$OUT/combined" --all

run cobble-build --config "$COBBLE_DEMO/carddemo.toml" \
  --output "$OUT/graph/carddemo.jsonl" \
  --dynamic-call-targets "$OUT/combined/targets.jsonl"
run cobble-compare --graph "$OUT/graph/carddemo.jsonl"
run cobble-render-webgl --graph "$OUT/graph/carddemo.jsonl"

run cobble-srccfg-build "$SRCCFG_PROGRAM" --config "$COBBLE_DEMO/srccfg.toml" \
  --dynamic-call-targets "$OUT/combined/targets.jsonl" \
  --output "$OUT/srccfg/$SRCCFG_PROGRAM-closure.jsonl"
run cobble-srccfg-webgl --cfg "$OUT/srccfg/$SRCCFG_PROGRAM-closure.jsonl" \
  --output "$OUT/srccfg/$SRCCFG_PROGRAM-closure.html"
