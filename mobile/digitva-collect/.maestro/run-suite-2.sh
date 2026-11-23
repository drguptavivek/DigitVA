#!/usr/bin/env bash
# Copy of run-suite.sh for the second emulator (emulator-5556, own users file).
# Local-only Maestro run on the Android emulator (never CI, never a real phone).
#
#   create e2e users -> enrol -> flows/*.yaml (each its own maestro run, continue
#   on failure) -> teardown of this run (always).
#   The app's data is cleared first, so profiles never carry over between runs.
#
# Secrets (e2e password, the run PIN) live only in this shell's MAESTRO_*
# environment: read from private/e2e-users.json / generated here, never printed,
# never on a command line. Maestro output is masked before it is shown or kept.
# Usage: run-suite.sh [flow-file-substring ...]   (no argument = every flow)
set -u
SERIAL=emulator-5556
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../.." && pwd)
WORK=$(mktemp -d)
RESULTS="$WORK/results.tsv"
# Failure screenshots: kept after the run, outside the repo. Delete them once reviewed.
SHOTS=${MAESTRO_SHOTS:-${TMPDIR:-/tmp}/maestro-shots/$(date +%Y%m%d-%H%M%S)}
: > "$RESULTS"
APP=com.causeofdeathindia.digitvacollect.plus
dc() { (cd "$ROOT" && docker compose exec -T minerva_app_service uv run --no-sync "$@"); }
adbx() { adb -s "$SERIAL" "$@"; }
# One scalar from the dev database (checks/*.sh). The statement may name this run's
# users by email prefix but must never select personal columns.
dbq() { (cd "$ROOT" && docker compose exec -T minerva_db_service sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"' _ "$1"); }

# Mask the secret values in everything Maestro prints.
mask() {
  python3 -I -c '
import os, sys
sec = [v for k, v in os.environ.items() if k.startswith("MAESTRO_") and len(v) >= 4]
for line in sys.stdin:
    for s in sec:
        line = line.replace(s, "***")
    sys.stdout.write(line)
'
}

cleanup() {
  trap - EXIT INT TERM
  adbx shell svc wifi enable >/dev/null 2>&1
  adbx shell svc data enable >/dev/null 2>&1
  adbx shell cmd connectivity airplane-mode disable >/dev/null 2>&1
  if [ -n "${MAESTRO_RUN_ID:-}" ]; then
    # Only this run's users: another run may be live on the same server.
    echo "== teardown e2e users (run $MAESTRO_RUN_ID)"
    dc flask seed e2e-users teardown --run "$MAESTRO_RUN_ID" 2>&1 | tail -5
  fi
  rm -rf "$HOME"/.maestro/tests/* "$WORK"
}
# A stopped run must not carry on with torn-down users: INT/TERM exit after cleanup.
trap cleanup EXIT
trap 'cleanup; exit 143' INT TERM

# Never touch anything but the emulator.
adbx get-state >/dev/null 2>&1 || { echo "$SERIAL is not attached"; exit 2; }

echo "== create e2e users"
dc flask seed e2e-users create --out private/e2e-users-2.json >/dev/null 2>&1 || { echo "e2e-users create failed"; exit 2; }
eval "$(python3 -I - "$ROOT/private/e2e-users-2.json" <<'P'
import json, secrets, shlex, sys
d = json.load(open(sys.argv[1]))
print("export MAESTRO_RUN_ID=" + shlex.quote(d["run_id"]))
print("export MAESTRO_PASSWORD=" + shlex.quote(d["password"]))
for key, email in d["users"].items():
    print("export MAESTRO_%s_EMAIL=%s" % (key.upper(), shlex.quote(email)))
while True:
    pin = "".join(secrets.choice("0123456789") for _ in range(6))
    if len(set(pin)) >= 4:
        break
print("export MAESTRO_PIN=" + pin)
P
)"
adbx shell am force-stop dev.mobile.maestro >/dev/null 2>&1
# Every run starts from an empty app (owner 2026-11-13): no profile or device enrolment
# from an earlier run or a manual session survives. The emulator is test-only.
echo "== clear app data"
adbx shell pm clear "$APP" >/dev/null || { echo "pm clear failed"; exit 2; }

run_flow() { # file -> appends "name<TAB>PASS|FAIL<TAB>seconds" to RESULTS
  local f=$1 name start rc end
  name=$(basename "$f" .yaml)
  start=$(date +%s)
  # A flow may ask for the network to be switched before it runs (the app must not be
  # relaunched while it is off: that also cuts Metro).
  if grep -q '^# wrapper: offline-before' "$f"; then
    adbx shell svc wifi disable >/dev/null 2>&1; adbx shell svc data disable >/dev/null 2>&1
  elif grep -q '^# wrapper: online-before' "$f"; then
    adbx shell svc wifi enable >/dev/null 2>&1; adbx shell svc data enable >/dev/null 2>&1
  fi
  for attempt in 1 2; do
    # The Maestro driver sometimes dies between runs: reset it, retry once.
    adbx forward --remove-all >/dev/null 2>&1
    adbx shell am force-stop dev.mobile.maestro >/dev/null 2>&1
    adbx shell am force-stop dev.mobile.maestro.test >/dev/null 2>&1
    maestro --device "$SERIAL" test "$f" 2>&1 | mask > "$WORK/$name.log"
    rc=${PIPESTATUS[0]}
    grep -q 'Device server died' "$WORK/$name.log" || break
  done
  if [ "$rc" -eq 0 ] && [ -f "$HERE/checks/$name.sh" ]; then
    # shellcheck disable=SC1090
    source "$HERE/checks/$name.sh" >> "$WORK/$name.log" 2>&1 || rc=1
  fi
  end=$(date +%s)
  printf '%s\t%s\t%ss\n' "$name" "$([ "$rc" -eq 0 ] && echo PASS || echo FAIL)" "$((end - start))" >> "$RESULTS"
  echo "$name: $([ "$rc" -eq 0 ] && echo PASS || echo FAIL) ($((end - start))s)"
  [ "$rc" -eq 0 ] || echo "failed-step: $(grep -m1 'FAILED' "$WORK/$name.log" | cut -c1-200)"
  # What the screen showed at the failure: visible texts only (masked fields stay masked).
  [ "$rc" -eq 0 ] || { adbx shell uiautomator dump /sdcard/u.xml >/dev/null 2>&1; adbx exec-out cat /sdcard/u.xml \
    | grep -oE ' text="[^"]+"' | sort -u | head -30 | mask | sed 's/^/screen:/'; }
  [ "$rc" -eq 0 ] || grep -v 'COMPLETED' "$WORK/$name.log" | tail -25
  # Keep Maestro's failure screenshots (local only; may show test names and death details).
  if [ "$rc" -ne 0 ]; then
    mkdir -p "$SHOTS"
    find "$HOME/.maestro/tests" -name '*.png' -exec cp {} "$SHOTS/" \; 2>/dev/null
    for p in "$SHOTS"/screenshot-*.png; do [ -e "$p" ] && mv "$p" "$SHOTS/$name-$(basename "$p")"; done
  fi
  rm -rf "$HOME"/.maestro/tests/*
}

suite_start=$(date +%s)
# Enrol only the profiles the chosen flows sign in as (each enrolment is about 2 minutes).
sel=""
for f in "$HERE"/flows/*.yaml; do
  if [ "$#" -gt 0 ]; then
    keep=0; for a in "$@"; do case "$f" in *"$a"*) keep=1;; esac; done
    [ "$keep" -eq 1 ] || continue
  fi
  sel="$sel $f"
done
need=$(cat /dev/null $sel | grep -oE 'ROLE: *[a-z0-9_]+|interviewer2' | sed 's/ROLE: *//' | sort -u)
for r in interviewer interviewer2 reporter coder supervisor reporter_t2 interviewer_t2; do
  v=0; echo "$need" | grep -qx "$r" && v=1
  export "MAESTRO_ENROL_$(echo "$r" | tr a-z A-Z)=$v"
done
echo "== enrol users:" $need
run_flow "$HERE/setup/enrol-users.yaml"
if grep -q 'enrol-users	FAIL' "$RESULTS"; then echo "enrol failed, stopping"; exit 1; fi

for f in "$HERE"/flows/*.yaml; do
  if [ "$#" -gt 0 ]; then
    keep=0; for a in "$@"; do case "$f" in *"$a"*) keep=1;; esac; done
    [ "$keep" -eq 1 ] || continue
  fi
  run_flow "$f"
  if [ "$(basename "$f" .yaml)" = 70-interview-send ]; then
    # Web check while this run's users exist: the supervisor sees the case 70 sent.
    start=$(date +%s)
    "$HERE/run-web-supervisor.sh" "$ROOT/private/e2e-users-2.json" 2>&1 | mask > "$WORK/web.log"
    if [ "${PIPESTATUS[0]}" -eq 0 ]; then r=PASS; else r=FAIL; fi
    printf 'web-supervisor\t%s\t%ss\n' "$r" "$(( $(date +%s) - start ))" >> "$RESULTS"
    echo "web-supervisor: $r ($(( $(date +%s) - start ))s)"
    # Keep the masked Playwright output and its failure artefacts (local only).
    if [ "$r" = FAIL ]; then
      mkdir -p "$SHOTS"; cp "$WORK/web.log" "$SHOTS/web-supervisor.log"
      grep -vE '^\s*$' "$WORK/web.log" | tail -30 | sed 's/^/web: /'
      cp -R "$HERE/web/test-results" "$SHOTS/web-test-results" 2>/dev/null || true
    fi
  fi
done
echo "== results"
column -t -s "$(printf '\t')" "$RESULTS"
echo "suite seconds: $(( $(date +%s) - suite_start ))"
! grep -q "	FAIL	" "$RESULTS"
