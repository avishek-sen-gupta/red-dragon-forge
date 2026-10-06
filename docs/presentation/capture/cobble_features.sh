#!/usr/bin/env bash
# Evidence for three Cobble features on CardDemo: byte-level field queries, the checks for a
# new corpus (copybooks, COBOL, JCL, a rebuilt CSD), and recorded path sampling animated.
# Reads what capture/cobble.sh leaves in cobble/out-presentation (the whole-corpus fixpoint,
# the extents table, the combine's targets) and the ASG cache in cobble/out-parsed.
# Writes artifacts/cobble/{fields,onboarding,pathwalk}/; work files go to a temp dir.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
ART="$ROOT/docs/presentation/artifacts/cobble"
PRES="$ROOT/cobble/out-presentation"
TMP="${TMPDIR:-/tmp}"
WORK="$(mktemp -d "${TMP%/}/cobble-features.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$ART/fields" "$ART/onboarding" "$ART/pathwalk"
cd "$ROOT/cobble"
. "$ROOT/bridge-env.sh"
for f in "$PRES/fields-all/graph.jsonl" "$PRES/extents-input.jsonl" "$PRES/combined/targets.jsonl"; do
  [[ -f "$f" ]] || { echo "$f missing: run capture/cobble.sh (make cobble) first" >&2; exit 1; }
done

summary() { tr '\r' '\n' | grep -v '%|' | grep -v '^$' | sed -e "s#$WORK/##g" -e "s#$ROOT/##g" || true; }

echo "== byte-level field queries (COACTVWC)"
fq() {
  echo "\$ cobble-dataflow-fixpoint-query $1 $2 --fixpoint-dir out-presentation/fields-all --extents out-presentation/extents-input.jsonl"
  uv run --no-sync cobble-dataflow-fixpoint-query "$1" "$2" \
    --fixpoint-dir "$PRES/fields-all" --extents "$PRES/extents-input.jsonl" 2>/dev/null
}
{
  fq extents COACTVWC.WS-CARD-RID-ACCT-ID-X
  fq writers COACTVWC.WS-CARD-RID-ACCT-ID-X
  fq readers COACTVWC.WS-CARD-RID-ACCT-ID
  fq overlapping COACTVWC.WS-CARD-RID-ACCT-ID-X
  fq contains COACTVWC.WS-XREF-RID
} > "$ART/fields/COACTVWC-acct-rid-redefines.txt"
{
  fq writers COACTVWC.ACCT-CURR-BAL
  fq readers COACTVWC.ACCT-CURR-BAL
  fq writers COACTVWC.CDEMO-ACCT-ID
} > "$ART/fields/COACTVWC-group-children.txt"
grep -nE "WS-CARD-RID-ACCT-ID|INTO +\(ACCOUNT-RECORD\)|ACCT-CURR-BAL|INITIALIZE CC-WORK-AREA|^ +WS-MISC-STORAGE *$|DFHCOMMAREA \(1:LENGTH OF CARDDEMO-COMMAREA\)" \
  "$ROOT/vendor/carddemo/app/cbl/COACTVWC.cbl" | sed 's/ *$//' > "$ART/fields/COACTVWC-source-lines.txt"

uv run --no-sync cobble-srccfg-build COACTVWC --config <(printf '[srccfg]\nasg_dir = "%s"\nout_dir = "%s"\n' \
  "$ROOT/cobble/out-parsed" "$WORK/srccfg") --output "$WORK/cfg-COACTVWC.jsonl" > /dev/null 2>&1
uv run --no-sync cobble-fields-access --cfg "$WORK/cfg-COACTVWC.jsonl" --asg-dir out-parsed \
  --out "$WORK/access-COACTVWC.jsonl" 2>&1 | tail -1 | summary > "$ART/fields/access-COACTVWC-build.txt"
{
  echo "\$ grep -c '\"field\":\"WS-CARD-RID-ACCT-ID\"' access-COACTVWC.jsonl   # sites naming it"
  grep -c '"field":"WS-CARD-RID-ACCT-ID"' "$WORK/access-COACTVWC.jsonl" || true
  for f in COACTVWC.WS-CARD-RID-ACCT-ID COACTVWC.ACCT-CURR-BAL; do
    echo "\$ cobble-access-query $f --accesses access-COACTVWC.jsonl --extents out-presentation/extents-input.jsonl"
    uv run --no-sync cobble-access-query "$f" --accesses "$WORK/access-COACTVWC.jsonl" \
      --extents "$PRES/extents-input.jsonl" 2>/dev/null
  done
} > "$ART/fields/access-COACTVWC.txt"

echo "== checks for a new corpus"
{
  echo "\$ diagnose-copybooks --config config/carddemo.toml"
  uv run --no-sync diagnose-copybooks --config config/carddemo.toml --output "$ART/onboarding/missing-copybooks.json" 2>&1 | summary
} > "$ART/onboarding/diagnose-copybooks.txt"

# The same corpus, with only the copybook directories CardDemo ships: cobble's own
# cics-copybooks/ (IBM-supplied members) and sym/ (generated) are left out, and an empty
# stub directory is listed so that --fix has somewhere it is allowed to write.
mkdir -p "$WORK/stubs"
uv run --no-sync python - config/carddemo.toml "$WORK/carddemo-shipped-copybooks.toml" "$WORK/stubs" <<'PY'
import pathlib, re, sys
src, dst, stubs = sys.argv[1:]
text = pathlib.Path(src).read_text()
dirs = f'copybook_dirs = [\n  "../vendor/carddemo/app/cpy",\n  "../vendor/carddemo/app/cpy-bms",\n  "{stubs}",\n]'
pathlib.Path(dst).write_text(re.sub(r"copybook_dirs = \[.*?\]", dirs, text, count=1, flags=re.S))
PY
{
  echo "\$ diagnose-copybooks --config carddemo-shipped-copybooks.toml   # copybook_dirs: app/cpy, app/cpy-bms, stubs/"
  uv run --no-sync diagnose-copybooks --config "$WORK/carddemo-shipped-copybooks.toml" \
    --output "$ART/onboarding/missing-copybooks-shipped-dirs.json" 2>&1 | summary
  echo
  echo "\$ diagnose-copybooks --config carddemo-shipped-copybooks.toml --fix stubs/"
  uv run --no-sync diagnose-copybooks --config "$WORK/carddemo-shipped-copybooks.toml" --fix "$WORK/stubs" 2>&1 >/dev/null \
    | summary | tail -5
  echo
  for stub in "$WORK"/stubs/*; do echo "\$ cat stubs/$(basename "$stub")"; cat "$stub"; done
  echo
  echo "\$ diagnose-copybooks --config carddemo-shipped-copybooks.toml"
  uv run --no-sync diagnose-copybooks --config "$WORK/carddemo-shipped-copybooks.toml" 2>&1 >/dev/null | summary
} > "$ART/onboarding/diagnose-copybooks-shipped-dirs.txt"

{
  echo "\$ diagnose-cobol --config config/carddemo.toml"
  uv run --no-sync diagnose-cobol --config config/carddemo.toml --output "$ART/onboarding/unparseable-cobol.json" 2>&1 | summary
} > "$ART/onboarding/diagnose-cobol.txt"
{
  echo "\$ diagnose-jcl --config config/carddemo.toml"
  uv run --no-sync diagnose-jcl --config config/carddemo.toml --output "$ART/onboarding/unparseable-jcl.json" 2>&1 | summary
} > "$ART/onboarding/diagnose-jcl.txt"

{
  echo "\$ cobble-csd --config config/carddemo.toml --out synthetic.csd"
  uv run --no-sync cobble-csd --config config/carddemo.toml --out "$ART/onboarding/synthetic.csd" 2>&1 \
    | sed "s#$ART/onboarding/##"
} > "$ART/onboarding/cobble-csd.txt"
sed "s#^csd_files = .*#csd_files = [\"$ART/onboarding/synthetic.csd\"]#" config/carddemo.toml > "$WORK/carddemo-synthetic-csd.toml"
uv run --no-sync cobble-build --config "$WORK/carddemo-synthetic-csd.toml" --output "$WORK/carddemo-synthetic-csd.jsonl" \
  --dynamic-call-targets "$PRES/combined/targets.jsonl" > "$WORK/build-synthetic-csd.log" 2>&1
{
  echo "\$ cobble-build --config carddemo-synthetic-csd.toml --output carddemo-synthetic-csd.jsonl --dynamic-call-targets <combined>/targets.jsonl   # csd_files = [synthetic.csd]"
  echo "\$ cobble-compare --graph carddemo-synthetic-csd.jsonl"
  uv run --no-sync cobble-compare --graph "$WORK/carddemo-synthetic-csd.jsonl" 2>&1 || true
} > "$ART/onboarding/compare-synthetic-csd.txt"

echo "== recorded path sampling, animated (COACTVWC)"
{
  echo "\$ cobble-fields-trace COACTVWC --asg-dir out-parsed --out COACTVWC-trace.jsonl --record-paths COACTVWC-paths.jsonl --force"
  uv run --no-sync cobble-fields-trace COACTVWC --asg-dir out-parsed --out "$WORK/COACTVWC-trace.jsonl" \
    --record-paths "$WORK/COACTVWC-paths.jsonl" --force 2>&1 | grep -v "^reaching_defs"
} > "$ART/pathwalk/COACTVWC-trace.txt"
tail -2 "$ART/pathwalk/COACTVWC-trace.txt" > "$ART/pathwalk/COACTVWC-trace-summary.txt"
VARS=CARDDEMO-COMMAREA,CDEMO-ACCT-ID,CDEMO-TO-PROGRAM
{
  echo "\$ cobble-viz-pathwalk --cfg cfg-COACTVWC.jsonl --paths COACTVWC-paths.jsonl --vars $VARS --output COACTVWC-pathwalk.html"
  uv run --no-sync cobble-viz-pathwalk --cfg "$WORK/cfg-COACTVWC.jsonl" --paths "$WORK/COACTVWC-paths.jsonl" \
    --vars "$VARS" --output "$ART/pathwalk/COACTVWC-pathwalk.html" 2>&1 | sed "s#$ART/pathwalk/##"
} > "$ART/pathwalk/COACTVWC-pathwalk.txt"

echo "done: $ART/fields $ART/onboarding $ART/pathwalk"
