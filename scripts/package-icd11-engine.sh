#!/usr/bin/env bash
# Package the offline ICD-11 engine as the release archive that Collect Plus CI downloads. Packaging only: nothing is
# compiled here. The archive holds exactly the files stage-engine.js stages, sorted, with fixed owners, modes and
# mtimes, so the same spike folder gives the same bytes. The spike is DIGITVA_ICD11_SPIKE_DIR, else private/.
# usage: scripts/package-icd11-engine.sh OUT_DIR
set -euo pipefail

usage() {
  echo "usage: $0 OUT_DIR" >&2
  exit 2
}

[[ $# -eq 1 ]] || usage
out_dir=$1

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
stage="$repo_root/mobile/digitva-collect/modules/digitva-icd11/scripts/stage-engine.js"
# shellcheck source=icd11-engine.env
. "$repo_root/scripts/icd11-engine.env"

name="icd11-engine-${ICD11_ENGINE_VERSION}"
# Fixed mtime for every file, so the archive does not depend on when the spike was copied.
mtime="202601010000"
spike="$(node "$stage" --spike)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

list="$work/files.txt"
node "$stage" --list "$spike" > "$list"
[[ -s "$list" ]] || { echo "no engine files listed in $spike" >&2; exit 1; }

tree="$work/tree"
while IFS= read -r file; do
  mkdir -p "$tree/$(dirname "$file")"
  cp "$spike/$file" "$tree/$file"
  chmod 644 "$tree/$file"
  touch -t "$mtime" "$tree/$file"
done < "$list"

mkdir -p "$out_dir"
archive="$out_dir/$name.tar.gz"
# COPYFILE_DISABLE and --no-xattrs keep AppleDouble (._*) entries out; gzip -n keeps the gzip header free of a time.
(cd "$tree" && COPYFILE_DISABLE=1 tar --no-xattrs --uid 0 --gid 0 --uname root --gname root --format ustar -cf - -T "$list") \
  | gzip -n > "$archive"

tar -tzf "$archive" > "$work/listing.txt"
if grep -Eq '(^|/)\._' "$work/listing.txt"; then
  echo "archive has AppleDouble entries; refusing to publish it: $archive" >&2
  exit 1
fi

(cd "$out_dir" && shasum -a 256 "$name.tar.gz" > "$name.tar.gz.sha256")
echo "archive: $archive"
echo "sha256:  $(cut -d' ' -f1 "$out_dir/$name.tar.gz.sha256")"
echo "bytes:   $(wc -c < "$archive" | tr -d ' ')"
