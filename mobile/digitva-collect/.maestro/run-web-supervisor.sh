#!/usr/bin/env bash
# Playwright check "supervisor sees the sent case". Run it after a Maestro run (70 has sent
# regA) while that run's users still exist, i.e. before run-suite.sh's teardown, or against
# a run you created yourself: private/e2e-users.json by default, or the file in $1.
# The credentials go into this shell's environment only, never printed. Dev web app on
# http://localhost:8051 (make dev-hmr); override with E2E_BASE_URL.
# Usage: run-web-supervisor.sh [users-file]
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../.." && pwd)
eval "$(python3 -I - "${1:-$ROOT/private/e2e-users.json}" <<'P'
import json, shlex, sys
d = json.load(open(sys.argv[1]))
print("export E2E_RUN_ID=" + shlex.quote(d["run_id"]))
print("export E2E_PASSWORD=" + shlex.quote(d["password"]))
print("export E2E_SUPERVISOR_EMAIL=" + shlex.quote(d["users"]["supervisor"]))
P
)"
# Playwright is installed only under vendor/who-va-2022; resolve @playwright/test from there.
PW="$ROOT/vendor/who-va-2022"
NODE_PATH="$PW/node_modules" exec "$PW/node_modules/.bin/playwright" test -c "$HERE/web/playwright.config.ts"
