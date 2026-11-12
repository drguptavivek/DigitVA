#!/bin/bash
# Runnable check for restore_guard: bash scripts/lib/test-restore-guard.sh
# Fake values only; touches no database.
. "$(dirname "$0")/restore-guard.sh"
fail=0
t() { # expected_rc, then env assignments..., -- guard args
  local want="$1"; shift
  local envs=(); while [ "$1" != "--" ]; do envs+=("$1"); shift; done; shift
  env -u CONFIRM_RESTORE -u ALLOW_REMOTE_RESTORE "${envs[@]}" bash -c '. "$0"; restore_guard "$@"' \
    "$(dirname "$0")/restore-guard.sh" "$@" </dev/null >/dev/null 2>&1
  local rc=$?; [ "$want" = ok ] && [ $rc -ne 0 ] && { echo "FAIL: $*"; fail=1; }
  [ "$want" = no ] && [ $rc -eq 0 ] && { echo "FAIL (allowed): $*"; fail=1; }
}
t no  -- minerva localhost                                   # no confirmation, no tty
t no  CONFIRM_RESTORE=other -- minerva localhost             # wrong name
t ok  CONFIRM_RESTORE=minerva -- minerva localhost
t no  CONFIRM_RESTORE=minerva -- minerva db.example.com      # remote host
t no  CONFIRM_RESTORE=minerva_prod -- minerva_prod localhost # prod name
t ok  CONFIRM_RESTORE=minerva_prod ALLOW_REMOTE_RESTORE=1 -- minerva_prod localhost
t no  CONFIRM_RESTORE=minerva -- minerva minerva_db remote   # remote mode needs override
t ok  CONFIRM_RESTORE=minerva ALLOW_REMOTE_RESTORE=1 -- minerva minerva_db remote
[ $fail = 0 ] && echo "restore_guard: all checks passed"; exit $fail
