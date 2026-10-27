#!/usr/bin/env bash
# Deploy a CI-built server image on the app host. Run ON the server, from the
# checkout, as the checkout's owner (over SSM):
#
#   scripts/deploy-server.sh <full-git-sha>      # sha of a server-images build
#   make prod-rollback TAG=<previous-sha>        # same script, SKIP_BACKUP=1
#
# Nothing is built here (docs/policy/server-builds.md). Steps: image exists in
# the registry; verified DB dump; checkout the sha (compose/config and the
# bind-mounted code must match the image); pin DIGITVA_IMAGE_TAG in .env;
# make prod-pull; wait healthy; migrations at head; disk report; prune old
# images keeping this tag and the previous one. The ingress shows the
# maintenance page from just before the pull until migrations are at head
# (flag file below, docs/current-state/split-production-deploy.md).
set -euo pipefail
cd "$(dirname "$0")/.."

TAG="${1:?usage: $0 <full 40-char git sha>}"
[[ "$TAG" =~ ^[0-9a-f]{40}$ ]] || { echo "TAG must be a full lowercase git sha" >&2; exit 1; }

REGISTRY="${DIGITVA_IMAGE_REGISTRY:-$(sed -n 's/^DIGITVA_IMAGE_REGISTRY=//p' .env | tail -n1)}"
REGISTRY="${REGISTRY:-ghcr.io/drguptavivek}"
IMAGE="$REGISTRY/digitva-app"
DB_ENV="${PROD_DB_ENV:-/data/digitva-db.env}"

DC="docker compose"
[ -f "$DB_ENV" ] && DC="docker compose --env-file .env --env-file $DB_ENV -f docker-compose.yml -f docker-compose.external-db.yml"
DC="$DC -f docker-compose.images.yml"

PREV_TAG="$(sed -n 's/^DIGITVA_IMAGE_TAG=//p' .env | tail -n1)"
PREV_COMMIT="$(git rev-parse HEAD)"
trap 'echo "FAILED. Previous: tag ${PREV_TAG:-none}, commit $PREV_COMMIT. Roll back: make prod-rollback TAG=${PREV_TAG:-<sha>}" >&2' ERR

# Maintenance page flag, read per request by the ingress. EXIT, not ERR: the
# explicit `exit 1` checks below do not fire ERR. On failure the page is lifted
# only if the app is healthy; a broken app keeps showing it, not raw errors.
MAINT_FLAG="$PWD/deploy/maintenance/on"
trap '[ $? -eq 0 ] || [ ! -e "$MAINT_FLAG" ] || {
  if [ "$(docker inspect -f "{{.State.Health.Status}}" minerva_app 2>/dev/null)" = healthy ]; then rm -f "$MAINT_FLAG"
  else echo "App not healthy: maintenance page left ON. Remove with: rm $MAINT_FLAG" >&2; fi; }' EXIT

echo "== 1. image $IMAGE:$TAG in the registry"
docker manifest inspect "$IMAGE:$TAG" >/dev/null \
  || { echo "image $IMAGE:$TAG not found (run the Server images workflow, and docker login ghcr.io)" >&2; exit 1; }

echo "== 2. verified database backup"
if [ "${SKIP_BACKUP:-0}" = 1 ]; then
  echo "skipped (SKIP_BACKUP=1)"
else
  $DC exec -T minerva_app_service flask backups db-dump --no-prune
  $DC exec -T minerva_app_service flask backups db-list --limit 1 | head -n1 | grep -qi success \
    || { echo "newest backup is not a success; stopping" >&2; exit 1; }
fi

echo "== 3. checkout $TAG"
[ -z "$(git status --porcelain --ignore-submodules)" ] || { echo "local changes in the checkout; stopping" >&2; exit 1; }
git fetch origin --tags
git checkout --detach "$TAG"
git submodule sync vendor/smartva-analyze
git submodule update --init vendor/smartva-analyze

echo "== 4. pin DIGITVA_IMAGE_TAG in .env"
if grep -q '^DIGITVA_IMAGE_TAG=' .env; then
  sed -i.bak "s/^DIGITVA_IMAGE_TAG=.*/DIGITVA_IMAGE_TAG=$TAG/" .env && rm -f .env.bak
else
  { [ -z "$(tail -c1 .env)" ] || echo; echo "DIGITVA_IMAGE_TAG=$TAG"; } >> .env
fi

echo "== 5. maintenance page on, pull and start (no build)"
touch "$MAINT_FLAG"
# The checkout is bind-mounted over /app, so /app/.venv is a named volume that
# Docker fills from the image only when it is created. Drop it on every deploy
# so the new image's dependencies are used (a stale one broke 2026-10-27).
$DC rm -sf minerva_app_service minerva_celery_worker minerva_celery_beat
docker volume rm -f "${COMPOSE_PROJECT_NAME:-$(basename "$PWD" | tr '[:upper:]' '[:lower:]')}_minerva_venv"
make prod-pull

echo "== 6. wait for the app to be healthy"
for _ in $(seq 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' minerva_app 2>/dev/null)" = healthy ] && break
  sleep 5
done
[ "$(docker inspect -f '{{.State.Health.Status}}' minerva_app)" = healthy ] || { echo "app not healthy after 5 minutes" >&2; exit 1; }

echo "== 7. migrations at head"
heads="$($DC exec -T minerva_app_service flask db heads 2>/dev/null | awk '{print $1}' | sort)"
current="$($DC exec -T minerva_app_service flask db current 2>/dev/null | awk '{print $1}' | sort)"
[ -n "$heads" ] && [ "$heads" = "$current" ] || { echo "db current ($current) != heads ($heads)" >&2; exit 1; }
rm -f "$MAINT_FLAG"
echo "maintenance page off"

echo "== 8. disk"
df -h / /var/lib/docker 2>/dev/null || df -h /
docker system df

echo "== 9. prune old images (keep $TAG and ${PREV_TAG:-none})"
docker images "$IMAGE" --format '{{.Tag}}' | while read -r t; do
  [ "$t" = "$TAG" ] || [ "$t" = "$PREV_TAG" ] || docker rmi "$IMAGE:$t" || true
done
docker image prune -f >/dev/null

echo "deployed $TAG (previous: ${PREV_TAG:-none}, commit $PREV_COMMIT)"
