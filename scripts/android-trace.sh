#!/usr/bin/env bash
# Records a Perfetto trace over USB: system atrace categories plus the app's own Trace.beginSection sections, for the
# app's main process and its ":icd11" engine process. Open the output in https://ui.perfetto.dev.
#
# Usage: scripts/android-trace.sh <out_dir> [seconds=30]
#   PKG=<package> overrides the package (default: the Collect Plus release/dev package).
#
# Needs adb and exactly one connected device, or ANDROID_SERIAL set to choose one. Start the work to record (for
# example `adb shell am start -a android.intent.action.VIEW -d "digitvacollectplus://engine-check?run=1"`) while
# this is running; the trace covers only the window of the recording.
# Writes <out_dir>/<name>.perfetto-trace. The trace file on the phone is removed after the pull.

PKG=${PKG:-com.causeofdeathindia.digitvacollect.plus}
OUT=${1:-}
SECONDS_TO_RECORD=${2:-30}

die() { echo "android-trace: $*" >&2; exit 1; }

[ -n "$OUT" ] || { echo "usage: $0 <out_dir> [seconds=30]" >&2; exit 2; }
printf '%s' "$SECONDS_TO_RECORD" | grep -Eq '^[0-9]+$' || die "seconds must be a whole number"
[ "$SECONDS_TO_RECORD" -ge 1 ] && [ "$SECONDS_TO_RECORD" -le 600 ] || die "seconds must be between 1 and 600"

command -v adb >/dev/null 2>&1 || die "adb not found on PATH"

if [ -n "${ANDROID_SERIAL:-}" ]; then
  SERIAL=$ANDROID_SERIAL
else
  DEVICES=$(adb devices | awk 'NR > 1 && $2 == "device" { print $1 }')
  COUNT=$(printf '%s\n' "$DEVICES" | grep -c .)
  [ "$COUNT" -eq 1 ] || die "expected exactly one connected device, found $COUNT (set ANDROID_SERIAL to choose one)"
  SERIAL=$DEVICES
fi
[ "$(adb -s "$SERIAL" get-state 2>/dev/null)" = device ] || die "device $SERIAL is not attached and ready"

# </dev/null: adb shell must not read the caller's stdin, except where the config is piped in below.
adb_s() { adb -s "$SERIAL" "$@" </dev/null 2>/dev/null | tr -d '\r'; }

mkdir -p "$OUT" || die "cannot create $OUT"
NAME="digitva-trace-$(date -u +%Y%m%dT%H%M%SZ)"
DEVICE_TRACE="/data/misc/perfetto-traces/$NAME.perfetto-trace"

if [ -z "$(adb_s shell pidof "$PKG")" ]; then
  echo "android-trace: warning: $PKG is not running; start it before the work to record" >&2
fi

# Text config (perfetto --txt). Atrace categories are the system side (am, wm, view, dalvik, sched, freq, gfx);
# atrace_apps lists both processes so the icd11.* sections in :icd11 are recorded too.
trace_config() {
  cat <<EOF
buffers {
  size_kb: 65536
  fill_policy: RING_BUFFER
}
data_sources {
  config {
    name: "linux.ftrace"
    target_buffer: 0
    ftrace_config {
      ftrace_events: "sched/sched_switch"
      ftrace_events: "sched/sched_wakeup"
      ftrace_events: "power/cpu_frequency"
      atrace_categories: "am"
      atrace_categories: "wm"
      atrace_categories: "view"
      atrace_categories: "dalvik"
      atrace_categories: "sched"
      atrace_categories: "freq"
      atrace_categories: "gfx"
      atrace_apps: "$PKG"
      atrace_apps: "$PKG:icd11"
    }
  }
}
data_sources {
  config {
    name: "linux.process_stats"
    target_buffer: 0
  }
}
data_sources {
  config {
    name: "android.surfaceflinger.frametimeline"
    target_buffer: 0
  }
}
duration_ms: $(( SECONDS_TO_RECORD * 1000 ))
EOF
}

echo "recording ${SECONDS_TO_RECORD}s of atrace and $PKG (both processes) on $SERIAL -> $OUT/$NAME.perfetto-trace"
# perfetto reads the config from stdin (-c -) and stops by itself after duration_ms.
trace_config | adb -s "$SERIAL" shell perfetto -c - --txt -o "$DEVICE_TRACE" || die "perfetto failed on $SERIAL"

LOCAL_TRACE="$OUT/$NAME.perfetto-trace"
adb -s "$SERIAL" pull "$DEVICE_TRACE" "$LOCAL_TRACE" </dev/null >/dev/null 2>&1 || die "could not pull $DEVICE_TRACE"
adb -s "$SERIAL" shell rm -f "$DEVICE_TRACE" </dev/null >/dev/null 2>&1

echo "trace: $LOCAL_TRACE"
echo "open it at https://ui.perfetto.dev (Open trace file, or drag the file onto the page)"
echo "app sections are named icd11.init, icd11.copy, icd11.search, icd11.codeinfo, icd11.doris, icd11.codedit"
