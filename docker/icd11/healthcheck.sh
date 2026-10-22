#!/bin/bash
# Healthy only when the WHO engine answers a real DORIS run: an open port is not
# enough (digitva-cfb1). bash /dev/tcp because the runtime image has no curl/wget.
body='{"ICDVersion":"ICD11","AdministrativeData":{"Sex":1,"EstimatedAge":"P62Y"},"Part1":[{"Conditions":[{"Code":"BA41.Z"}]}]}'
exec 3<>/dev/tcp/127.0.0.1/80 || exit 1
printf 'POST /icd/release/11/2026-01/doris HTTP/1.0\r\nAPI-Version: v2\r\nAccept-Language: en\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s' "${#body}" "$body" >&3
grep -q '"stemCode":"BA41.Z"' <&3
