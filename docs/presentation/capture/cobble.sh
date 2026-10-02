#!/usr/bin/env bash
# Capture Cobble static-analysis evidence for CardDemo into docs/presentation/artifacts/cobble/.
# Run from the repo root. Needs `make setup` (bridge JARs + hlasm_export) and the BMS
# symbolic copybooks (cd cobble && uv run cobble-sym --config config/carddemo.toml).
# Work caches go to cobble/out-parsed, cobble/out and cobble/out-presentation (gitignored).
set -euo pipefail

ROOT="$(pwd)"
test -f "$ROOT/cobble/config/carddemo.toml" || { echo "run from the repo root" >&2; exit 1; }
ART="$ROOT/docs/presentation/artifacts/cobble"
WORK="$ROOT/cobble/out-presentation"
mkdir -p "$ART/viz" "$ART/dataflow" "$ART/screens" "$WORK/viz"
cd "$ROOT/cobble"
. "$ROOT/bridge-env.sh"

# cobble.viz modules are invoked by import: their console scripts are declared in
# cobble/pyproject.toml but absent from the synced venv, and the modules have no __main__.
viz() {
  local module="$1"; shift
  uv run --no-sync python -c "import sys; from cobble.viz.$module import main; sys.argv=['$module', *sys.argv[1:]]; main()" "$@"
}

echo "== parse + build + compare + render (whole-system graph)"
uv run --no-sync cobble-parse-corpus --config config/carddemo.toml 2>&1 | tail -3
# The reference graph includes the dynamic-target edges, so the build reads the
# whole-corpus fixpoint's targets.jsonl.
uv run --no-sync cobble-extents --asg-dir out-parsed --out "$WORK/extents-input.jsonl"
uv run --no-sync cobble-dataflow-fixpoint --asg-dir out-parsed --out-dir "$WORK/fields-all" \
  --extents "$WORK/extents-input.jsonl" --all > /dev/null 2> "$WORK/fixpoint-all.log"
uv run --no-sync cobble-build --config config/carddemo.toml --output out/carddemo.jsonl \
  --dynamic-call-targets "$WORK/fields-all/targets.jsonl" > "$WORK/build.log" 2>&1
grep -A12 "FAILURE" "$WORK/build.log" > "$ART/build-warnings.txt" || true
uv run --no-sync cobble-compare --graph out/carddemo.jsonl 2>&1 | tee "$ART/compare.txt"
grep -q "EMPTY DIFF" "$ART/compare.txt"
uv run --no-sync cobble-render --graph out/carddemo.jsonl
cp out/carddemo.html "$ART/graph.html"

uv run --no-sync python - "$ART/stats.json" <<'PY'
import collections, json, pathlib, sys
rows = [json.loads(l) for l in open("out/carddemo.jsonl") if l.strip()]
nodes = [r for r in rows if r["type"] == "node"]
edges = [r for r in rows if r["type"] == "edge"]
unresolved = collections.Counter(
    n["kind"] for n in nodes if n.get("file_path_reason") == "unresolved"
)
stats = {
    "corpus": "CardDemo (vendor/carddemo)",
    "source": "cobble/out/carddemo.jsonl after cobble-build --config config/carddemo.toml --output out/carddemo.jsonl",
    "total_nodes": len(nodes),
    "total_edges": len(edges),
    "nodes_by_kind": dict(collections.Counter(n["kind"] for n in nodes).most_common()),
    "edges_by_kind": dict(collections.Counter(e["kind"] for e in edges).most_common()),
    "unresolved_nodes_by_kind": dict(unresolved.most_common()),
    "cobol_members_parsed": len(list(pathlib.Path("out-parsed").glob("*.json"))),
}
pathlib.Path(sys.argv[1]).write_text(json.dumps(stats, indent=2) + "\n")
print(json.dumps(stats, indent=2))
PY

echo "== source CFG closures"
cat > "$WORK/srccfg.toml" <<EOF
[srccfg]
asg_dir = "$ROOT/cobble/out-parsed"
out_dir = "$WORK/srccfg"
EOF
for p in COSGN00C COACTVWC; do
  uv run --no-sync cobble-srccfg-build --config "$WORK/srccfg.toml" --output "$WORK/cfg-$p.jsonl" "$p"
done

echo "== call graph + sequence diagrams"
viz callgraph_cmd --graph out/carddemo.jsonl --cfg "$WORK/cfg-COSGN00C.jsonl" --out "$ART/viz/COSGN00C-call-dep.json"
# viz-callgraph keeps only kind == LINK; CardDemo's online flow is all XCTL, so the
# as-shipped graph has no edges. The second variant relabels XCTL edges as LINK in a
# scratch copy of the graph file so the XCTL hand-offs are drawn. Node rows pass through.
uv run --no-sync python - out/carddemo.jsonl "$WORK/graph-xctl-as-link.jsonl" <<'PY'
import json, sys
with open(sys.argv[1]) as src, open(sys.argv[2], "w") as dst:
    for line in src:
        r = json.loads(line)
        if r["type"] == "edge" and r["kind"] == "XCTL":
            r["kind"] = "LINK"
        dst.write(json.dumps(r) + "\n")
PY
viz callgraph_cmd --graph "$WORK/graph-xctl-as-link.jsonl" --cfg "$WORK/cfg-COSGN00C.jsonl" --out "$ART/viz/COSGN00C-call-dep-xctl.json"
viz sequence_cmd --cfg "$WORK/cfg-COSGN00C.jsonl" --entry COSGN00C --out "$ART/viz/COSGN00C-sequences.json"
viz sequence_cmd --cfg "$WORK/cfg-COACTVWC.jsonl" --entry COACTVWC --out "$ART/viz/COACTVWC-sequences.json"
viz render_cmd --input "$ART/viz/COSGN00C-call-dep.json" --mode callgraph --out "$ART/viz/COSGN00C-callgraph.html"
viz render_cmd --input "$ART/viz/COSGN00C-call-dep-xctl.json" --mode callgraph --out "$ART/viz/COSGN00C-callgraph-xctl.html"
viz render_cmd --input "$ART/viz/COSGN00C-sequences.json" --mode top --out "$ART/viz/COSGN00C-sequence-top.html"
viz render_cmd --input "$ART/viz/COSGN00C-sequences.json" --mode program --program COSGN00C --out "$ART/viz/COSGN00C-sequence-program.html"
viz render_cmd --input "$ART/viz/COACTVWC-sequences.json" --mode program --program COACTVWC --out "$ART/viz/COACTVWC-sequence-program.html"

echo "== field-level dataflow"
uv run --no-sync cobble-fields-trace COACTVWC --asg-dir out-parsed --out "$WORK/trace-COACTVWC.jsonl" 2> "$WORK/trace-COACTVWC.log"
tail -2 "$WORK/trace-COACTVWC.log" | tee "$ART/dataflow/trace-COACTVWC-summary.txt"
uv run --no-sync cobble-trace-query backward WS-CARD-RID-ACCT-ID --trace "$WORK/trace-COACTVWC.jsonl" --depth 5 \
  | tee "$ART/dataflow/COACTVWC-acct-rid-backward.txt"

uv run --no-sync cobble-dataflow-fixpoint --asg-dir "$ROOT/cobble/out-parsed" --out-dir "$WORK/fields" \
  --extents "$WORK/extents-input.jsonl" --member COSGN00C COMEN01C COADM01C COACTVWC > "$ART/dataflow/fixpoint-summary.json" 2> "$WORK/fixpoint.log"
grep -v "dequeues," "$WORK/fixpoint.log" > "$ART/dataflow/fixpoint-report.txt"
cp "$WORK/fields/aliases.jsonl" "$ART/dataflow/aliases.jsonl"
uv run --no-sync cobble-dataflow-fixpoint-query reaches COSGN00C.WS-USER-ID --fixpoint-dir "$WORK/fields" \
  --extents "$WORK/extents-input.jsonl" \
  --across-calls --max-hops 2 --depth 6 | tee "$ART/dataflow/COSGN00C-user-id-across-calls.txt"

uv run --no-sync python - "$ART/dataflow" <<'PY'
import html, pathlib, re, sys
out = pathlib.Path(sys.argv[1])
backward = (out / "COACTVWC-acct-rid-backward.txt").read_text()
across = (out / "COSGN00C-user-id-across-calls.txt").read_text()

def node_id(label, ids):
    return ids.setdefault(label, f"n{len(ids)}")

# Origin rows (LITERAL, %CICS-STATE) are leaves of no interest on a slide; a field
# nested under one is attached to the nearest field above it in the tree instead.
ORIGINS = {"LITERAL", "%CICS-STATE"}

def tree_edges(text):
    stack, edges = [], set()
    for line in text.splitlines():
        m = re.match(r"^(\s*)(?:<- )?(\S+)", line)
        if not m or not line.strip():
            continue
        depth, name = len(m.group(1)), m.group(2).split("@")[0]
        while stack and stack[-1][0] >= depth:
            stack.pop()
        parent = next((n for _, n in reversed(stack) if n not in ORIGINS), None)
        if parent and name not in ORIGINS and name != parent:
            edges.add((name, parent))
        stack.append((depth, name))
    return sorted(edges)

def across_edges(text):
    root = text.splitlines()[0].split()[0]
    edges = []
    for line in text.splitlines():
        m = re.match(r"\s*hop (\d+)\s+depth (\d+)\s+(\S+)", line)
        if m:
            edges.append((m.group(1), m.group(2), m.group(3)))
    chain = []
    prev_by_program = {}
    for hop, depth, target in edges:
        prog = target.split(".")[0]
        if hop == "0":
            chain.append((root, target, "MOVE"))
            prev_by_program[root.split(".")[0]] = target
        elif target.endswith("DFHCOMMAREA"):
            chain.append((prev_by_program[root.split(".")[0]], target, "XCTL COMMAREA"))
            prev_by_program[prog] = target
        else:
            chain.append((prev_by_program[prog], target, "MOVE"))
    return chain

def mermaid(lines):
    ids, body = {}, []
    for src, dst, label in lines:
        a, b = node_id(src, ids), node_id(dst, ids)
        body.append(f'  {a} -->|{label}| {b}' if label else f"  {a} --> {b}")
    decl = [f'  {i}["{html.escape(n)}"]' for n, i in ids.items()]
    return "flowchart LR\n" + "\n".join(decl + body)

page = f"""<!doctype html><html><head><meta charset="utf-8"><title>CardDemo field dataflow</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<style>body{{font-family:system-ui,sans-serif;margin:24px;background:#fff}}pre.src{{background:#f5f5f5;padding:12px;font-size:12px;overflow:auto}}h2{{margin-top:32px}}</style>
</head><body>
<h1>Field-level dataflow in CardDemo (derived from cobble query output)</h1>
<h2>1. Sign-on user id crosses XCTL into the menu programs (cobble-dataflow-fixpoint-query reaches --across-calls)</h2>
<pre class="mermaid">{mermaid(across_edges(across))}</pre>
<pre class="src">{html.escape(across)}</pre>
<h2>2. What feeds the account-file read key in COACTVWC (cobble-trace-query backward)</h2>
<pre class="mermaid">{mermaid([(s, d, "") for s, d in tree_edges(backward)])}</pre>
<pre class="src">{html.escape(backward)}</pre>
<script>mermaid.initialize({{startOnLoad:true}});</script>
</body></html>"""
(out / "dataflow.html").write_text(page)
print("wrote", out / "dataflow.html")
PY

echo "== BMS maps rendered empty"
uv run --no-sync python -m cobble.bms_render --config config/carddemo.toml --format html --out-dir "$ART/screens"
ls "$ART/screens"/*.html | wc -l

echo "done: $ART"
