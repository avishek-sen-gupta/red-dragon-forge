#!/bin/sh
# Fetches the CodeQL CLI and the QL libraries this pack is written against into tools/, which git ignores.
set -eu
VERSION=2.27.4
cd "$(dirname "$0")"
mkdir -p tools
case "$(uname -s)" in
  Darwin) PLATFORM=osx64 ;;
  Linux) PLATFORM=linux64 ;;
esac
curl -fL -o tools/codeql.zip "https://github.com/github/codeql-cli-binaries/releases/download/v$VERSION/codeql-$PLATFORM.zip"
unzip -q -o tools/codeql.zip -d tools
rm tools/codeql.zip
git clone --depth 1 --branch "codeql-cli/v$VERSION" https://github.com/github/codeql.git tools/ql
