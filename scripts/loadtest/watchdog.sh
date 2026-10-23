#!/bin/bash
# Runs on the operator's machine. Every ~10 s reads the app host's sampler
# (box_sampler.sh); when MemAvailable < 300 MiB or an OOM is seen it touches
# /tmp/lt_abort here and on the load box, which stops lt_run.py.
# Env: LT_APP_INSTANCE, LT_LOAD_INSTANCE (instance ids). Stop: touch /tmp/lt_watchdog.stop
: "${LT_APP_INSTANCE:?}" "${LT_LOAD_INSTANCE:?}"
SSM=$(dirname "$0")/ssm.sh
rm -f /tmp/lt_abort /tmp/lt_watchdog.stop
while [ ! -f /tmp/lt_watchdog.stop ]; do
  row=$(LT_TARGET=$LT_APP_INSTANCE $SSM 'grep ",host," /tmp/lt_monitor.csv | tail -1' | grep -oE '[0-9:]{8},host,[a-z]+,[0-9]+,[0-9.]+,[^[:space:]]*' | tail -1)
  echo "$(date +%H:%M:%S) $row"
  avail=$(echo "$row" | cut -d, -f4)
  if [[ "$row" == *OOM_SEEN* ]] || { [ -n "$avail" ] && [ "$avail" -lt 300 ]; }; then
    touch /tmp/lt_abort; LT_TARGET=$LT_LOAD_INSTANCE $SSM "touch /tmp/lt_abort" >/dev/null; echo "ABORT: $row"
  fi
  sleep 10
done
