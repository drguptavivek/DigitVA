# Version pins for the local Collect Plus build, read from the repo's own files so CI and this build cannot drift.
# Sourced by run.sh (host, to build the toolchain image) and build.sh (container). Usage: pin_<name> REPO_ROOT.
wf() { echo "$1/.github/workflows/$2"; }
# "KEY: value" lines of a workflow (env blocks, with-blocks); quotes stripped.
wf_value() { awk -v k="$2:" '$1 == k {gsub(/"/, "", $2); print $2; exit}' "$(wf "$1" "$3")"; }
pin_node_major() { wf_value "$1" node-version collect-plus-release.yml; }
pin_pnpm() { grep -o 'pnpm@[0-9][0-9.]*' "$(wf "$1" collect-plus-release.yml)" | head -1 | cut -d@ -f2; }
pin_ndk() { wf_value "$1" NDK_VERSION icd11-engine-build.yml; }
pin_icd_image() { wf_value "$1" ICD11_IMAGE icd11-engine-build.yml; }
pin_dotnet() { sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$1/mobile/digitva-collect/modules/digitva-icd11/engine-src/global.json"; }
# WHO download URLs and the sha256 of every file they yield, as icd11-engine-build.yml checks them.
pin_who_urls() { grep -o 'fetch "https://[^"]*"' "$(wf "$1" icd11-engine-build.yml)" | cut -d'"' -f2; }
pin_who_data_sums() { grep -E '^ +[0-9a-f]{64}  ' "$(wf "$1" icd11-engine-build.yml)" | sed 's/^ *//'; }
pin_doris_zip_sha() { grep -o '[0-9a-f]\{64\}  \$RUNNER_TEMP/DORIS[^"]*\.zip' "$(wf "$1" icd11-engine-build.yml)" | cut -c1-64; }
# Fail now, with the name of the pin, rather than build with an empty version.
require_pins() {
  local root=$1 name
  for name in node_major pnpm ndk icd_image dotnet doris_zip_sha who_urls who_data_sums; do
    [[ -n "$("pin_$name" "$root")" ]] || { echo "pin '$name' not found under $root (workflow or global.json changed shape?)" >&2; return 1; }
  done
}
