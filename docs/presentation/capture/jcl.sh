#!/usr/bin/env bash
# Capture JCL (jackal) evidence: ACCTFILE -> READACCT chain, PROC/COND demo, and a
# bounded executability survey over every CardDemo job. Outputs: docs/presentation/artifacts/jcl/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

export PROLEAP_BRIDGE_JAR="${PROLEAP_BRIDGE_JAR:-$ROOT/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar}"
export JCL_BRIDGE_JAR="${JCL_BRIDGE_JAR:-$ROOT/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar}"
export CARDDEMO_HOME="${CARDDEMO_HOME:-$ROOT/vendor/carddemo/app}"
SURVEY_TIMEOUT="${SURVEY_TIMEOUT:-120}"

for jar in "$PROLEAP_BRIDGE_JAR" "$JCL_BRIDGE_JAR"; do
  [[ -f "$jar" ]] || { echo "missing bridge JAR: $jar (run make jar)" >&2; exit 1; }
done
[[ -d "$CARDDEMO_HOME/jcl" ]] || { echo "CARDDEMO_HOME has no jcl/: $CARDDEMO_HOME" >&2; exit 1; }

OUT="$ROOT/docs/presentation/artifacts/jcl"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/jcl-capture.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT" "$WORK/chain" "$WORK/demo" "$WORK/survey"
HELPER="$ROOT/docs/presentation/capture/jcl_capture.py"
cp -R "$CARDDEMO_HOME/data/EBCDIC" "$WORK/cli-data"

echo "== jackal CLI: ACCTFILE.jcl"
{
  echo "\$ uv run --no-sync jackal run vendor/carddemo/app/jcl/ACCTFILE.jcl --source-dir ... --data-dir ... --copybook-dir ..."
  uv run --no-sync jackal run "$CARDDEMO_HOME/jcl/ACCTFILE.jcl" \
    --source-dir "$CARDDEMO_HOME/cbl" --data-dir "$WORK/cli-data" \
    --copybook-dir "$CARDDEMO_HOME/cpy"
  echo "exit=$?"
} | tee "$OUT/cli-acctfile.txt"

echo "== chain: ACCTFILE -> READACCT"
uv run --no-sync python "$HELPER" chain "$OUT" "$WORK/chain"

echo "== demo: PROC expansion + COND"
uv run --no-sync python "$HELPER" demo "$OUT" "$WORK/demo"

echo "== survey (timeout ${SURVEY_TIMEOUT}s per job)"
uv run --no-sync python "$HELPER" survey "$OUT" "$WORK/survey" "$SURVEY_TIMEOUT" \
  | tee "$OUT/job-survey.txt"
