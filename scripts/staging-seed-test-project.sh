#!/bin/bash
# Run `flask seed test-project --staging` on staging over SSM (owner only).
# Idempotent: adds missing TST001 test accounts and grants (e.g. test.all
# interviewer + data_manager). Existing users keep their passwords; new users
# get a random password nobody sees. Run only after the seed change is deployed.
#
# usage: scripts/staging-seed-test-project.sh <active-global-admin-email>
set -euo pipefail
ACTOR="${1:?usage: $0 <active-global-admin-email>}"
export LT_TARGET="${LT_TARGET:-i-0b2caee6465bfcac1}" AWS_PROFILE="${AWS_PROFILE:-digitva}" AWS_REGION="${AWS_REGION:-ap-south-1}"
case "$ACTOR" in *[!A-Za-z0-9@._+-]*) echo "bad email"; exit 2;; esac
exec "$(dirname "$0")/ssm.sh" "sudo docker exec -w /app -e PYTHONPATH=/app -e DIGITVA_ALLOW_TEST_SEED=1 minerva_app flask seed test-project --staging --actor-email '$ACTOR'"
