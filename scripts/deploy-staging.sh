#!/usr/bin/env bash
# Owner-invoked Mac wrapper for a pull-only staging deployment over SSM.
# Usage: scripts/deploy-staging.sh <full-git-sha>
set -euo pipefail

TAG="${1:?usage: $0 <full 40-character lowercase git sha>}"
[[ "$TAG" =~ ^[0-9a-f]{40}$ ]] || { echo "TAG must be a full lowercase git sha" >&2; exit 1; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_SCRIPT=$(cat <<'REMOTE'
set -euo pipefail
cd /data/DigitVA

test -z "$(git status --porcelain --ignore-submodules=none)" || { echo "staging checkout or submodules are not clean" >&2; exit 1; }
PREVIOUS_COMMIT=$(git rev-parse HEAD)
PREVIOUS_TAG=$(sed -n 's/^DIGITVA_IMAGE_TAG=//p' .env | tail -n1)
test -n "$PREVIOUS_TAG" || { echo "DIGITVA_IMAGE_TAG is missing from .env" >&2; exit 1; }
ENV_REST=$(grep -v '^DIGITVA_IMAGE_TAG=' .env | sha256sum | cut -d' ' -f1)

test "$(df --output=avail / | tail -1 | tr -d ' ')" -gt 6000000 || { echo "less than 6 GB free on /" >&2; exit 1; }
grep -qx 'DIGITVA_ANDROID_APK_DIR=/app/private/android-hosted' .env || { echo "hosted APK override is missing or unexpected" >&2; exit 1; }
test -d private/android-hosted || { echo "hosted APK directory is missing" >&2; exit 1; }
find private/android-hosted -maxdepth 1 -type f -name '*.apk' -print -quit | grep -q . || { echo "no hosted APK found" >&2; exit 1; }
APK_MANIFEST=$(mktemp)
trap 'result=$?; rm -f "$APK_MANIFEST"; if [ "$result" -ne 0 ]; then printf "Deployment failed; previous commit %s, image %s. Rollback on the host: sudo -Hu ubuntu env SKIP_BACKUP=1 bash scripts/deploy-server.sh %s\n" "$PREVIOUS_COMMIT" "$PREVIOUS_TAG" "$PREVIOUS_TAG" >&2; fi' EXIT
find private/android-hosted -maxdepth 1 -type f -name '*.apk' -print0 | sort -z | xargs -0 sha256sum > "$APK_MANIFEST"

git fetch -q origin --tags
git cat-file -e "$DEPLOY_SHA^{commit}" || { echo "requested commit is unavailable" >&2; exit 1; }
IMAGE="ghcr.io/drguptavivek/digitva-app:$DEPLOY_SHA"
docker manifest inspect "$IMAGE" >/dev/null || { echo "requested image is unreadable" >&2; exit 1; }

echo "Creating and verifying the database backup"
docker exec minerva_app flask backups db-dump --no-prune >/dev/null
BACKUP_LIST=$(docker exec minerva_app flask backups db-list --limit 1 2>&1)
printf '%s\n' "$BACKUP_LIST"
printf '%s\n' "$BACKUP_LIST" | grep -qi success || { echo "latest database backup is not successful" >&2; exit 1; }

echo "Deploying $DEPLOY_SHA (previous commit $PREVIOUS_COMMIT, image tag $PREVIOUS_TAG)"
if ! DEPLOY_OUTPUT=$(env SKIP_BACKUP=1 bash scripts/deploy-server.sh "$DEPLOY_SHA" 2>&1); then
  printf '%s\n' "$DEPLOY_OUTPUT" | tail -60 >&2
  exit 1
fi
printf '%s\n' "$DEPLOY_OUTPUT" | tail -35
test "$(docker inspect -f '{{.Config.Image}}' minerva_app)" = "$IMAGE"
test "$(docker inspect -f '{{.State.Health.Status}}' minerva_app)" = healthy
grep -qx 'DIGITVA_ANDROID_APK_DIR=/app/private/android-hosted' .env
test "$(grep -v '^DIGITVA_IMAGE_TAG=' .env | sha256sum | cut -d' ' -f1)" = "$ENV_REST" || { echo ".env settings changed during deployment" >&2; exit 1; }
sha256sum -c "$APK_MANIFEST"
echo "DEPLOY_STAGING_OK previous_commit=$PREVIOUS_COMMIT previous_tag=$PREVIOUS_TAG rollback='sudo -Hu ubuntu env SKIP_BACKUP=1 bash scripts/deploy-server.sh $PREVIOUS_TAG'"
REMOTE
)

# Pass the program as an argument so child commands cannot consume its source from stdin.
QUOTED_SCRIPT=$(printf '%s' "$REMOTE_SCRIPT" | python3 -c 'import shlex, sys; print(shlex.quote(sys.stdin.read()))')
REMOTE_COMMAND="sudo -Hu ubuntu env DEPLOY_SHA=$TAG bash -c $QUOTED_SCRIPT"
OUTPUT=$(LT_TARGET=i-0b2caee6465bfcac1 AWS_PROFILE=digitva AWS_REGION=ap-south-1 bash "$ROOT/scripts/ssm.sh" "$REMOTE_COMMAND")
printf '%s\n' "$OUTPUT"
grep -q 'DEPLOY_STAGING_OK ' <<<"$OUTPUT" || { echo "SSM command did not report successful deployment" >&2; exit 1; }
