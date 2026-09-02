# Source this to export SQUALL_DB2_DSN / SQUALL_DB2_DSN2. Sourced from squall/ as
# `. db2/dsn-env.sh`; from another directory (the workspace root) set SQUALL_DIR to
# squall's path so .env is still found.
# The password comes from .env (gitignored) or the environment (CI secret) — it is
# NEVER committed; only the DSN shape lives here. POSIX-sh safe (sourced by Make's
# /bin/sh and by CI); intentionally does not `set -e`/`-u` (would affect the caller).
# .env's own vars are plain KEY=VALUE (no `export`), so a bare `.`/source would only
# set shell-local variables invisible to any subprocess (e.g. pytest) launched later
# in the same recipe — `set -a` marks every variable sourced afterwards for export.
set -a
[ -f "${SQUALL_DIR:-.}/.env" ] && . "${SQUALL_DIR:-.}/.env"
set +a

: "${DB2_PASSWORD:?DB2_PASSWORD not set (copy .env.example to .env, or set it in CI)}"
: "${PROLEAP_BRIDGE_JAR:?PROLEAP_BRIDGE_JAR not set (the ProLeap bridge JAR path)}"
_squall_host="${DB2_HOST:-localhost}"
_squall_port="${DB2_PORT:-50000}"

export SQUALL_DB2_DSN="DATABASE=MOJO;HOSTNAME=${_squall_host};PORT=${_squall_port};PROTOCOL=TCPIP;UID=db2inst1;PWD=${DB2_PASSWORD}"
export SQUALL_DB2_DSN2="DATABASE=MOJO2;HOSTNAME=${_squall_host};PORT=${_squall_port};PROTOCOL=TCPIP;UID=db2inst1;PWD=${DB2_PASSWORD}"
