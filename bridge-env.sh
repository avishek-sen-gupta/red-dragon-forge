# Source this to export PROLEAP_BRIDGE_JAR / JCL_BRIDGE_JAR, the two bridge JARs, and
# HLASM_EXPORT, the BMS exporter binary, all built by `make setup`, as absolute paths:
# . ./bridge-env.sh  (or ../bridge-env.sh from a package). The paths resolve from this
# file's own location under bash and zsh; any other shell must set FORGE_ROOT first.
# Does not `set -e`/`-u`: it runs in the caller's shell.
if [ -n "${BASH_SOURCE:-}" ]; then
  FORGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [ -n "${ZSH_VERSION:-}" ]; then
  eval 'FORGE_ROOT="$(cd "$(dirname "${(%):-%x}")" && pwd)"'
fi
: "${FORGE_ROOT:?FORGE_ROOT not set (source bridge-env.sh from bash or zsh, or set it)}"

export PROLEAP_BRIDGE_JAR="$FORGE_ROOT/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
export JCL_BRIDGE_JAR="$FORGE_ROOT/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar"
export HLASM_EXPORT="$FORGE_ROOT/vendor/red-dragon/hlasm-bridge/che4z/build/bin/hlasm_export"

for _built in "$PROLEAP_BRIDGE_JAR" "$JCL_BRIDGE_JAR" "$HLASM_EXPORT"; do
  [ -f "$_built" ] || echo "warning: $_built not built (run \`make setup\` at the forge root)" >&2
done
unset _built
