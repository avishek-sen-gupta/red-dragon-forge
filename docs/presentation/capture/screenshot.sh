#!/usr/bin/env bash
# Screenshot one self-contained HTML page (WebGL included) with headless Chrome.
# Usage: screenshot.sh <page.html> <out.png> [width height]. CHROME overrides the binary.
set -euo pipefail

page="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
out="$2"
width="${3:-1920}"
height="${4:-1200}"
chrome="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

"$chrome" --headless=new --disable-gpu-sandbox --use-angle=swiftshader --enable-unsafe-swiftshader \
  --hide-scrollbars --window-size="$width,$height" --virtual-time-budget=15000 \
  --screenshot="$out" "file://$page" 2>/dev/null
test -s "$out"
echo "screenshot: $out"
