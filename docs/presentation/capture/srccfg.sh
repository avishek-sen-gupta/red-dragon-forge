#!/usr/bin/env bash
# Source-CFG evidence: per-program CFGs with reaching conditions, expanded across XCTL/LINK/CALL,
# dynamic targets included. Reads cobble's ASG cache (cobble/out-parsed, written by
# `cobble-parse-corpus`) and the combine's targets.jsonl that capture/cobble.sh leaves in
# cobble/out-presentation/combined; no JVM.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
ART="$ROOT/docs/presentation/artifacts/srccfg"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/srccfg-capture.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$ART"
cd "$ROOT/cobble"
[[ -d out-parsed ]] || { echo "cobble/out-parsed missing: run uv run cobble-parse-corpus --config config/carddemo.toml" >&2; exit 1; }
TARGETS="$ROOT/cobble/out-presentation/combined/targets.jsonl"
[[ -f "$TARGETS" ]] || { echo "$TARGETS missing: run capture/cobble.sh (make cobble) first" >&2; exit 1; }

cat > "$WORK/srccfg.toml" <<EOF
[srccfg]
asg_dir = "$ROOT/cobble/out-parsed"
out_dir = "$WORK/out"
EOF

# The sign-on closure follows dynamic XCTLs too, as the slides show it; COACTVWC is only
# queried within itself, so its closure stays the program and its literal calls.
build() {
  local p="$1"; shift
  { /usr/bin/time -p uv run --no-sync cobble-srccfg-build --config "$WORK/srccfg.toml" \
      "$@" --output "$ART/cfg-$p.jsonl" "$p"; } 2>&1 | tee "$ART/build-$p.txt"
}
build COSGN00C --dynamic-call-targets "$TARGETS"
build COACTVWC

uv run --no-sync python - "$ART" <<'PY'
import collections, json, pathlib, sys

from cobble.dataflow.srccfg.bundle import load_bundle

art = pathlib.Path(sys.argv[1])
summary = {}
for entry in ("COSGN00C", "COACTVWC"):
    bundle = load_bundle(art / f"cfg-{entry}.jsonl")
    summary[entry] = {
        "programs": len(bundle.cfgs),
        "nodes": sum(len(cfg.nodes) for cfg in bundle.cfgs),
        "edges_within_programs": sum(len(cfg.edges) for cfg in bundle.cfgs),
        "calls_between_programs": len(bundle.calls),
        "cfgs": [
            {
                "program": cfg.program,
                "nodes": len(cfg.nodes),
                "edges": len(cfg.edges),
                "node_kinds": dict(collections.Counter(n.kind.name for n in cfg.nodes).most_common()),
            }
            for cfg in bundle.cfgs
        ],
    }
(art / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
PY

uv run --no-sync cobble-srccfg-dot --cfg "$ART/cfg-COSGN00C.jsonl" --output "$ART/cfg-COSGN00C.dot"

# One paragraph of the closure, small enough to read on a slide.
uv run --no-sync python - "$ART" <<'PY'
import pathlib, subprocess, sys
art = pathlib.Path(sys.argv[1])
prefix = '"COSGN00C::READ-USER-SEC-FILE'
lines = (art / "cfg-COSGN00C.dot").read_text().splitlines()
body = [l for l in lines if prefix in l and ("->" not in l or l.count(prefix) == 2)]
dot = (
    "digraph srccfg {\n  rankdir=TB;\n"
    '  node [fontname="Helvetica", fontsize=11];\n  edge [fontname="Helvetica", fontsize=10];\n'
    + "\n".join(body) + "\n}\n"
)
(art / "COSGN00C-READ-USER-SEC-FILE.dot").write_text(dot)
subprocess.run(["dot", "-Tpng", "-Gdpi=110", str(art / "COSGN00C-READ-USER-SEC-FILE.dot"),
                "-o", str(art / "COSGN00C-READ-USER-SEC-FILE.png")], check=True)
PY

q() { uv run --no-sync cobble-srccfg-query "$@"; }
{
  echo "\$ cobble-srccfg-query guards READ-USER-SEC-FILE/1.when.0.0.then.5.then.0 --cfg cfg-COSGN00C.jsonl   # XCTL COADM01C"
  q guards "READ-USER-SEC-FILE/1.when.0.0.then.5.then.0" --cfg "$ART/cfg-COSGN00C.jsonl"
  echo
  echo "\$ cobble-srccfg-query guards READ-USER-SEC-FILE/1.when.0.0.then.5.else.0 --cfg cfg-COSGN00C.jsonl   # XCTL COMEN01C"
  q guards "READ-USER-SEC-FILE/1.when.0.0.then.5.else.0" --cfg "$ART/cfg-COSGN00C.jsonl"
} > "$ART/guards-COSGN00C-xctl.txt"

{
  echo "\$ cobble-srccfg-query provenance CDEMO-USER-ID --max-depth 2 --cfg cfg-COSGN00C.jsonl"
  q provenance CDEMO-USER-ID --max-depth 2 --cfg "$ART/cfg-COSGN00C.jsonl"
} > "$ART/provenance-COSGN00C-CDEMO-USER-ID.txt"

{
  echo "\$ cobble-srccfg-query coassign CC-ACCT-ID --cfg cfg-COACTVWC.jsonl"
  q coassign CC-ACCT-ID --cfg "$ART/cfg-COACTVWC.jsonl"
} > "$ART/coassign-COACTVWC-CC-ACCT-ID.txt"

uv run --no-sync cobble-srccfg-webgl --cfg "$ART/cfg-COSGN00C.jsonl" --output "$ART/cfg-COSGN00C-webgl.html" \
  2>&1 | tee "$ART/webgl-COSGN00C.txt"
bash "$ROOT/docs/presentation/capture/screenshot.sh" "$ART/cfg-COSGN00C-webgl.html" "$ART/cfg-COSGN00C-webgl.png" 1920 1200
echo "srccfg artifacts written to $ART"
