"""Snapshot what /api/v1/me/access (cookie and bearer) and
/api/v1/organization/me return for every user, to diff access before and
after a deploy or a grant clean-up (digitva-4650).

    python scripts/me_access_snapshot.py > before.json
    ... deploy, migrate or apply ...
    python scripts/me_access_snapshot.py > after.json
    python scripts/me_access_snapshot.py --diff before.json after.json

The output holds personal data (names, emails, units): keep it on the
server, out of the repo, and delete it after use. ``server_time`` is ignored
by --diff.
"""

import json
import sys


def snapshot():
    from flask import g

    from app import create_app, db

    app = create_app()
    with app.app_context():
        from app.models import VaUsers
        from app.services.access_summary_service import build_access_summary
        from app.services.org_my_organization import my_organization

        out = {}
        for user in db.session.scalars(db.select(VaUsers).order_by(VaUsers.user_id)):
            row = {}
            for mode in ("cookie", "bearer"):
                with app.test_request_context("/api/v1/me/access"):
                    g.bearer_auth = mode == "bearer"
                    row[mode] = build_access_summary(user)
                db.session.rollback()
            with app.test_request_context("/api/v1/organization/me"):
                row["org_me"] = my_organization(user)
            db.session.rollback()
            out[str(user.user_id)] = row
        json.dump(out, sys.stdout, sort_keys=True, default=str, indent=1)


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k != "server_time"}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def diff(before_path, after_path):
    with open(before_path) as fh:
        before = json.load(fh)
    with open(after_path) as fh:
        after = json.load(fh)
    changed = 0
    for user_id in sorted(set(before) | set(after)):
        for mode in ("cookie", "bearer", "org_me"):
            old = _strip((before.get(user_id) or {}).get(mode))
            new = _strip((after.get(user_id) or {}).get(mode))
            if old != new:
                changed += 1
                keys = sorted(k for k in set(old or {}) | set(new or {})
                              if (old or {}).get(k) != (new or {}).get(k))
                print(f"{user_id} {mode}: {', '.join(keys)}")
    print(f"{len(before)} -> {len(after)} users, {changed} changed replies", file=sys.stderr)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--diff"]:
        diff(sys.argv[2], sys.argv[3])
    else:
        snapshot()
