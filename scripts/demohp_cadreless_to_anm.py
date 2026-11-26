"""Keep the 153 Hamirpur Demo interviewers' access by giving their cadre-less
unit grants the ANM cadre (owner 2026-11-26, digitva-hofh).

All 153 are interviewer grants at DH01 CMO Office (District level) in DEMOHP,
created 2026-11-23, with no worker record. Under the cadre rule
(docs/policy/organization-model.md, "Allowed and default roles per level x
cadre") a health-system unit grant names the person's cadre, so this:

1. places ANM at the District level with interviewer allowed and default
   (as SN already is), keeping any roles the row already has;
2. enrols each person as an ANM worker at DH01 (no invitation, no new grant);
3. sets the ANM cadre on their existing grant and notes it on the row.

It refuses unless the cadre-less list is exactly that set. Dry run by
default (everything is rolled back); --apply --actor <admin email> commits
and writes one grants.log line per grant. Run after a verified backup:

    python - < scripts/demohp_cadreless_to_anm.py            # dry run
    python - --apply --actor <admin email> < scripts/demohp_cadreless_to_anm.py

Prints counts and ids only, no names or emails.
"""

import argparse
import sys
from datetime import UTC, datetime

PROJECT_ID = "DEMOHP"
UNIT_CODE = "DH01"
CADRE_CODE = "ANM"
ROLE = "interviewer"
EXPECTED = 153
NOTE = "Cadre ANM set {date}: kept access under the cadre rule (digitva-hofh, owner 2026-11-26)."


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor", default=None)
    args = parser.parse_args(argv)

    import sqlalchemy as sa

    from app import create_app, db

    app = create_app()
    with app.app_context():
        from app.commands.organization import _cadreless_grants
        from app.logging.va_logger import log_grant_action
        from app.models import MasCadre, MasOrgUnit, MasOrgUnitWorker, VaStatuses, VaUsers
        from app.services import organization_service as org
        from app.services.org_grant_service import validate_org_unit_grant

        def fail(msg):
            db.session.rollback()
            sys.exit(f"REFUSED: {msg}")

        actor = None
        if args.apply:
            actor = db.session.scalar(sa.select(VaUsers).where(
                sa.func.lower(VaUsers.email) == (args.actor or "").strip().lower()
            )) if args.actor else None
            if actor is None or actor.user_status != VaStatuses.active or not actor.is_admin():
                fail("--apply needs --actor, the email of an active global admin.")

        cadreless, outside, borrowed = _cadreless_grants()
        if outside or borrowed:
            fail(f"unexpected mentor grants: {len(outside)} outside, {len(borrowed)} borrowed.")
        unit = db.session.scalar(sa.select(MasOrgUnit).where(
            MasOrgUnit.project_id == PROJECT_ID, MasOrgUnit.unit_code == UNIT_CODE))
        cadre = db.session.scalar(sa.select(MasCadre).where(
            MasCadre.project_id == PROJECT_ID, MasCadre.cadre_code == CADRE_CODE))
        if unit is None or cadre is None:
            fail("DH01 or ANM not found in DEMOHP.")
        grants = [g for g, *_ in cadreless]
        if len(grants) != EXPECTED or any(
            g.org_unit_id != unit.org_unit_id or g.role.value != ROLE for g in grants
        ):
            fail(f"the cadre-less list is not the {EXPECTED} DEMOHP DH01 interviewer grants.")
        user_ids = [g.user_id for g in grants]
        if len(set(user_ids)) != EXPECTED:
            fail("a person holds more than one of these grants.")
        if db.session.scalar(sa.select(sa.func.count()).select_from(MasOrgUnitWorker)
                             .where(MasOrgUnitWorker.user_id.in_(user_ids))):
            fail("some of these people already have a worker record.")

        # 1. ANM at the District level may hold, and by default gets, interviewer.
        row = org.get_level_cadre_permission(unit.org_level_id, cadre.cadre_id)
        allowed = set(row.allowed_roles or ()) if row is not None else set()
        defaults = set(row.default_roles or ()) if row is not None else set()
        org.upsert_level_cadre(
            PROJECT_ID, org_level_id=unit.org_level_id, cadre_id=cadre.cadre_id,
            allowed_roles=sorted(allowed | {ROLE}), default_roles=sorted(defaults | {ROLE}),
        )
        db.session.flush()
        print(f"grid {unit.level.level_code}/{CADRE_CODE}: "
              f"{'new row' if row is None else 'updated'}, allowed and default include {ROLE}")

        # 2 and 3. One ANM worker per person at DH01; the grant carries ANM.
        today = datetime.now(UTC).date().isoformat()
        for g in grants:
            user = db.session.get(VaUsers, g.user_id)
            org.create_worker(PROJECT_ID, org_unit_id=unit.org_unit_id, cadre_id=cadre.cadre_id,
                              worker_name=user.name, user=user)
            g.cadre_id = cadre.cadre_id
            g.notes = f"{g.notes}\n{NOTE.format(date=today)}" if g.notes else NOTE.format(date=today)
        db.session.flush()
        for g in grants:
            validate_org_unit_grant(role=g.role, org_unit_id=g.org_unit_id,
                                    cadre_id=g.cadre_id, user_id=g.user_id)
        left, _, _ = _cadreless_grants()
        print(f"workers created: {len(grants)}; grants given ANM: {len(grants)}; "
              f"cadre-less grants left: {len(left)}")

        if not args.apply:
            db.session.rollback()
            print("Dry run only; rolled back, nothing written.")
            return
        db.session.commit()
        for g in grants:
            log_grant_action(
                action="grant_cadre_assigned", actor_user_id=actor.user_id, actor_role="admin",
                target_user_id=g.user_id, grant_id=g.grant_id, role=g.role.value,
                scope_type=g.scope_type.value, project_id=PROJECT_ID,
                org_unit_id=g.org_unit_id, cadre_id=g.cadre_id,
            )
        print(f"Applied: {len(grants)} grants now carry ANM at {UNIT_CODE}.")


if __name__ == "__main__":
    main(sys.argv[1:])
