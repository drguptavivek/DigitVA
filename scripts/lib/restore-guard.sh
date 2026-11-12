#!/bin/bash
# Guard for scripts that REPLACE a database. Source it, then:
#   restore_guard <db_name> <db_host> [remote]
# Refuses unless the target is local and not named like staging/production, or
# ALLOW_REMOTE_RESTORE=1 is set ("remote" always needs it). Then requires the
# target DB name typed back: at the prompt, or CONFIRM_RESTORE=<db_name> for
# non-interactive use. Never call it with values it should not trust: it only
# compares strings and touches nothing.

restore_guard() {
  local db="${1:?db name}" host="${2:-}" mode="${3:-}"
  local risky=0
  case "$host" in
    ""|localhost|127.0.0.1|::1|minerva_db|minerva_db_service) ;;
    *) risky=1 ;;
  esac
  case "$db" in
    *staging*|*prod*|*live*) risky=1 ;;
  esac
  [ "$mode" = "remote" ] && risky=1
  if [ "$risky" = 1 ] && [ "${ALLOW_REMOTE_RESTORE:-}" != "1" ]; then
    echo "REFUSED: target '$db' on host '${host:-local}' looks like staging/production." >&2
    echo "Set ALLOW_REMOTE_RESTORE=1 only if replacing this database is intended." >&2
    return 1
  fi
  local typed="${CONFIRM_RESTORE:-}"
  if [ -z "$typed" ]; then
    if [ ! -t 0 ]; then
      echo "REFUSED: not a terminal; set CONFIRM_RESTORE=$db to confirm." >&2
      return 1
    fi
    echo "This REPLACES database '$db' (host '${host:-local}'). Type the database name to continue:" >&2
    read -r typed
  fi
  if [ "$typed" != "$db" ]; then
    echo "REFUSED: confirmation did not match '$db'." >&2
    return 1
  fi
}
