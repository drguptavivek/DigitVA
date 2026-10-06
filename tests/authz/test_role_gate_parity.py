"""role_required decides from authz.effective_roles (digitva-5hmc, item 1).

Before, each gate called a ``VaUsers.is_*`` predicate, several of them
form-resolved (``_get_granted_va_forms``). The parity table below runs every
fixture user through both the legacy predicate and the new gate, so a user
whose gate opens or closes differently fails by name.

``mentor_institute_admin`` is a membership flag, not a grant: effective_roles
does not answer it and the gate keeps its predicate.
"""
from datetime import UTC, datetime

import flask
import sqlalchemy as sa

from app import db
from app.decorators.role_required import _ROLE_METHODS
from app.models import VaProjectMaster, VaStatuses, VaUserAccessGrants
from app.services.authz import effective_roles
from tests.authz.fixture import DM, AuthzFixtureMixin, P, R
from tests.base import BaseTestCase

# Each role -> the predicate role_required called before this change.
LEGACY = {
    "admin": lambda u: u.is_admin(),
    "coder": lambda u: u.is_coder(),
    "coding_tester": lambda u: u.is_coding_tester(),
    "reviewer": lambda u: u.is_reviewer(),
    "data_manager": lambda u: u.is_data_manager(),
    "site_pi": lambda u: u.is_site_pi(),
    "project_pi": lambda u: u.is_project_pi(),
    "interviewer": lambda u: u.is_interviewer(),
    "death_reporter": lambda u: u.is_death_reporter(),
    "interview_supervisor": lambda u: u.is_interview_supervisor(),
    "mentor_institute_admin": lambda u: u.is_mentor_institute_admin(),
    "collaborator": lambda u: u.is_viewer(),
    "collaborator_pii": lambda u: u.is_viewer(),
}

NO_FORMS_PROJECT = "AZNF01"


class RoleGateParityTests(AuthzFixtureMixin, BaseTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A project with no forms at all: the case the form-resolved legacy
        # predicates and the grant-resolved gate could disagree on.
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=NO_FORMS_PROJECT, project_code=NO_FORMS_PROJECT,
            project_name=NO_FORMS_PROJECT, project_nickname=NO_FORMS_PROJECT,
            project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now,
        ))
        db.session.flush()
        cls.formless = {}
        for role in (R.coder, R.coding_tester, R.reviewer, R.interviewer):
            user = cls._get_or_make_user(f"authz.formless.{role.value}@test.local", "AuthzTest123")
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, scope_type=P,
                project_id=NO_FORMS_PROJECT, grant_status=VaStatuses.active,
            ))
            cls.formless[role.value] = user
        db.session.commit()

    def test_the_table_covers_every_gate(self):
        self.assertEqual(set(LEGACY), set(_ROLE_METHODS))

    def test_every_fixture_user_opens_the_same_gates_as_before(self):
        users = dict(self.users)
        users.update({f"formless_{k}": v for k, v in self.formless.items()})
        # Presence first: the table is not vacuous.
        self.assertIn("coder", effective_roles(self.users["coder_ta"]))
        self.assertTrue(self.users["coder_ta"].is_coder())
        mismatches = []
        for key, user in sorted(users.items()):
            for role, legacy in LEGACY.items():
                with flask.current_app.test_request_context("/"):
                    before = bool(legacy(user))
                with flask.current_app.test_request_context("/"):
                    after = bool(_ROLE_METHODS[role](user))
                if before != after:
                    mismatches.append(f"{key}: {role} legacy={before} gate={after}")
        self.assertEqual(mismatches, [])

    def test_a_grant_on_a_project_with_no_forms_and_no_demo(self):
        """With no active demo project to mask it, the form-resolved
        ``is_coder``/``is_coding_tester``/``is_reviewer``/``is_interviewer``
        refuse a project grant that reaches no active form yet; so does the
        gate (``Grant.opens_gate``)."""
        demo = db.session.get(VaProjectMaster, DM)
        demo.demo_training_enabled = False
        db.session.flush()
        mismatches = []
        for role, user in sorted(self.formless.items()):
            with flask.current_app.test_request_context("/"):
                before = bool(LEGACY[role](user))
            with flask.current_app.test_request_context("/"):
                after = bool(_ROLE_METHODS[role](user))
            if before != after:
                mismatches.append(f"{role} legacy={before} gate={after}")
        self.assertEqual(mismatches, [])
        with flask.current_app.test_request_context("/"):
            self.assertFalse(_ROLE_METHODS["coder"](self.formless["coder"]))
            self.assertTrue(_ROLE_METHODS["coder"](self.users["coder_ta"]))

    def test_the_gate_reads_effective_roles_not_the_user_predicates(self):
        user = self.users["coder_ta"]
        self.assertTrue(_ROLE_METHODS["coder"](user))
        self.assertFalse(_ROLE_METHODS["data_manager"](user))
        # A grant revoked behind the predicate's back: the gate follows authz.
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == user.user_id,
        ))
        grant.grant_status = VaStatuses.deactive
        db.session.flush()
        with flask.current_app.test_request_context("/"):
            self.assertNotIn("coder", effective_roles(user))
            self.assertFalse(_ROLE_METHODS["coder"](user))

    def test_one_resolution_answers_every_gate_in_a_request(self):
        from tests.authz.test_grants import count_queries

        user = self.users["dm_ta"]
        with flask.current_app.test_request_context("/"):
            self.assertTrue(_ROLE_METHODS["data_manager"](user))
            with count_queries() as statements:
                for role in LEGACY:
                    if role != "mentor_institute_admin":
                        _ROLE_METHODS[role](user)
            self.assertEqual(statements, [])

