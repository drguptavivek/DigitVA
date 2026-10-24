#!/usr/bin/env bash
# Samples the memory of an Android app over USB while someone (or a script) drives it.
#
# Usage: scripts/android-profile.sh <package> <out_dir> [interval_seconds=2] [duration_seconds=300]
#
# Needs adb and exactly one connected device, or ANDROID_SERIAL set to choose one.
# Writes into <out_dir>:
#   device.txt      model, Android version, ABIs, MemTotal/MemAvailable, page size (once)
#   meminfo.csv     App Summary memory per process (main and ":name" sub-processes) per sample
#   device_mem.csv  device-wide MemAvailable per sample
#   logcat.txt      logcat lines matching LMK, trim, kill, ANR, FATAL or the package name
# On exit (normal, or Ctrl-C) logcat is stopped and a summary is printed.
# Reads only memory statistics and host-filtered logcat; the unfiltered logcat is never captured.
# A process that is absent from a sample (no App Summary) gets no row, so it counts as missing.

PKG=${1:-}
OUT=${2:-}
INTERVAL=${3:-2}
DURATION=${4:-300}

die() { echo "android-profile: $*" >&2; exit 1; }

[ -n "$PKG" ] && [ -n "$OUT" ] || { echo "usage: $0 <package> <out_dir> [interval_seconds=2] [duration_seconds=300]" >&2; exit 2; }
printf '%s' "$INTERVAL" | grep -Eq '^[0-9]+([.][0-9]+)?$' || die "interval must be a positive number"
printf '%s' "$DURATION" | grep -Eq '^[0-9]+$' || die "duration must be a whole number of seconds"

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

# </dev/null matters: adb shell inside a `while read` loop would otherwise eat the loop input.
adb_s() { adb -s "$SERIAL" "$@" </dev/null 2>/dev/null | tr -d '\r'; }

mkdir -p "$OUT" || die "cannot create $OUT"
MEM_CSV=$OUT/meminfo.csv
DEV_CSV=$OUT/device_mem.csv
LOG=$OUT/logcat.txt

{
  echo "package: $PKG"
  echo "serial: $SERIAL"
  echo "model: $(adb_s shell getprop ro.product.model)"
  echo "android_version: $(adb_s shell getprop ro.build.version.release)"
  echo "sdk_level: $(adb_s shell getprop ro.build.version.sdk)"
  echo "abi_list: $(adb_s shell getprop ro.product.cpu.abilist)"
  adb_s shell cat /proc/meminfo | awk '$1 == "MemTotal:" || $1 == "MemAvailable:" { print $1, $2, "kB" }'
  echo "page_size_bytes: $(adb_s shell getconf PAGESIZE)"
} > "$OUT/device.txt"

echo "iso_timestamp,process,pid,total_pss_kb,total_rss_kb,native_heap_kb,java_heap_kb,graphics_kb,swap_pss_kb" > "$MEM_CSV"
echo "iso_timestamp,mem_available_kb" > "$DEV_CSV"
: > "$LOG"

# Filter on the host: only matching lines reach disk. Dots in the package name are escaped for grep -E.
PKG_RE=$(printf '%s' "$PKG" | sed 's/\./\\./g')
adb -s "$SERIAL" logcat -v time </dev/null 2>/dev/null \
  | grep --line-buffered -E "lowmemorykiller|lmkd|onTrimMemory|TRIM_MEMORY|Kill|died|ANR|FATAL|$PKG_RE" >> "$LOG" &
LOGCAT_BG=$!

stop_logcat() {
  [ -n "${LOGCAT_BG:-}" ] || return 0
  # adb is a sibling of grep in the pipeline, so it is found by parent pid and its command line.
  pkill -P $$ -f 'logcat -v time' 2>/dev/null
  kill "$LOGCAT_BG" 2>/dev/null
  wait "$LOGCAT_BG" 2>/dev/null
  LOGCAT_BG=
}

# Parses the App Summary block only; the detailed table uses the same labels without colons.
MEM_AWK='
function num(s, lab,   t) {
  t = substr(s, index(s, lab) + length(lab))
  return match(t, /[0-9]+/) ? substr(t, RSTART, RLENGTH) : ""
}
/App Summary/ { insum = 1; next }
/^ *Objects/ { insum = 0 }
insum && index($0, "Java Heap:") { jh = num($0, "Java Heap:") }
insum && index($0, "Native Heap:") { nh = num($0, "Native Heap:") }
insum && index($0, "Graphics:") { gr = num($0, "Graphics:") }
insum && index($0, "TOTAL PSS:") { tpss = num($0, "TOTAL PSS:") }
insum && index($0, "TOTAL RSS:") { trss = num($0, "TOTAL RSS:") }
insum && index($0, "TOTAL SWAP PSS:") { sw = num($0, "TOTAL SWAP PSS:") }
END { if (tpss != "") print ts "," name "," pid "," tpss "," trss "," nh "," jh "," gr "," sw }
'

sample() {
  local ts procs pid name
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  adb_s shell cat /proc/meminfo | awk -v ts="$ts" '$1 == "MemAvailable:" { print ts "," $2 }' >> "$DEV_CSV"
  procs=$(adb_s shell ps -A -o PID,NAME | awk -v p="$PKG" 'NR > 1 && ($2 == p || index($2, p ":") == 1) { print $1, $2 }')
  printf '%s\n' "$procs" | while read -r pid name; do
    [ -n "$pid" ] || continue
    adb_s shell dumpsys meminfo "$pid" | awk -v ts="$ts" -v name="$name" -v pid="$pid" "$MEM_AWK" >> "$MEM_CSV"
  done
}

summary() {
  stop_logcat
  echo "== android-profile summary: $PKG on $SERIAL =="
  echo "TOTAL PSS per process (MB):"
  awk -F, 'NR > 1 && $4 != "" {
      n[$2]++; s[$2] += $4; v = $4 + 0
      if (!($2 in m) || v > m[$2]) m[$2] = v
    }
    END {
      if (!length(n)) print "  (no samples)"
      for (k in n) printf "  %s  max %.1f  mean %.1f  samples %d\n", k, m[k] / 1024, s[k] / n[k] / 1024, n[k]
    }' "$MEM_CSV"
  awk -F, 'NR > 1 && $2 != "" { v = $2 + 0; if (!set || v < min) { min = v; set = 1 } }
    END { if (set) printf "min device MemAvailable: %.1f MB\n", min / 1024; else print "min device MemAvailable: no samples" }' "$DEV_CSV"

  # A pid present in one sample and absent from the next has died (killed or exited) in between.
  awk -F, '
  function step(   p) {
    for (p in P) if (!(p in C)) gone[P[p]]++
    delete P
    for (p in C) P[p] = C[p]
    delete C
  }
  NR == 1 { next }
  $1 != cur { if (cur != "") step(); cur = $1 }
  { C[$3] = $2; seen[$2] = 1 }
  END {
    if (cur != "") step()
    for (n in seen) printf "missing between samples: %s  %d time(s)\n", n, gone[n] + 0
  }' "$MEM_CSV"

  LMK_LINES=$(grep -E 'lowmemorykiller|lmkd' "$LOG" | grep -cF "$PKG")
  echo "logcat lines (filtered): $(wc -l < "$LOG" | tr -d ' ')"
  echo "logcat lines naming lowmemorykiller/lmkd and $PKG: $LMK_LINES"
  echo "outputs: $OUT"
}

trap summary EXIT
trap 'exit 130' INT TERM

echo "profiling $PKG on $SERIAL every ${INTERVAL}s for ${DURATION}s -> $OUT (Ctrl-C to stop early)"
start=$(date +%s)
while [ $(( $(date +%s) - start )) -lt "$DURATION" ]; do
  sample
  sleep "$INTERVAL"
done
