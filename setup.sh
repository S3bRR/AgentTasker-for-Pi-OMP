#!/usr/bin/env bash
# Convenience entry point. Arguments go to the explicit Python installer.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'Error: Python 3.10+ is required; install Python first.' >&2
  exit 1
fi
exec python3 "$ROOT/install.py" "$@"
