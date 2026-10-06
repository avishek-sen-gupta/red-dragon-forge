#!/usr/bin/env bash
# Record CardDemo driven through c3270 against cicada-tn3270, as an MP4 and a GIF.
# Outputs: docs/presentation/artifacts/cics/carddemo-3270.{mp4,gif}. Needs the bridge JARs, hlasm_export, c3270, vhs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
. ./carddemo-env.sh

OUT="$ROOT/docs/presentation/artifacts/cics"
MP4="$OUT/carddemo-3270.mp4"
GIF="$OUT/carddemo-3270.gif"
POSTER="$OUT/carddemo-3270-poster.png"
TAPE="$ROOT/docs/presentation/capture/carddemo-3270.tape"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/carddemo-3270.XXXXXX")"
LOG="$WORK/server.log"

vendor_state() {
  git -C "$ROOT/vendor/carddemo" rev-parse HEAD
  git -C "$ROOT/vendor/carddemo" status --porcelain --untracked-files=all
}

stop_server() {
  [ -n "${SERVER:-}" ] && pkill -TERM -P "$SERVER" 2>/dev/null
  [ -n "${SERVER:-}" ] && kill "$SERVER" 2>/dev/null
  wait 2>/dev/null
  rm -rf "$WORK"
}
trap stop_server EXIT

BEFORE="$(vendor_state)"
PORT="$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"

echo "== starting cicada-tn3270 on port $PORT (log: $LOG)"
uv run --no-sync cicada-tn3270 --config cicada/config/carddemo-tn3270.toml --port "$PORT" >"$LOG" 2>&1 &
SERVER=$!

until nc -z 127.0.0.1 "$PORT" 2>/dev/null; do
  kill -0 "$SERVER" 2>/dev/null || { cat "$LOG"; echo "server exited before listening" >&2; exit 1; }
  sleep 1
done

SESSION="$WORK/carddemo.c3270"
cat >"$SESSION" <<SESSION_FILE
c3270.hostname: 127.0.0.1:$PORT
c3270.model: 3279-2-E
c3270.menuBar: false
c3270.keymap: pfkeys
c3270.keymap.pfkeys: \\n\\
  Ctrl<Key>p <Key>3: PF(3)\\n\\
  Ctrl<Key>p <Key>5: PF(5)
SESSION_FILE

echo "== recording $MP4"
mkdir -p "$OUT"
CARDDEMO_C3270_SESSION="$SESSION" vhs -o "$MP4" "$TAPE"

echo "== encoding $GIF"
ffmpeg -loglevel error -y -i "$MP4" \
  -vf "fps=6,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=32[p];[b][p]paletteuse=dither=none" \
  "$GIF"

echo "== poster $POSTER"
ffmpeg -loglevel error -y -ss 3 -i "$MP4" -frames:v 1 "$POSTER"

AFTER="$(vendor_state)"
[ "$BEFORE" = "$AFTER" ] || { echo "vendor/carddemo changed during the recording" >&2; exit 1; }
echo "== vendor/carddemo unchanged"
ls -l "$MP4" "$GIF" "$POSTER"
