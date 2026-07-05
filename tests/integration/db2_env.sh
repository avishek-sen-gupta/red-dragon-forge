# Source this (from the repo root) to export SQUALL_DB2_DSN for red-dragon-forge's
# own Db2 integration test. Reuses squall's own MOJO container config; does not
# stand up a second one. POSIX-sh safe; intentionally does not set -e/-u.
[ -f squall/.env ] && . squall/.env

: "${DB2_PASSWORD:?DB2_PASSWORD not set (copy squall/.env.example to squall/.env)}"
: "${PROLEAP_BRIDGE_JAR:?PROLEAP_BRIDGE_JAR not set}"
_forge_host="${DB2_HOST:-localhost}"
_forge_port="${DB2_PORT:-50000}"

export SQUALL_DB2_DSN="DATABASE=MOJO;HOSTNAME=${_forge_host};PORT=${_forge_port};PROTOCOL=TCPIP;UID=db2inst1;PWD=${DB2_PASSWORD}"
