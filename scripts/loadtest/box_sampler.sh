#!/bin/bash
# Runs on staging. Every 10 s appends one row per container plus host totals to /tmp/lt_monitor.csv.
# Stop: rm /tmp/lt_monitor.run
OUT=/tmp/lt_monitor.csv; touch /tmp/lt_monitor.run
[ -f $OUT ] || echo "ts,kind,name,mem_mib,cpu_pct,extra" > $OUT
while [ -f /tmp/lt_monitor.run ]; do
  ts=$(date -u +%H:%M:%S)
  avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
  load=$(cut -d" " -f1 /proc/loadavg)
  q=$(docker exec minerva_app python -c 'import os,redis;print(redis.Redis.from_url(os.environ["CELERY_BROKER_URL"]).llen("celery"))' 2>/dev/null || echo NA)
  echo "$ts,host,host,$avail,$load,celery_queue=$q" >> $OUT
  docker stats --no-stream --format '{{.Name}},{{.MemUsage}},{{.CPUPerc}}' | awk -F, -v ts=$ts '{split($2,a," "); m=a[1]; v=m+0; if (m ~ /GiB/) v*=1024; if (m ~ /KiB/) v/=1024; gsub("%","",$3); printf "%s,ctr,%s,%d,%s,\n", ts,$1,v,$3}' >> $OUT
  dmesg 2>/dev/null | grep -qi 'out of memory' && echo "$ts,host,oom,0,0,OOM_SEEN" >> $OUT
  sleep 8
done
