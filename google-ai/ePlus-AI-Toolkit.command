#!/bin/sh
# Finder/Terminal launcher for the macOS source bundle.
# This script is not a signed or notarized .app.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec /bin/sh ./run-macos.sh "$@"
