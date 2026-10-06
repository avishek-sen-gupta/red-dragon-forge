#!/usr/bin/env bash
# Capture the headless CardDemo test runs as a terminal-style screenshot.
# Outputs: docs/presentation/artifacts/cics/headless-tests.{txt,png}. Needs the bridge JARs and a running Db2.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

OUT="$ROOT/docs/presentation/artifacts/cics"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/headless-capture.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
RAW="$WORK/raw.ansi"
: > "$RAW"

CICADA_CMD="uv run --no-sync python -m pytest tests/integration/cics/test_carddemo_terminal_screen.py -v -n0 --color=yes"
DB2_CMD="uv run --no-sync python -m pytest tests/integration/test_carddemo_db2_headless.py -v --color=yes"

echo "== cicada: CardDemo sign-on and menu, headless"
{
  printf '$ cd cicada && %s\n' "$CICADA_CMD"
  (. "$ROOT/bridge-env.sh" && cd cicada && $CICADA_CMD) || true
  printf '\n'
} >> "$RAW" 2>&1

echo "== forge: CardDemo admin 5/6 on Db2, headless"
{
  printf '$ %s\n' "$DB2_CMD"
  (. "$ROOT/carddemo-env.sh" && . "$ROOT/tests/integration/db2_env.sh" && $DB2_CMD) || true
} >> "$RAW" 2>&1

uv run --no-sync python - "$RAW" "$OUT/headless-tests.txt" "$WORK/headless-tests.html" <<'PY'
import html
import re
import sys
from pathlib import Path

NOISE = re.compile(
    r"^(=+ test session starts|platform |cachedir|rootdir|configfile|plugins|"
    r"collecting|collected|created: |\d+ workers|bringing up nodes|$)"
)
ANSI = re.compile(r"\x1b\[([0-9;]*)m")
COLOURS = {
    "30": "#4d4d4d", "31": "#ff6b6b", "32": "#5fd75f", "33": "#e5c07b",
    "34": "#61afef", "35": "#c678dd", "36": "#56b6c2", "37": "#dcdcdc",
    "90": "#7f7f7f", "91": "#ff8787", "92": "#87ff87", "93": "#ffd787",
    "94": "#87afff", "95": "#d787ff", "96": "#87d7d7", "97": "#ffffff",
}


def plain(line: str) -> str:
    return ANSI.sub("", line)


def keep(line: str) -> bool:
    return not NOISE.match(plain(line))


def span(codes: str, text: str) -> str:
    parts = codes.split(";")
    colour = next((COLOURS[p] for p in parts if p in COLOURS), "")
    bold = "1" in parts
    style = (f"color:{colour};" if colour else "") + ("font-weight:700;" if bold else "")
    body = html.escape(text)
    return f'<span style="{style}">{body}</span>' if style else body


def to_html(line: str) -> str:
    if plain(line).startswith("$ "):
        return f'<span class="prompt">{html.escape(plain(line))}</span>'
    pieces = ANSI.split(line)
    texts = pieces[0::2]
    codes = [""] + pieces[1::2]
    return "".join(span(c, t) for c, t in zip(codes, texts))


raw, txt_out, html_out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
kept = [l for l in Path(raw).read_text().splitlines() if keep(l)]
lines = [part for i, l in enumerate(kept) for part in (["", l] if i and plain(l).startswith("$ ") else [l])]
txt_out.write_text("\n".join(plain(l) for l in lines) + "\n")
body = "\n".join(f'<div class="l">{to_html(l)}</div>' for l in lines)
html_out.write_text(f"""<!doctype html><meta charset="utf-8">
<style>
body {{ margin:0; background:#0d1117; }}
.term {{ margin:0; padding:22px 26px; font:17px/1.45 Menlo, Monaco, "DejaVu Sans Mono", monospace;
  color:#dcdcdc; }}
.l {{ white-space:pre-wrap; overflow-wrap:anywhere; padding-left:4ch; text-indent:-4ch; min-height:1.45em; }}
.prompt {{ color:#5fd75f; font-weight:700; }}
</style>
<div class="term">{body}</div>
""")
PY

bash "$ROOT/docs/presentation/capture/screenshot.sh" "$WORK/headless-tests.html" "$OUT/headless-tests.png" 1200 780
