#!/usr/bin/env bash
# Offline regression suite only. Does not start Forge, Pi, Docker, or a browser.
set -euo pipefail
cd "$(dirname "$0")/.."
# Do not inherit deployment settings, lease endpoints, or provider credentials.
env -i PATH="$PATH" HOME="$HOME" TMPDIR="${TMPDIR:-/tmp}" \
  CVENT_ENV=development PYTHONPATH=.:tests \
  python3 -m unittest discover -s tests
node --check ego_direct.mjs
git diff --check
