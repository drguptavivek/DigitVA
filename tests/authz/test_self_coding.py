"""Coder implies interviewer in a self-coding project (digitva-xuxk).

Derived when grants are read (``grants._implied_interviewer_grants``): no
grant row, same scope, never for a mentoring institute member, and only while
the project's web intake is on. Policy: docs/policy/access-control-model.md,
"Implied roles".
"""
import uuid
from types import SimpleNamespace

import flask
import sqlalchemy as sa

from app import db
from app.models import VaProjectMaster, VaUserAccessGrants
from app.services import web_intake_service as intake_svc
from app.services.authz import grant_cache, resolve_grants
from app.services.authz.predicates import role_flags
from tests.authz.fixture import SP, TA, AuthzFixtureMixin, P, R, U
from tests.base import BaseTestCase


def _set_project(project_id, **values):
    project = db.session.get(VaProjectMaster, project_id)
    for key, value in values.items():
        setattr(project, key, value)
    db.session.commit()


def _interviewer_grants(user):
    return [g for g in resolve_grants(user).of({R.interviewer}, virtual=False)]


class ImpliedInterviewerTests(AuthzFixtureMixin, BaseTestCase):

    def test_off_by_default(self):
        user = self.users["coder_sp"]
        self.assertTrue(list(resolve_grants(user).of({R.coder}, virtual=False)))
        self.assertEqual(_interviewer_grants(user), [])
        self.assertFalse(user.is_interviewer())

    def test_a_project_coder_gets_a_project_interviewer(self):
        _set_project(SP, self_coding_enabled=True, web_intake_mode="both")
        user = self.users["coder_sp"]
        coder = next(resolve_grants(user).of({R.coder}, virtual=False))
        [implied] = _interviewer_grants(user)
        self.assertEqual(
            (implied.scope_type, implied.project_id, implied.virtual, implied.opens_gate),
            (P, SP, False, coder.opens_gate),
        )
        self.assertIn("interviewer", role_flags(user))
        self.assertTrue(user.is_interviewer())
        # No row was written for it.
        roles = set(db.session.scalars(
            sa.select(VaUserAccessGrants.role).where(VaUserAccessGrants.user_id == user.user_id)
        ))
        self.assertEqual(roles, {R.coder})

    def test_a_unit_coder_gets_the_interviewer_at_the_same_unit(self):
        _set_project(TA, self_coding_enabled=True, web_intake_mode="direct")
        user = self.users["coder_p1"]
        coder = next(resolve_grants(user).of({R.coder}, virtual=False))
        [implied] = _interviewer_grants(user)
        self.assertEqual(
            (implied.scope_type, implied.org_unit_id, implied.unit_depth, implied.unit_path),
            (U, coder.org_unit_id, coder.unit_depth, coder.unit_path),
        )

    def test_a_site_coder_gets_a_site_interviewer(self):
        _set_project(SP, self_coding_enabled=True, web_intake_mode="both")
        user = self.users["coder_sp1"]
        coder = next(resolve_grants(user).of({R.coder}, virtual=False))
        [implied] = _interviewer_grants(user)
        self.assertEqual((implied.site_id, implied.project_site_id), (coder.site_id, coder.project_site_id))
        self.assertEqual(coder.site_id, "AZS1")

    def test_only_a_coder_implies_it(self):
        _set_project(SP, self_coding_enabled=True, web_intake_mode="both")
        for key in ("tester_sp", "dm_sp", "collabpii_sp"):
            user = self.users[key]
            self.assertTrue(resolve_grants(user).grants, key)
            self.assertEqual(_interviewer_grants(user), [], key)

    def test_a_coder_elsewhere_gets_nothing(self):
        _set_project(SP, self_coding_enabled=True, web_intake_mode="both")
        user = self.users["coder_ta"]  # coder on TA, which is not self-coding
        self.assertTrue(list(resolve_grants(user).of({R.coder}, virtual=False)))
        self.assertEqual(_interviewer_grants(user), [])

    def test_intake_off_switches_it_off(self):
        _set_project(SP, self_coding_enabled=True, web_intake_mode="both")
        user = self.users["coder_sp"]
        self.assertEqual(len(_interviewer_grants(user)), 1)
        _set_project(SP, web_intake_mode="off")
        self.assertEqual(_interviewer_grants(user), [])

    def test_an_explicit_interviewer_grant_is_not_doubled(self):
        _set_project(SP, self_coding_enabled=True, web_intake_mode="both")
        user = self.users["coder_sp"]
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=R.interviewer, scope_type=P, project_id=SP,
        ))
        db.session.commit()
        self.assertEqual(len(_interviewer_grants(user)), 1)

    def test_a_view_only_above_scope_coder_does_not_interview(self):
        _set_project(TA, self_coding_enabled=True, web_intake_mode="direct")
        user = self.users["coder_ta"]  # project coder; TA is view_only above PHC
        coder = next(resolve_grants(user).of({R.coder}, virtual=False))
        self.assertFalse(resolve_grants(user).codes(coder))
        self.assertEqual(_interviewer_grants(user), [])
        _set_project(TA, above_scope_coding_mode="code_any")
        self.assertEqual(len(_interviewer_grants(user)), 1)

    def test_a_mentoring_institute_member_is_excluded(self):
        _set_project(TA, self_coding_enabled=True, web_intake_mode="direct")
        mentor, plain = self.users["mentor"], self.users["coder_p1"]
        # Same shape of grant (coder at P1): subject present for both.
        for user in (mentor, plain):
            self.assertEqual(len(list(resolve_grants(user).of({R.coder}, virtual=False))), 1)
        self.assertEqual(len(_interviewer_grants(plain)), 1)
        self.assertEqual(_interviewer_grants(mentor), [])
        self.assertFalse(mentor.is_interviewer())

    def test_the_mentor_lookup_runs_only_with_a_candidate(self):
        from tests.authz.test_grants import count_queries

        user = SimpleNamespace(user_id=self.users["coder_sp"].user_id)
        with count_queries() as statements:
            resolve_grants(user)
        self.assertFalse([s for s in statements if "map_mentor_institute_user" in s])
        _set_project(SP, self_coding_enabled=True, web_intake_mode="both")
        with count_queries() as statements:
            resolve_grants(user)
        self.assertEqual(len([s for s in statements if "map_mentor_institute_user" in s]), 1)


class InterviewerContextTests(AuthzFixtureMixin, BaseTestCase):
    """``interviewer_context`` reads the resolved interviewer grants."""

    def test_a_plain_project_interviewer_lists_the_projects_sites(self):
        user = self.users["interviewer_p1"]
        context = intake_svc.interviewer_context(user)
        # Unit grant on a project that has web intake off: nothing offered.
        self.assertEqual(context, [])
        _set_project(TA, web_intake_mode="both")
        context = intake_svc.interviewer_context(user)
        self.assertEqual({(e["project_id"], e["site_id"]) for e in context}, {(TA, "AZS1"), (TA, "AZS2")})
        for entry in context:
            self.assertEqual(
                set(entry),
                {"project_id", "project_name", "site_id", "site_name", "web_intake_mode", "org_units"},
            )
            [unit] = entry["org_units"]
            self.assertEqual(set(unit), {"org_unit_id", "unit_code", "unit_name", "path"})
            self.assertEqual(unit["unit_code"], "P1")

    def test_an_implied_interviewer_has_the_same_context(self):
        _set_project(TA, web_intake_mode="both")
        plain = intake_svc.interviewer_context(self.users["interviewer_p1"])
        self.assertTrue(plain)
        self.assertEqual(intake_svc.interviewer_context(self.users["coder_p1"]), [])
        _set_project(TA, self_coding_enabled=True)
        self.assertEqual(intake_svc.interviewer_context(self.users["coder_p1"]), plain)

    def test_a_project_coder_lists_the_sites_with_forms(self):
        _set_project(SP, web_intake_mode="both")
        self.assertEqual(intake_svc.interviewer_context(self.users["coder_sp"]), [])
        _set_project(SP, self_coding_enabled=True)
        context = intake_svc.interviewer_context(self.users["coder_sp"])
        # AZS4's project-site is inactive: not offered.
        self.assertEqual({(e["project_id"], e["site_id"]) for e in context}, {(SP, "AZS1"), (SP, "AZS3")})
        self.assertTrue(all(e["org_units"] == [] for e in context))
        site_only = intake_svc.interviewer_context(self.users["coder_sp1"])
        self.assertEqual({(e["project_id"], e["site_id"]) for e in site_only}, {(SP, "AZS1")})

    def test_unit_grants_cost_a_fixed_number_of_queries(self):
        from tests.authz.test_grants import count_queries

        _set_project(TA, web_intake_mode="both")
        user = self.users["interviewer_p1"]
        with count_queries() as statements:
            intake_svc.interviewer_context(user)
        # Two grant queries (nothing is cached outside a request), then the
        # units, sites, projects, site names and active pairs.
        selects = [s for s in statements if s.startswith("SELECT") and "FROM va_users" not in s]
        self.assertEqual(len(selects), 7, selects)


class ImpliedInterviewerCacheTests(AuthzFixtureMixin, BaseTestCase):
    """The Redis cache sees the setting flip (global version bump)."""

    def setUp(self):
        super().setUp()
        self.prefix = f"digitva_authz_test_{uuid.uuid4().hex}:"
        for key, value in (
            ("AUTHZ_GRANT_CACHE_ENABLED", True),
            ("AUTHZ_GRANT_CACHE_PREFIX", self.prefix),
        ):
            previous = self.app.config.get(key)
            self.app.config[key] = value
            self.addCleanup(self.app.config.__setitem__, key, previous)
        self.redis = grant_cache._client()
        self.assertIsNotNone(self.redis)
        self.addCleanup(self._drop_keys)

    def _drop_keys(self):
        keys = list(self.redis.scan_iter(self.prefix + "*"))
        if keys:
            self.redis.delete(*keys)

    def _resolve(self, user):
        with flask.current_app.test_request_context("/"):
            return resolve_grants(user)

    def test_flipping_the_setting_changes_the_next_resolution(self):
        user = self.users["coder_sp"]
        self.assertTrue(any(self._resolve(user).of({R.coder}, virtual=False)))
        self.assertFalse(any(self._resolve(user).of({R.interviewer}, virtual=False)))
        _set_project(SP, self_coding_enabled=True, web_intake_mode="both")
        self.assertEqual(len(list(self._resolve(user).of({R.interviewer}, virtual=False))), 1)
        _set_project(SP, self_coding_enabled=False)
        self.assertFalse(any(self._resolve(user).of({R.interviewer}, virtual=False)))

    def test_the_intake_mode_flip_also_bumps(self):
        _set_project(SP, self_coding_enabled=True, web_intake_mode="both")
        user = self.users["coder_sp"]
        self.assertEqual(len(list(self._resolve(user).of({R.interviewer}, virtual=False))), 1)
        _set_project(SP, web_intake_mode="off")
        self.assertFalse(any(self._resolve(user).of({R.interviewer}, virtual=False)))

    def test_a_cached_entry_round_trips_the_flag(self):
        _set_project(SP, self_coding_enabled=True, web_intake_mode="both")
        user = self.users["coder_sp"]
        resolved = self._resolve(user)
        self.assertTrue(resolved.projects[SP].self_coding)
        decoded = grant_cache.decode(grant_cache.encode(resolved), user.user_id)
        self.assertEqual(decoded, resolved)
        # The grant's source and the settings the access summary reports survive.
        self.assertEqual(
            {(g.role, g.source) for g in decoded.grants if not g.virtual},
            {(R.coder, "assigned"), (R.interviewer, "self_coding")},
        )
        self.assertEqual(decoded.projects[SP].web_intake_mode, "both")
        tree = grant_cache.decode(grant_cache.encode(self._resolve(self.users["coder_p1"])),
                                  self.users["coder_p1"].user_id)
        self.assertEqual(tree.projects[TA].scope_level_code, "phc")

    def test_a_mentor_membership_change_drops_the_cached_entry(self):
        from app.services import mentor_institute_service as mentors

        _set_project(TA, self_coding_enabled=True, web_intake_mode="direct")
        user = self.users["mentor"]
        self.assertFalse(any(self._resolve(user).of({R.interviewer}, virtual=False)))
        mentors.remove_member("AZMI", user.email)
        db.session.commit()
        self.assertEqual(len(list(self._resolve(user).of({R.interviewer}, virtual=False))), 1)

    def test_flipping_the_institute_drops_its_members_cached_entry(self):
        from app.services import mentor_institute_service as mentors

        _set_project(TA, self_coding_enabled=True, web_intake_mode="direct")
        user = self.users["mentor"]
        self.assertFalse(any(self._resolve(user).of({R.interviewer}, virtual=False)))
        mentors.set_institute_active("AZMI", False)
        db.session.commit()
        self.assertEqual(len(list(self._resolve(user).of({R.interviewer}, virtual=False))), 1)
        mentors.set_institute_active("AZMI", True)
        db.session.commit()
        self.assertFalse(any(self._resolve(user).of({R.interviewer}, virtual=False)))
