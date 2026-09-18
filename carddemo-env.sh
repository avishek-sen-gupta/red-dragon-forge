# Source this before running the TN3270 server or anything else that drives
# CardDemo:  . ./carddemo-env.sh
#
# Exports FORGE_ROOT and CARDDEMO_HOME (which the wire config's ${...} paths
# expand) and, via bridge-env.sh, the two bridge JARs. Paths resolve from this
# file's own location under bash and zsh; any other shell must set FORGE_ROOT
# first. Does not `set -e`/`-u`: it runs in the caller's shell.
if [ -n "${BASH_SOURCE:-}" ]; then
  FORGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [ -n "${ZSH_VERSION:-}" ]; then
  eval 'FORGE_ROOT="$(cd "$(dirname "${(%):-%x}")" && pwd)"'
fi
: "${FORGE_ROOT:?FORGE_ROOT not set (source carddemo-env.sh from bash or zsh, or set it)}"
export FORGE_ROOT
export CARDDEMO_HOME="${CARDDEMO_HOME:-$FORGE_ROOT/vendor/carddemo/app}"

. "$FORGE_ROOT/bridge-env.sh"

[ -d "$CARDDEMO_HOME/cbl" ] || echo "warning: no CardDemo COBOL under $CARDDEMO_HOME/cbl (run \`git submodule update --init vendor/carddemo\`, or set CARDDEMO_HOME)" >&2
