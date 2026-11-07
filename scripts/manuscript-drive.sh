#!/usr/bin/env bash
# The LDH manuscript and appendix are edited on Google Drive only. This keeps a
# local working copy in private/manuscript-drive/ (git-ignored), which the
# docs/manuscript/*.docx symlinks point at.
#
#   scripts/manuscript-drive.sh pull   fetch both files; the previous copy goes to backups/
#   scripts/manuscript-drive.sh push   upload local edits to the same Drive files
#
# push refuses when a file changed on Drive since the last pull, so edits made on
# Drive are never overwritten; pull again and redo the change. Needs the rclone
# remote "gdrive:". Drive keeps every uploaded version.
set -euo pipefail

REMOTE="gdrive:DigitVA Platform Paper"
DIR="$(cd "$(dirname "$0")/.." && pwd)/private/manuscript-drive"
FILES=(
  "DigitVA_LDH_Manuscript.docx 1O2cFwZqgyZ7sh87VkjiYgHQ8oM2Diuho"
  "DigitVA_LDH_Appendix.docx 12UMIGl0DrIIYtLNA0ZVVPk22u0n7OPMd"
)

# Drive modification time and size of one file, checked against its expected ID.
drive_stamp() {
  rclone lsjson "$REMOTE" --files-only --include "$1" | python3 -c '
import json, sys
rows = json.load(sys.stdin)
if len(rows) != 1 or rows[0]["ID"] != sys.argv[1]:
    sys.exit("expected exactly one file with ID " + sys.argv[1] + ", found " + str([r["ID"] for r in rows]))
print(rows[0]["ModTime"], rows[0]["Size"])' "$2"
}

pull() {
  mkdir -p "$DIR/backups"
  for entry in "${FILES[@]}"; do
    read -r name id <<<"$entry"
    if [ -f "$DIR/$name" ]; then
      cp -p "$DIR/$name" "$DIR/backups/${name%.docx}.$(date +%Y%m%d-%H%M%S).docx"
    fi
    rclone backend copyid gdrive: "$id" "$DIR/$name.part"
    mv "$DIR/$name.part" "$DIR/$name"
    drive_stamp "$name" "$id" >"$DIR/.$name.pulled"
    echo "pulled $name ($(cat "$DIR/.$name.pulled"))"
  done
}

push() {
  for entry in "${FILES[@]}"; do
    read -r name id <<<"$entry"
    [ -f "$DIR/.$name.pulled" ] || { echo "$name: never pulled; run pull first" >&2; exit 1; }
    now="$(drive_stamp "$name" "$id")"
    if [ "$now" != "$(cat "$DIR/.$name.pulled")" ]; then
      echo "$name changed on Drive since the last pull ($now); pull and redo the edit" >&2
      exit 1
    fi
  done
  for entry in "${FILES[@]}"; do
    read -r name id <<<"$entry"
    rclone copyto "$DIR/$name" "$REMOTE/$name"   # updates the same file ID
    drive_stamp "$name" "$id" >"$DIR/.$name.pulled"
    echo "pushed $name ($(cat "$DIR/.$name.pulled"))"
  done
}

case "${1:-}" in
  pull) pull ;;
  push) push ;;
  *) echo "usage: $0 pull|push" >&2; exit 2 ;;
esac
