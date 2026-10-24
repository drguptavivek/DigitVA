#!/usr/bin/env bash
# Publish the packaged ICD-11 engine as a public GitHub release asset. The owner runs this by hand; CI never does.
# It checks the packaged sha256, creates the release, then downloads the release copy and compares it with the
# local archive, so a mismatch shows before anyone pins the sha256 in the Collect Plus workflow.
# usage: scripts/publish-icd11-engine.sh OUT_DIR   (OUT_DIR from scripts/package-icd11-engine.sh)
set -euo pipefail

usage() {
  echo "usage: $0 OUT_DIR" >&2
  exit 2
}

[[ $# -eq 1 ]] || usage
out_dir=$1

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=icd11-engine.env
. "$repo_root/scripts/icd11-engine.env"

name="icd11-engine-${ICD11_ENGINE_VERSION}"
tag="icd11-engine-v${ICD11_ENGINE_VERSION}"
repo="${DIGITVA_REPO:-drguptavivek/DigitVA}"
archive="$out_dir/$name.tar.gz"
checksum="$archive.sha256"
[[ -s "$archive" && -s "$checksum" ]] || {
  echo "missing $archive or $checksum; run scripts/package-icd11-engine.sh first" >&2
  exit 1
}
(cd "$out_dir" && shasum -a 256 -c "$name.tar.gz.sha256")

notes="Offline ICD-11 engine for DigitVA Collect Plus (Android, arm64-v8a).

Compiled from the WHO ICD-API 2.6.0 code and the DORIS rules 1.2.0. WHO ICD-11 is licensed CC BY-ND 3.0 IGO; this
archive is a derivative built from those sources. The licence obligations are in docs/policy/icd11-local-api-runtime.md
(\"ICD-11 licence obligations\") in the DigitVA repository.

Contents: the engine library and the WHO-supplied data files that the app ships, listed by
mobile/digitva-collect/modules/digitva-icd11/scripts/stage-engine.js. The archive is a packaging of those files only;
nothing is compiled from it at release time. Verify with the attached $name.tar.gz.sha256."

gh release create "$tag" "$archive" "$checksum" \
  --repo "$repo" \
  --title "ICD-11 engine ${ICD11_ENGINE_VERSION}" \
  --notes "$notes"

verify="$(mktemp -d)"
trap 'rm -rf "$verify"' EXIT
gh release download "$tag" --repo "$repo" --dir "$verify" \
  --pattern "$name.tar.gz" --pattern "$name.tar.gz.sha256"
(cd "$verify" && shasum -a 256 -c "$name.tar.gz.sha256")
cmp -s "$verify/$name.tar.gz" "$archive" || {
  echo "release copy of $name.tar.gz differs from the local archive" >&2
  exit 1
}
echo "published $tag; sha256 $(cut -d' ' -f1 "$checksum")"
