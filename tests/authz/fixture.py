"""Shared fixtures for the authorization module tests (digitva-0wc, design 8).

Built once per class inside the class transaction (tests/base.py):

* ``AZTA01`` tree project, coding scope level PHC, ``view_only``. Units
  D1 (district) > C1 (CHC) > P1 (PHC) > SC1 (sub-centre); C1 > P2 (PHC);
  D2 (district). Forms on sites AZS1 and AZS2.
* ``AZTB01`` tree project, scope level PHC, ``code_any``. E1 > F1 (CHC) > G1 (PHC).
* ``AZSP01`` site project (no tree). Forms on AZS1 (the same site id as the
  tree project's, so only (project, site) keying separates them), AZS3, and
  AZS4 whose project-site is inactive.
* ``AZCL01`` closed site project; ``AZDM01`` demo-training site project.

Submissions are keyed by short names (``SIDS``); users by role and scope
(``USERS``). ``incharge_c1`` is the In-charge: ``site_pi`` at a unit, a real
grant row since the stage-5 migration lifted the role_scope CHECK.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.services import org_unit_routing_service as routing
from app.services import organization_service as org
from app.services.authz import ResolvedGrants, resolve_grants

R = VaAccessRoles
P = VaAccessScopeTypes.project
PS = VaAccessScopeTypes.project_site
U = VaAccessScopeTypes.org_unit

TA, TB, SP, CL, DM = "AZTA01", "AZTB01", "AZSP01", "AZCL01", "AZDM01"

# form key -> (form_id, project, site)
FORMS = {
    "ta1": ("AZTA01AZS101", TA, "AZS1"),
    "ta2": ("AZTA01AZS201", TA, "AZS2"),
    "tb1": ("AZTB01AZS501", TB, "AZS5"),
    "sp1": ("AZSP01AZS101", SP, "AZS1"),
    "sp3": ("AZSP01AZS301", SP, "AZS3"),
    "sp4": ("AZSP01AZS401", SP, "AZS4"),
    "cl1": ("AZCL01AZS601", CL, "AZS6"),
    "dm1": ("AZDM01AZS701", DM, "AZS7"),
}
INACTIVE_PAIRS = {(SP, "AZS4")}

# sid key -> (form key, unit key or None)
SIDS = {
    "ta-d1": ("ta1", "D1"),
    "ta-c1": ("ta1", "C1"),
    "ta-p1": ("ta1", "P1"),
    "ta-sc1": ("ta1", "SC1"),
    "ta-p2": ("ta1", "P2"),
    "ta-d2": ("ta1", "D2"),
    "ta-unr": ("ta1", None),
    "ta-s2": ("ta2", None),
    "tb-f1": ("tb1", "F1"),
    "tb-g1": ("tb1", "G1"),
    "tb-unr": ("tb1", None),
    "sp-1": ("sp1", None),
    "sp-3": ("sp3", None),
    "sp-4": ("sp4", None),
    "cl-1": ("cl1", None),
    "dm-1": ("dm1", None),
}

# unit key -> (project, level code, parent key, unit code)
UNITS = {
    "D1": (TA, "district", None, "D1"),
    "C1": (TA, "chc", "D1", "C1"),
    "P1": (TA, "phc", "C1", "P1"),
    "SC1": (TA, "subcentre", "P1", "SC1"),
    "P2": (TA, "phc", "C1", "P2"),
    "D2": (TA, "district", None, "D2"),
    "E1": (TB, "district", None, "E1"),
    "F1": (TB, "chc", "E1", "F1"),
    "G1": (TB, "phc", "F1", "G1"),
}

# user key -> [(role, scope, where)]; where = project id, (project, site) or unit key
USERS = {
    "admin": "base_admin",
    "nobody": [],
    "pi_ta": [(R.project_pi, P, TA)],
    "pi_sp": [(R.project_pi, P, SP)],
    "sitepi_sp1": [(R.site_pi, PS, (SP, "AZS1"))],
    "dm_ta": [(R.data_manager, P, TA)],
    "dm_ta_s1": [(R.data_manager, PS, (TA, "AZS1"))],
    "dm_c1": [(R.data_manager, U, "C1")],
    "dm_sp": [(R.data_manager, P, SP)],
    "dm_sp1": [(R.data_manager, PS, (SP, "AZS1"))],
    "coder_ta": [(R.coder, P, TA)],
    "coder_ta_s1": [(R.coder, PS, (TA, "AZS1"))],
    "coder_c1": [(R.coder, U, "C1")],
    "coder_p1": [(R.coder, U, "P1")],
    "coder_tb": [(R.coder, P, TB)],
    "coder_f1": [(R.coder, U, "F1")],
    "coder_sp": [(R.coder, P, SP)],
    "coder_sp1": [(R.coder, PS, (SP, "AZS1"))],
    "tester_ta": [(R.coding_tester, P, TA)],
    "tester_c1": [(R.coding_tester, U, "C1")],
    "tester_sp": [(R.coding_tester, P, SP)],
    "reviewer_ta": [(R.reviewer, P, TA)],
    "reviewer_c1": [(R.reviewer, U, "C1")],
    "reviewer_p1": [(R.reviewer, U, "P1")],
    "reviewer_sp1": [(R.reviewer, PS, (SP, "AZS1"))],
    "collab_c1": [(R.collaborator, U, "C1")],
    "collabpii_sp": [(R.collaborator_pii, P, SP)],
    "interviewer_p1": [(R.interviewer, U, "P1")],
    "supervisor_c1": [(R.interview_supervisor, U, "C1")],
    # Mentoring institute member (attached to D1): mentor roles at units only.
    "mentor": [(R.coder, U, "P1"), (R.collaborator_pii, U, "D1")],
    "mixed": [(R.coder, U, "P1"), (R.collaborator, P, SP)],
    "closed_coder": [(R.coder, P, CL)],
    # The In-charge: site_pi at a unit.
    "incharge_c1": [(R.site_pi, U, "C1")],
}


class AuthzFixtureMixin:
    """Seeds the projects, tree, forms, submissions and users once per class."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        stamps = dict(project_registered_at=now, project_updated_at=now)
        for project_id in (TA, TB, SP, CL, DM):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id,
                project_name=project_id, project_nickname=project_id,
                project_status=VaStatuses.deactive if project_id == CL else VaStatuses.active,
                coding_intake_mode="pick_and_choose",
                demo_training_enabled=project_id == DM,
                **stamps,
            ))
            db.session.add(VaResearchProjects(
                project_id=project_id, project_code=project_id,
                project_name=project_id, project_nickname=project_id,
                project_status=VaStatuses.active, **stamps,
            ))
        sites = sorted({site for _, _, site in FORMS.values()})
        for site_id in sites:
            db.session.add(VaSiteMaster(
                site_id=site_id, site_abbr=site_id, site_name=site_id,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        for site_id in sites:
            owner = next(p for _, p, s in FORMS.values() if s == site_id)
            db.session.add(VaSites(
                site_id=site_id, project_id=owner, site_name=site_id, site_abbr=site_id,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        cls.project_site_ids = {}
        for form_id, project_id, site_id in FORMS.values():
            pair = VaProjectSites(
                project_id=project_id, site_id=site_id,
                project_site_status=(
                    VaStatuses.deactive if (project_id, site_id) in INACTIVE_PAIRS
                    else VaStatuses.active
                ),
                project_site_registered_at=now, project_site_updated_at=now,
            )
            db.session.add(pair)
            db.session.flush()
            cls.project_site_ids[(project_id, site_id)] = pair.project_site_id
            db.session.add(VaForms(
                form_id=form_id, project_id=project_id, site_id=site_id,
                odk_form_id=f"AZ_{form_id}", odk_project_id="95",
                form_type="WHO VA 2022", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        db.session.flush()

        cls.units = {}
        for project_id in (TA, TB):
            org.seed_default_organization(project_id)
        levels = {
            project_id: {lv.level_code: lv for lv in org.list_levels(project_id)}
            for project_id in (TA, TB)
        }
        for key, (project_id, level_code, parent, code) in UNITS.items():
            cls.units[key] = org.create_unit(
                project_id, org_level_id=levels[project_id][level_code].org_level_id,
                parent_org_unit_id=cls.units[parent].org_unit_id if parent else None,
                unit_code=code, unit_name=code,
            )
        for project_id, mode in ((TA, "view_only"), (TB, "code_any")):
            project = db.session.get(VaProjectMaster, project_id)
            project.coding_scope_level_id = levels[project_id]["phc"].org_level_id
            project.above_scope_coding_mode = mode
        db.session.flush()

        for sid, (form_key, unit_key) in SIDS.items():
            unit = cls.units.get(unit_key)
            db.session.add(VaSubmissions(
                va_sid=sid, va_form_id=FORMS[form_key][0], va_submission_date=now,
                va_odk_updatedat=now, va_data_collector="Collector",
                va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
                va_consent="yes", va_narration_language="English",
                va_deceased_age=42, va_deceased_gender="male",
                va_summary=[], va_catcount={}, va_category_list=[],
                org_unit_id=unit.org_unit_id if unit else None,
                org_unit_resolution=routing.RESOLUTION_FORM_FIELD if unit else None,
            ))
        db.session.flush()

        cls.users = {}
        for key, grants in USERS.items():
            if grants == "base_admin":
                cls.users[key] = cls.base_admin_user
                continue
            user = cls._get_or_make_user(f"authz.{key}@test.local", "AuthzTest123")
            for role, scope, where in grants:
                db.session.add(cls._grant_row(user, role, scope, where))
            cls.users[key] = user
        db.session.flush()

        from app.services import mentor_institute_service as mentors

        mentors.create_institute("AZMI", "Authz Mentor Institute")
        mentors.attach_district("AZMI", TA, "D1")
        mentors.add_member("AZMI", cls.users["mentor"].email)
        db.session.commit()

    @classmethod
    def _grant_row(cls, user, role, scope, where):
        kwargs = dict(user_id=user.user_id, role=role, scope_type=scope,
                      grant_status=VaStatuses.active)
        if scope == P:
            kwargs["project_id"] = where
        elif scope == PS:
            kwargs["project_site_id"] = cls.project_site_ids[where]
        else:
            kwargs["org_unit_id"] = cls.units[where].org_unit_id
        return VaUserAccessGrants(**kwargs)

    # -- lookups -----------------------------------------------------------

    def user(self, key):
        return self.users[key]

    def grants_for(self, key) -> ResolvedGrants:
        """Resolved grants of *key*."""
        return resolve_grants(self.users[key])

    def target(self, key):
        """Resolve a matrix target key to the object ``can`` takes."""
        kind, _, rest = key.partition(":")
        if not rest:
            return key  # a va_sid
        if kind == "form":
            return FORMS[rest][0]
        if kind == "proj":
            return rest
        if kind == "pair":
            project_id, site_id = rest.split("/")
            return ("pair", project_id, site_id)
        if kind in ("unit", "pin"):
            return ("unit", self.units[rest].org_unit_id)
        if kind == "sitecase":
            project_id, site_id = rest.split("/")
            return SimpleNamespace(project_id=project_id, site_id=site_id, org_unit_id=None)
        if kind == "case":
            unit = self.units[rest]
            site_id = next(s for _, p, s in FORMS.values() if p == unit.project_id)
            return SimpleNamespace(
                project_id=unit.project_id, site_id=site_id, org_unit_id=unit.org_unit_id
            )
        raise KeyError(key)

    def all_sids(self) -> set[str]:
        return set(SIDS)

    def scoped_sids(self, predicate) -> set[str]:
        return set(db.session.scalars(
            sa.select(VaSubmissions.va_sid).where(
                VaSubmissions.va_sid.in_(sorted(SIDS)), predicate
            )
        ).all())
