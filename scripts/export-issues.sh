#!/usr/bin/env bash
#
# Export the Beads issue graph to a tracked, diffable JSONL snapshot.
#
# WHY THIS IS A SCRIPT, NOT A PRE-COMMIT HOOK:
#   The export must happen BEFORE a commit so the snapshot is staged with the
#   change that touched the issues. A pre-commit hook runs *during* the commit,
#   after staging — regenerating the file there would either leave the staged
#   snapshot stale or fight pre-commit's stash/restore of unstaged files. So
#   this is a deliberate pre-commit STEP you run by hand:
#
#       scripts/export-issues.sh && git add beads/issues.jsonl
#
# WHAT IS / ISN'T TRACKED:
#   .beads/        -> the local Dolt working DB (gitignored, rebuildable)
#   beads/issues.jsonl -> this portable snapshot (tracked; the source of truth in git)
#
# REBUILD THE LOCAL DB ON A FRESH CLONE:
#       bd import beads/issues.jsonl
#
# Output is sorted by issue id with sorted keys so diffs show only real changes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT/beads"
OUT="$OUT_DIR/issues.jsonl"
mkdir -p "$OUT_DIR"

cd "$ROOT"
bd export \
  | python3 -c "import sys, json
rows = [json.loads(line) for line in sys.stdin if line.strip()]
for row in sorted(rows, key=lambda r: str(r.get('id', ''))):
    print(json.dumps(row, sort_keys=True, ensure_ascii=False))" \
  > "$OUT"

echo "wrote $OUT ($(wc -l < "$OUT" | tr -d ' ') issues)"
