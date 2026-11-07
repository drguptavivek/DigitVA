#!/bin/bash
# Find staging accounts whose password is still a documented dev password
# (Admin@123, Aiims@123) and, with --reset, give each a new random password.
#
# usage (from this Mac, owner only):
#   scripts/staging-rotate-dev-passwords.sh            # check: list matching emails, change nothing
#   scripts/staging-rotate-dev-passwords.sh --reset    # reset every match
#
# --reset uses mobile_sign_in_service.set_new_password (audited, ends every
# session). New passwords never go to SSM output (AWS keeps that); they are
# written on the instance to /root/rotated-passwords-<UTC time>.txt (mode 600).
# Read it in an SSM session: sudo cat /root/rotated-passwords-*.txt, then delete it.
set -euo pipefail
MODE="${1:-check}"
[ "$MODE" = "check" ] || [ "$MODE" = "--reset" ] || { echo "usage: $0 [--reset]"; exit 2; }
export LT_TARGET="${LT_TARGET:-i-0b2caee6465bfcac1}" AWS_PROFILE="${AWS_PROFILE:-digitva}" AWS_REGION="${AWS_REGION:-ap-south-1}"

PY=$(cat <<'EOF'
import os, sys
from app import create_app, db
from app.models import VaUsers
from app.services import mobile_sign_in_service
reset = sys.argv[1] == "--reset"
out = sys.argv[2]
app = create_app()
with app.app_context():
    users = db.session.query(VaUsers).all()
    hits = []
    for i, u in enumerate(users, 1):
        if u.password and any(u.check_password(p) for p in ("Admin@123", "Aiims@123")):
            hits.append(u)
        if i % 20 == 0 or i == len(users):
            print(f"Checked {i}/{len(users)} · Found {len(hits)}", flush=True)
    print(f"checked {len(users)} accounts, {len(hits)} use a dev password")
    lines = []
    for u in hits:
        print(f"  {u.email}")
        if reset:
            lines.append(f"{u.email}\t{mobile_sign_in_service.set_new_password(u, path='cli')}")
    if reset and hits:
        db.session.commit()
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"reset {len(hits)}; new passwords in {out} on the host (mode 600)")
EOF
)
B64=$(printf '%s' "$PY" | base64 | tr -d '\n')
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
# Inside the container the file lands in /tmp; it is moved to /root and removed from the container.
REMOTE="echo $B64 | base64 -d > /tmp/rotate.py && sudo docker cp /tmp/rotate.py minerva_app:/tmp/rotate.py && rm /tmp/rotate.py && \
sudo docker exec -w /app -e PYTHONPATH=/app minerva_app python /tmp/rotate.py '$MODE' /tmp/rotated-$STAMP.txt; rc=\$?; \
sudo docker exec minerva_app rm -f /tmp/rotate.py; \
if sudo docker exec minerva_app test -f /tmp/rotated-$STAMP.txt; then \
  sudo docker cp minerva_app:/tmp/rotated-$STAMP.txt /root/rotated-passwords-$STAMP.txt && sudo chmod 600 /root/rotated-passwords-$STAMP.txt && \
  sudo docker exec minerva_app rm -f /tmp/rotated-$STAMP.txt; fi; exit \$rc"
exec "$(dirname "$0")/ssm.sh" "$REMOTE"
