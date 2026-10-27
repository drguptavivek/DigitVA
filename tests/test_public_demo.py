"""Public demo backend core (digitva-77v5.2). Policy: docs/policy/public-demo.md.

Sign-up (web and JSON), the username sign-in branch, the grant guard, the
virtual-grant exclusion, own-case isolation, the per-account limits and
``flask public-demo setup``. The demo project is built once per class by the
real setup service with the flag on.
"""
import io
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest import mock
from urllib.parse import urlparse

import sqlalchemy as sa
from flask_limiter.util import get_remote_address

from app import db, limiter
from app.models import (
    AuthSecurityEvent,
    MasConsentNoticeVersion,
    MasDeathIdentifierType,
    MasOrgUnit,
    MasProjectConsentSettings,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaStatuses,
    VaSubmissionAttachments,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
    VaUsers,
    VaWebIntakeAttachment,
    VaWebIntakeDraft,
)
from app.services import org_unit_routing_service as routing
from app.services import public_demo_service as demo
from app.services import reviewer_dashboard_service
from app.services import user_account_service as accounts
from app.services import web_intake_service as intake
from app.services.attachment_service import can_access_submission_attachment
from app.services.authz import Action, Lens, can, lens_filter, reaches, resolve_grants, scope_filter
from app.services.authz.grant_cache import PublicDemoGrantRefused
from app.services.case_transition_service import WebIntakeError
from app.services.coder_workflow_service import (
    AllocationError,
    allocate_own_case,
    allocate_pick_form,
    allocate_random_form,
    get_pick_available_forms,
)
from app.services.reviewer_coding_service import ReviewerCodingError, start_reviewer_coding
from tests.base import BaseTestCase

PROJECT = "PUB01"
PASSWORD = "plain-demo-password-1"


class PublicDemoBase(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_form_type("WHO_2022_VA", "WHO VA 2022")
        cls._config = mock.patch.dict(
            cls.app.config, PUBLIC_DEMO_ENABLED=True, PUBLIC_DEMO_PROJECT_ID=PROJECT
        )
        cls._config.start()
        # The base test project makes every test database look like the main
        # one; MainDatabaseGuardTests runs the real check.
        cls._database = mock.patch.object(demo, "foreign_projects_exist", return_value=False)
        cls._database.start()
        cls.setup_result = demo.setup_public_demo_project(cls.base_admin_user)
        form = db.session.scalar(sa.select(VaForms).where(
            VaForms.project_id == PROJECT, VaForms.form_source == "web"))
        cls.form_id, cls.site_id = form.form_id, form.site_id
        cls.unit_id = db.session.scalar(sa.select(MasOrgUnit.org_unit_id).where(
            MasOrgUnit.project_id == PROJECT, MasOrgUnit.unit_code == demo.DEMO_UNIT_CODE))

    @classmethod
    def tearDownClass(cls):
        cls._database.stop()
        cls._config.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        limiter.reset()  # in-memory buckets outlive a test

    def _account(self, name):
        user = demo.create_account(name, PASSWORD)
        db.session.commit()
        return user

    def _case(self, owner, sid, state="ready_for_coding"):
        """A demo submission whose submitted draft is *owner*'s."""
        now = datetime.now(UTC)
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=self.form_id, va_submission_date=now,
            va_odk_updatedat=now, va_data_collector="Collector",
            va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
            va_consent="yes", va_narration_language="english",
            va_deceased_age=42, va_deceased_gender="male",
            va_summary=[], va_catcount={}, va_category_list=[], org_unit_id=self.unit_id,
            org_unit_resolution=routing.RESOLUTION_FORM_FIELD,
        ))
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(
            va_sid=sid, workflow_state=state, workflow_reason="test_seed",
            workflow_updated_by_role="vasystem",
        ))
        db.session.add(VaWebIntakeDraft(
            project_id=PROJECT, site_id=self.site_id, form_id=self.form_id,
            user_id=owner.user_id, unique_id=sid, meta={}, prefill={},
            status="submitted", va_sid=sid, submitted_at=now,
        ))
        db.session.commit()

    def _post_signup(self, *, captcha=True, path="/vaauth/signup", **fields):
        from app.services.pow_captcha_service import issue_challenge

        data = {"username": "demo.web", "password": PASSWORD, "confirm": PASSWORD,
                "accept_notice": "y", **fields}
        if captcha:
            challenge = issue_challenge()
            data.update(
                captcha_salt=challenge["salt"], captcha_difficulty=challenge["difficulty"],
                captcha_expires=challenge["expires"], captcha_signature=challenge["signature"],
                captcha_solution=self._solve_pow_captcha(challenge["salt"], challenge["difficulty"]),
            )
        return self.client.post(path, data=data, headers=self._csrf_headers())

    def _captcha(self):
        """A solved challenge from the JSON challenge endpoint."""
        challenge = self.client.get("/api/v1/auth/demo-signup/challenge").get_json()
        return {**challenge, "solution": self._solve_pow_captcha(challenge["salt"], challenge["difficulty"])}

    def _api_signup(self, username, password=PASSWORD, **extra):
        return self.client.post(
            "/api/v1/auth/demo-signup",
            json={"username": username, "password": password, "captcha": self._captcha(), **extra},
        )

    def _user(self, name):
        return db.session.scalar(sa.select(VaUsers).where(VaUsers.username == name))


class IdentifierResolverTests(PublicDemoBase):
    def test_email_mobile_and_username(self):
        self.assertEqual(accounts.sign_in_identifier(" A@B.org "), ("email", "a@b.org"))
        self.assertEqual(accounts.sign_in_identifier("+91 98765-43210"), ("mobile", "9876543210"))
        self.assertEqual(accounts.sign_in_identifier("Demo.User"), ("username", "demo.user"))
        # Letters around ten digits still read as a mobile number, never a username.
        self.assertEqual(accounts.sign_in_identifier("a9876543210"), ("mobile", "9876543210"))
        self.assertEqual(accounts.sign_in_identifier("ab"), ("mobile", ""))

    def test_username_resolves_only_with_the_flag_on(self):
        user = self._account("demo.resolve")
        self.assertEqual(accounts.find_sign_in_user("username", "demo.resolve"), user)
        from app.services.device_auth_service import _sign_in_user

        self.assertEqual(_sign_in_user("Demo.Resolve"), user)
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=False):
            self.assertEqual(accounts.sign_in_identifier("demo.resolve"), ("mobile", ""))
            self.assertIsNone(accounts.find_sign_in_user("username", "demo.resolve"))
            self.assertIsNone(_sign_in_user("demo.resolve"))

    def test_username_account_flags(self):
        user = self._account("demo.flags")
        self.assertTrue(user.sign_in_verified)
        self.assertFalse(user.is_mobile_only)
        self.assertIsNotNone(self.base_coder_user.email)
        self.assertFalse(self.base_coder_user.is_mobile_only)
        from app.services import mobile_sign_in_service

        with self.assertRaises(ValueError):
            mobile_sign_in_service.issue_code(user, actor_user_id=self.base_admin_user.user_id)


class WebSignUpTests(PublicDemoBase):
    def test_sign_up_creates_a_confined_account_and_signs_in(self):
        page = self.client.get("/vaauth/signup")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Do not enter real personal or health data", page.data)
        response = self._post_signup(username="Demo.Web")
        self.assertEqual(response.status_code, 302, response.data[:500])
        user = self._user("demo.web")
        self.assertIsNotNone(user)
        self.assertTrue(user.is_public_demo)
        self.assertIsNone(user.email)
        self.assertEqual(user.other["created_via"], "self_signup")
        self.assertTrue(user.pw_reset_t_and_c)
        self.assertEqual(user.vacode_language, ["english", "hindi"])
        self.assertTrue(user.check_password(PASSWORD))
        self.assertIsNotNone(user.last_signed_in_at)
        grants = db.session.execute(sa.select(
            VaUserAccessGrants.role, VaUserAccessGrants.scope_type, VaUserAccessGrants.project_id,
        ).where(VaUserAccessGrants.user_id == user.user_id)).all()
        self.assertEqual(
            sorted((g.role.value, g.scope_type, g.project_id) for g in grants),
            [(r, VaAccessScopeTypes.project, PROJECT) for r in ("coder", "interviewer", "reviewer")],
        )
        events = set(db.session.scalars(sa.select(AuthSecurityEvent.event_type).where(
            AuthSecurityEvent.user_id == user.user_id)))
        self.assertTrue({"account_created", "terms_accepted", "web_sign_in"} <= events)
        with self.client.session_transaction() as sess:
            self.assertTrue(sess.get("_user_id", "").startswith(str(user.user_id)))

    def test_username_signs_in_with_the_password_login(self):
        self._account("demo.login")
        response = self._login_via_form("Demo.Login", PASSWORD)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("/valogin", urlparse(response.headers["Location"]).path)
        self.client.post("/vaauth/valogout", headers=self._csrf_headers())
        limiter.reset()
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=False):
            refused = self._login_via_form("demo.login", PASSWORD)
        self.assertIn("/valogin/password", refused.headers.get("Location", ""))

    def test_flag_off_is_404_and_creates_nothing(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=False):
            self.assertEqual(self.client.get("/vaauth/signup").status_code, 404)
            self.assertEqual(self._post_signup(username="demo.off").status_code, 404)
            self.assertNotIn(b"/vaauth/signup", self.client.get("/vaauth/valogin").data)
        self.assertIn(b"/vaauth/signup", self.client.get("/vaauth/valogin").data)
        self.assertIsNone(self._user("demo.off"))

    def test_each_refusal_creates_nothing(self):
        cases = [
            ({"username": "1demo"}, "starting with a letter"),
            ({"username": "ab"}, "3 to 30 characters"),
            ({"username": "demo.short", "password": "short-pass", "confirm": "short-pass"}, "at least 12"),
            ({"username": "demo.mismatch", "confirm": PASSWORD + "x"}, "do not match"),
            ({"username": "demo.samename1", "password": "demo.samename1", "confirm": "demo.samename1"},
             "must not be the username"),
        ]
        for fields, message in cases:
            with self.subTest(fields=fields):
                response = self._post_signup(**fields)
                self.assertEqual(response.status_code, 200)
                self.assertIn(message, response.get_data(as_text=True))
                self.assertIsNone(self._user(fields["username"].lower()))

    def test_breached_password_and_unavailable_check(self):
        from app.utils.password_policy import BREACH_CHECK_UNAVAILABLE_MESSAGE

        for result, name in (("Password has been found in known breach data.", "demo.breached"),
                             (BREACH_CHECK_UNAVAILABLE_MESSAGE, "demo.unreachable")):
            with self.subTest(name=name), mock.patch.object(
                demo, "password_breach_error_message", return_value=result
            ):
                response = self._post_signup(username=name)
                self.assertEqual(response.status_code, 200)
                self.assertIn(result, response.get_data(as_text=True))
                self.assertIsNone(self._user(name))

    def test_taken_username_cap_and_missing_captcha(self):
        self._account("demo.taken")
        response = self._post_signup(username="Demo.Taken")
        self.assertIn("already taken", response.get_data(as_text=True))
        no_captcha = self._post_signup(username="demo.nocaptcha", captcha=False)
        self.assertEqual(no_captcha.status_code, 200)
        self.assertIsNone(self._user("demo.nocaptcha"))
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_MAX_ACCOUNTS=demo.active_account_count()):
            capped = self._post_signup(username="demo.capped")
        self.assertIn(demo.CAP_REACHED_MESSAGE, capped.get_data(as_text=True))
        self.assertIsNone(self._user("demo.capped"))

    def test_per_ip_limit_counts_successful_sign_ups(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_SIGNUP_RATE_LIMIT="1 per hour"):
            # A refused attempt does not spend the quota.
            self.assertEqual(self._post_signup(username="1bad").status_code, 200)
            self.assertEqual(self._post_signup(username="demo.first").status_code, 302)
            self.client.post("/vaauth/valogout", headers=self._csrf_headers())
            # The app's 429 handler answers an HTML page with a redirect back.
            limited = self._post_signup(username="demo.second")
            self.assertNotEqual(urlparse(limited.headers.get("Location", "")).path, "/app/")
            # One bucket per IP for both paths: the JSON endpoint shares the web quota.
            shared = self._api_signup("demo.shared")
        self.assertEqual(shared.status_code, 429)
        self.assertIsNone(self._user("demo.second"))
        self.assertIsNone(self._user("demo.shared"))
        limiter.reset()
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_SIGNUP_RATE_LIMIT="1 per hour"):
            first = self._api_signup("demo.apifirst")
            api = self._api_signup("demo.third")
        self.assertEqual((first.status_code, api.status_code), (201, 429))
        self.assertIsNone(self._user("demo.third"))


class JsonSignUpTests(PublicDemoBase):
    def test_demo_signup_returns_201_without_a_session(self):
        response = self._api_signup("Demo.App")
        self.assertEqual(response.status_code, 201, response.get_json())
        user = self._user("demo.app")
        self.assertEqual(response.get_json(), {"user_id": str(user.user_id), "username": "demo.app"})
        self.assertTrue(user.is_public_demo and user.pw_reset_t_and_c)
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)

    def test_refusals_and_flag_off(self):
        bad = self._api_signup("9")
        self.assertEqual((bad.status_code, bad.get_json()["code"], bad.get_json()["fields"]),
                         (400, "invalid_username", ["username"]))
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=False):
            off = self.client.post("/api/v1/auth/demo-signup",
                                   json={"username": "demo.offapi", "password": PASSWORD, "captcha": {}})
            off_challenge = self.client.get("/api/v1/auth/demo-signup/challenge")
        self.assertEqual((off.status_code, off_challenge.status_code), (404, 404))
        self.assertIsNone(self._user("demo.offapi"))


class GrantGuardTests(PublicDemoBase):
    def test_orm_writer_refuses_admin_other_project_and_other_roles(self):
        user = self._account("demo.guard")
        refused = [
            dict(role=VaAccessRoles.admin, scope_type=VaAccessScopeTypes.global_scope),
            dict(role=VaAccessRoles.coder, scope_type=VaAccessScopeTypes.project,
                 project_id=self.BASE_PROJECT_ID),
            dict(role=VaAccessRoles.data_manager, scope_type=VaAccessScopeTypes.project,
                 project_id=PROJECT),
            dict(role=VaAccessRoles.coder, scope_type=VaAccessScopeTypes.org_unit,
                 org_unit_id=self.unit_id),
        ]
        for shape in refused:
            with self.subTest(role=shape["role"].value, scope=shape["scope_type"].value):
                db.session.add(VaUserAccessGrants(user_id=user.user_id,
                                                  grant_status=VaStatuses.active, **shape))
                with self.assertRaises(PublicDemoGrantRefused):
                    db.session.flush()
                db.session.rollback()

    def test_reactivation_and_reshaping_are_guarded_and_the_three_roles_allowed(self):
        user = self._account("demo.reshape")
        coder = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == user.user_id, VaUserAccessGrants.role == VaAccessRoles.coder))
        coder.grant_status = VaStatuses.deactive
        db.session.commit()
        coder.grant_status = VaStatuses.active  # reactivating an allowed grant
        db.session.commit()
        coder.role = VaAccessRoles.data_manager
        with self.assertRaises(PublicDemoGrantRefused):
            db.session.flush()
        db.session.rollback()
        # Every other account is untouched by the guard.
        db.session.add(VaUserAccessGrants(
            user_id=self.base_coder_user.user_id, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project, project_id=PROJECT, grant_status=VaStatuses.active))
        db.session.flush()

    def test_admin_grant_route_refuses_with_403(self):
        user = self._account("demo.route")
        self._login(self.base_admin_id)
        response = self.client.post(
            "/admin/api/access-grants",
            json={"user_id": str(user.user_id), "role": "data_manager", "scope_type": "project",
                  "project_id": PROJECT},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 403, response.get_json())
        self.assertEqual(response.get_json()["code"], "forbidden")
        roles = set(db.session.scalars(sa.select(VaUserAccessGrants.role).where(
            VaUserAccessGrants.user_id == user.user_id)))
        self.assertEqual(roles, set(demo.DEMO_ROLES))


class VirtualGrantTests(PublicDemoBase):
    def test_demo_training_grants_skip_public_demo_accounts(self):
        user = self._account("demo.virtual")
        # Any active demo-training project with an active form: this one will do.
        project = db.session.get(VaProjectMaster, PROJECT)
        project.demo_training_enabled = True
        db.session.commit()

        def virtual_projects(account):
            return {g.project_id for g in resolve_grants(account).grants if g.virtual}

        self.assertIn(PROJECT, virtual_projects(self.base_coder_user))
        self.assertNotIn(PROJECT, virtual_projects(user))


class IsolationTests(PublicDemoBase):
    def setUp(self):
        super().setUp()
        self.alice = self._account("demo.alice")
        self.bob = self._account("demo.bob")
        self._case(self.alice, "pub-alice")
        self._case(self.bob, "pub-bob")

    def _sids(self, predicate):
        return set(db.session.scalars(sa.select(VaSubmissions.va_sid).where(
            VaSubmissions.va_sid.in_(["pub-alice", "pub-bob"]), predicate)))

    def test_view_list_and_attachments(self):
        for action in (Action.VIEW, Action.CODE, Action.REVIEW):
            with self.subTest(action=action.value):
                self.assertTrue(can(self.alice, action, "pub-alice"))
                self.assertFalse(can(self.alice, action, "pub-bob"))
                self.assertEqual(self._sids(scope_filter(self.alice, action)), {"pub-alice"})
        self.assertEqual(self._sids(lens_filter(self.alice, Lens.VIEW_CODER)), {"pub-alice"})
        self.assertTrue(reaches(self.alice, Lens.VIEW_REVIEWER, "pub-alice"))
        self.assertFalse(reaches(self.alice, Lens.VIEW_REVIEWER, "pub-bob"))
        self.assertTrue(can_access_submission_attachment(
            self.alice, va_form_id=self.form_id, va_sid="pub-alice"))
        self.assertFalse(can_access_submission_attachment(
            self.alice, va_form_id=self.form_id, va_sid="pub-bob"))
        # Another (non-demo) coder of the project still sees both.
        db.session.add(VaUserAccessGrants(
            user_id=self.base_coder_user.user_id, role=VaAccessRoles.coder,
            scope_type=VaAccessScopeTypes.project, project_id=PROJECT, grant_status=VaStatuses.active))
        db.session.commit()
        self.assertEqual(self._sids(scope_filter(self.base_coder_user, Action.VIEW)),
                         {"pub-alice", "pub-bob"})

    def test_allocation_pick_list_and_own_case(self):
        picks = {row["va_sid"] for row in get_pick_available_forms(self.alice, [self.form_id])}
        self.assertEqual(picks & {"pub-alice", "pub-bob"}, {"pub-alice"})
        with self.assertRaises(AllocationError):
            allocate_pick_form(self.alice, "pub-bob")
        with self.assertRaises(AllocationError):
            allocate_own_case(self.alice, "pub-bob")
        self.assertEqual(allocate_own_case(self.alice, "pub-alice").va_sid, "pub-alice")

    def test_random_allocation_draws_only_the_own_case(self):
        project = db.session.get(VaProjectMaster, PROJECT)
        project.coding_intake_mode = "random_form_allocation"
        db.session.commit()
        # With her own case out of the pool, Bob's ready case is still never drawn.
        db.session.execute(sa.update(VaSubmissionWorkflow).where(
            VaSubmissionWorkflow.va_sid == "pub-alice").values(workflow_state="smartva_pending"))
        db.session.commit()
        with self.assertRaises(AllocationError):
            allocate_random_form(self.alice, PROJECT)
        db.session.execute(sa.update(VaSubmissionWorkflow).where(
            VaSubmissionWorkflow.va_sid == "pub-alice").values(workflow_state="ready_for_coding"))
        db.session.commit()
        self.assertEqual(allocate_random_form(self.alice, PROJECT).va_sid, "pub-alice")

    def test_reviewer_queue_and_start(self):
        for sid in ("pub-alice", "pub-bob"):
            db.session.execute(sa.update(VaSubmissionWorkflow).where(
                VaSubmissionWorkflow.va_sid == sid).values(workflow_state="reviewer_eligible"))
        db.session.commit()
        rows, _ = reviewer_dashboard_service.list_available(self.alice, limit=50, offset=0)
        self.assertEqual({r["va_sid"] for r in rows} & {"pub-alice", "pub-bob"}, {"pub-alice"})
        with self.assertRaises(ReviewerCodingError) as ctx:
            start_reviewer_coding(self.bob, "pub-alice")
        # 404, as for an unknown case: a demo user cannot probe for another's case.
        self.assertEqual(ctx.exception.status_code, 404)

    def test_another_users_death_is_not_found(self):
        fields = {"deceased_name": "Test Person", "deceased_sex": "female", "age_years": 60,
                  "date_of_death": (date.today() - timedelta(days=5)).isoformat()}
        own = intake.register_death(self.alice, project_id=PROJECT, site_id=self.site_id, **fields)
        other = intake.register_death(self.bob, project_id=PROJECT, site_id=self.site_id, **fields)
        db.session.commit()
        self.assertEqual(own.org_unit_id, self.unit_id)  # M4: the demo unit by default
        self.assertEqual(intake.get_death(self.alice, own.death_id), own)
        with self.assertRaises(WebIntakeError) as ctx:
            intake.start_draft(self.alice, project_id=PROJECT, site_id=self.site_id,
                               death_id=other.death_id)
        self.assertEqual(ctx.exception.status_code, 404)
        listed = {d.death_id for d in intake.list_deaths(self.alice, project_id=PROJECT,
                                                         site_id=self.site_id)}
        self.assertIn(own.death_id, listed)
        self.assertNotIn(other.death_id, listed)


class LimitTests(PublicDemoBase):
    def setUp(self):
        super().setUp()
        self.user = self._account("demo.limits")

    def test_open_drafts(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_OPEN_DRAFTS=1):
            first = intake.start_draft(self.user, project_id=PROJECT, site_id=self.site_id)
            self.assertEqual(first.org_unit_id, self.unit_id)  # M4 default unit
            with self.assertRaises(WebIntakeError) as ctx:
                intake.start_draft(self.user, project_id=PROJECT, site_id=self.site_id)
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (429, demo.LIMIT_CODE))

    def test_submissions_per_day_and_total(self):
        draft = intake.start_draft(self.user, project_id=PROJECT, site_id=self.site_id)
        self._case(self.user, "pub-limit-1")
        completion = {"data": {}}
        for config in ({"PUBLIC_DEMO_SUBMISSIONS_PER_DAY": 1},
                       {"PUBLIC_DEMO_SUBMISSIONS_TOTAL": 1}):
            with self.subTest(config=config), mock.patch.dict(self.app.config, config):
                with self.assertRaises(WebIntakeError) as ctx:
                    intake.submit_draft(draft, self.user, completion=completion)
                self.assertEqual(ctx.exception.status_code, 429)
        # A day-old submission counts toward the total only.
        db.session.execute(sa.update(VaWebIntakeDraft).where(
            VaWebIntakeDraft.va_sid == "pub-limit-1").values(
            submitted_at=datetime.now(UTC) - timedelta(days=2)))
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_SUBMISSIONS_PER_DAY=1):
            demo.check_new_submission(self.user, PROJECT)
        self.assertEqual(draft.status, "draft")

    def test_attachment_size_and_count(self):
        from app.services import web_intake_attachment_service as uploads

        draft = intake.start_draft(self.user, project_id=PROJECT, site_id=self.site_id)
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ATTACHMENT_MAX_BYTES=1024):
            with self.assertRaises(WebIntakeError) as ctx:
                uploads.store_upload(draft, uuid.uuid4(), io.BytesIO(b"x" * 2048), 2048)
        self.assertEqual(ctx.exception.status_code, 413)
        db.session.add(VaWebIntakeAttachment(
            draft_id=draft.draft_id, client_attachment_id=uuid.uuid4(), filename="a.png",
            storage_name=uuid.uuid4().hex, store_state="local", mime_type="image/png", size_bytes=10,
            sha256="0" * 64,
            created_at=datetime.now(UTC)))
        db.session.flush()
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ATTACHMENTS_PER_DRAFT=1):
            with self.assertRaises(WebIntakeError) as ctx:
                uploads.store_upload(draft, uuid.uuid4(), io.BytesIO(b"x" * 10), 10)
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (422, "attachment_limit"))

    def test_other_accounts_have_no_demo_limits(self):
        self.assertIsNone(demo.attachment_limits(self.BASE_PROJECT_ID))
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_SUBMISSIONS_TOTAL=0):
            demo.check_new_submission(self.base_coder_user, PROJECT)


class SetupTests(PublicDemoBase):
    def test_setup_built_the_project_and_is_idempotent(self):
        self.assertEqual(self.setup_result, {"project": True, "unit": True, "notices_seeded": 2,
                                             "notices_approved": 2, "settings_reset": []})
        project = db.session.get(VaProjectMaster, PROJECT)
        self.assertEqual(
            (project.project_structure_mode, project.web_intake_mode, project.self_coding_enabled,
             project.icd_classification, project.cod_entry_mode, project.masked_cod_required,
             project.narrative_qa_enabled, project.social_autopsy_enabled,
             project.web_intake_narration_languages, project.recode_window_minutes,
             project.demo_training_enabled, project.web_intake_medical_records_enabled,
             project.web_intake_death_summary_enabled),
            ("organization", "both", True, "icd11", "doris", False, False, False,
             ["english", "hindi"], 5, False, True, True),
        )
        self.assertIsNotNone(self.unit_id)
        self.assertTrue(db.session.get(MasProjectConsentSettings, PROJECT).consent_required)
        notices = db.session.scalars(sa.select(MasConsentNoticeVersion).where(
            MasConsentNoticeVersion.project_id == PROJECT)).all()
        self.assertEqual(sorted(n.language for n in notices), ["en", "hi"])
        self.assertTrue(all(n.approved_at is not None for n in notices))

        project.recode_window_minutes = 60
        db.session.commit()
        again = demo.setup_public_demo_project(self.base_admin_user)
        self.assertEqual(again, {"project": False, "unit": False, "notices_seeded": 0,
                                 "notices_approved": 0, "settings_reset": ["recode_window_minutes"]})
        self.assertEqual(db.session.get(VaProjectMaster, PROJECT).recode_window_minutes, 5)

    def test_setup_refuses_flag_off_and_non_admin(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=False):
            with self.assertRaises(demo.PublicDemoError) as off:
                demo.setup_public_demo_project(self.base_admin_user)
        self.assertEqual(off.exception.code, "not_enabled")
        with self.assertRaises(demo.PublicDemoError) as ctx:
            demo.setup_public_demo_project(self.base_coder_user)
        self.assertEqual(ctx.exception.code, "admin_required")

    def test_cli_refuses_with_the_flag_off(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=False):
            result = self.app.test_cli_runner().invoke(
                args=["public-demo", "setup", "--by", self.base_admin_user.email])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("not_enabled", result.output)


class ReservedUsernameTests(PublicDemoBase):
    def test_reserved_names_and_prefixes_are_refused(self):
        for name in sorted(accounts.RESERVED_USERNAMES) + [
            "Admin", "admin2", "administrator", "digitva.team", "digitva-support", "adminbob",
            "support.team", "supporter", "root_user", "security-desk", "who.am.i", "whoami",
            "official1", "official-wm",
        ]:
            with self.subTest(name=name):
                with self.assertRaises(accounts.UserAccountError) as ctx:
                    accounts.clean_username(name)
                self.assertEqual(str(ctx.exception), accounts.USERNAME_RESERVED_MESSAGE)

    def test_separators_are_ignored_when_comparing(self):
        for name in ("a.d.m.i.n", "a_d-min", "d-i-g-i-t-v-a", "ro.ot", "s.u.p.p.o.r.t", "d.e.m.o", "n-u-l-l",
                     "mod.erator"):
            with self.subTest(name=name):
                with self.assertRaises(accounts.UserAccountError) as ctx:
                    accounts.clean_username(name)
                self.assertEqual(str(ctx.exception), accounts.USERNAME_RESERVED_MESSAGE)
        # Near misses stay open: not an exact name and not a prefix.
        for name in ("demo.web", "demo1", "the.admin", "my-root", "owner2", "whale"):
            with self.subTest(name=name):
                self.assertEqual(accounts.clean_username(name), name)

    def test_sign_up_refuses_a_reserved_name_on_both_paths(self):
        web = self._post_signup(username="support")
        self.assertEqual(web.status_code, 200)
        self.assertIn(accounts.USERNAME_RESERVED_MESSAGE, web.get_data(as_text=True))
        api = self._api_signup("admin")
        self.assertEqual((api.status_code, api.get_json()["code"]), (400, "invalid_username"))
        self.assertIsNone(self._user("support"))
        self.assertIsNone(self._user("admin"))


class SignUpQuotaTests(PublicDemoBase):
    def test_quota_hit_is_atomic_and_spends_every_window(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_SIGNUP_RATE_LIMIT="3 per hour;10 per day"):
            hits = [demo.hit_signup_quota("203.0.113.9") for _ in range(4)]
            other_ip = demo.hit_signup_quota("203.0.113.10")
        self.assertEqual(hits, [True, True, True, False])
        self.assertTrue(other_ip)

    def test_a_spent_quota_refuses_with_the_limiters_429_and_creates_nothing(self):
        with mock.patch.object(demo, "hit_signup_quota", return_value=False) as hit:
            web = self._post_signup(username="demo.quotaweb")
            api = self._api_signup("demo.quotaapi")
        self.assertEqual(hit.call_count, 2)
        # The app's 429 handler answers an HTML page with a redirect back.
        self.assertEqual(web.status_code, 302)
        self.assertNotEqual(urlparse(web.headers.get("Location", "")).path, "/app/")
        self.assertEqual((api.status_code, api.get_json()["code"]), (429, "rate_limited"))
        self.assertIsNone(self._user("demo.quotaweb"))
        self.assertIsNone(self._user("demo.quotaapi"))
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)


class AccountLockTests(PublicDemoBase):
    """Limit checks take the per-account lock, so parallel requests serialise
    (a concurrency test would be flaky; the lock is what is asserted)."""

    @staticmethod
    def _advisory_locks():
        return db.session.scalar(sa.text(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"))

    def test_each_limit_check_locks_a_demo_account_only(self):
        # A fresh account per check: the harness keeps one outer transaction,
        # so a lock taken once stays taken.
        for number, check in enumerate(
            (demo.check_new_draft, demo.check_new_submission, demo.check_new_registration)
        ):
            with self.subTest(check=check.__name__):
                user = self._account(f"demo.locks{number}")
                held = self._advisory_locks()  # the test harness may hold its own
                check(self.base_coder_user, PROJECT)  # not a demo account: no lock
                check(user, self.BASE_PROJECT_ID)  # not the demo project: no lock
                self.assertEqual(self._advisory_locks(), held)
                check(user, PROJECT)
                self.assertEqual(self._advisory_locks(), held + 1)


class RegistrationLimitTests(PublicDemoBase):
    FIELDS = {"deceased_name": "Test Person", "deceased_sex": "female", "age_years": 60,
              "date_of_death": (date.today() - timedelta(days=5)).isoformat()}

    def _register(self, user):
        return intake.register_death(user, project_id=PROJECT, site_id=self.site_id, **self.FIELDS)

    def test_per_day_and_total(self):
        user = self._account("demo.register")
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_REGISTRATIONS_PER_DAY=1):
            self._register(user)
            db.session.commit()
            with self.assertRaises(WebIntakeError) as ctx:
                self._register(user)
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (429, demo.LIMIT_CODE))
        db.session.rollback()
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_REGISTRATIONS_TOTAL=1):
            with self.assertRaises(WebIntakeError) as ctx:
                self._register(user)
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (429, demo.LIMIT_CODE))
        db.session.rollback()
        # A day-old registration counts toward the total only; the defaults (5 and 25) allow more.
        db.session.execute(sa.update(VaDeathRegister).where(
            VaDeathRegister.registered_by == user.user_id).values(
            created_at=datetime.now(UTC) - timedelta(days=2)))
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_REGISTRATIONS_PER_DAY=1):
            self._register(user)
        db.session.commit()

    def test_other_users_and_projects_are_not_limited(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_REGISTRATIONS_TOTAL=0):
            demo.check_new_registration(self.base_coder_user, PROJECT)
            demo.check_new_registration(self._account("demo.otherproj"), self.BASE_PROJECT_ID)

    def test_a_number_on_another_demo_users_case_is_not_confirmed(self):
        db.session.add(MasDeathIdentifierType(
            project_id=PROJECT, code="crs", label="CRS number", sort_order=1,
            min_length=6, max_length=12, char_type="digits"))
        db.session.commit()
        value = "9" + uuid.uuid4().int.__str__()[:7]
        alice, bob = self._account("demo.dupalice"), self._account("demo.dupbob")
        self.assertEqual(self._warnings(alice, value), [])
        self.assertEqual(self._warnings(bob, value), [])
        # Her own earlier case still warns her.
        self.assertEqual([w["code"] for w in self._warnings(alice, value)], ["identifier_in_use"])

    def _warnings(self, user, value):
        warnings = []
        intake.register_death(user, project_id=PROJECT, site_id=self.site_id,
                              identifiers={"crs": value}, warnings=warnings, **self.FIELDS)
        db.session.commit()
        return warnings


class SweepScheduleTests(BaseTestCase):
    """The beat tables only exist in the migrated dev database, so the seeding
    runs against a stand-in connection that remembers its writes."""

    def _run(self, configured, existing):
        from contextlib import contextmanager

        from app.tasks import sync_tasks

        writes = []

        class Conn:
            def execute(self, statement, params=None):
                sql = str(statement)
                result = mock.Mock()
                if "FROM public.celery_periodictask t" in sql:
                    result.first.return_value = existing
                elif "SELECT id FROM public.celery_intervalschedule" in sql:
                    result.scalar.return_value = 7
                else:
                    writes.append((sql.split()[0], params))
                return result

        @contextmanager
        def begin():
            yield Conn()

        with mock.patch("app.db", mock.Mock(engine=mock.Mock(begin=begin))), \
                mock.patch.dict(self.app.config, CODING_SWEEP_INTERVAL_MINUTES=configured):
            sync_tasks.ensure_coding_timeout_cleanup_scheduled()
        return writes

    @staticmethod
    def _row(every, period):
        return mock.Mock(id=3, every=every, period=period)

    def test_default_seeds_hourly_when_missing_and_never_repoints(self):
        inserted = self._run(None, None)
        self.assertEqual(inserted[0][0], "INSERT")
        self.assertEqual(inserted[0][1]["name"], "Release stale coding allocations — every 1 hour")
        # An existing row, whatever its interval, is left alone.
        self.assertEqual(self._run(None, self._row(5, "minutes")), [])
        self.assertEqual(self._run(None, self._row(1, "hours")), [])

    def test_configured_interval_repoints_and_renames_an_existing_row(self):
        writes = self._run(5, self._row(1, "hours"))
        update = next(params for verb, params in writes if verb == "UPDATE")
        self.assertEqual((update["schedule_id"], update["id"]), (7, 3))
        self.assertEqual(update["name"], "Release stale coding allocations — every 5 minutes")
        self.assertEqual(self._run(5, self._row(5, "minutes")), [])  # already there: no-op
        back = next(params for verb, params in self._run(60, self._row(5, "minutes")) if verb == "UPDATE")
        self.assertEqual(back["name"], "Release stale coding allocations — every 1 hour")

    def test_configured_interval_names_a_new_row_from_the_interval(self):
        inserted = self._run(1, None)
        self.assertEqual(inserted[0][1]["name"], "Release stale coding allocations — every 1 minute")


class ExposureRefusalTests(PublicDemoBase):
    """Other demo users' identities and project-wide aggregates stay out of reach."""

    def setUp(self):
        super().setUp()
        self.alice = self._account("demo.exalice")
        self.bob = self._account("demo.exbob")

    def test_people_roles_json_and_csv_are_not_found_for_a_demo_user(self):
        self._login(str(self.alice.user_id))
        for suffix in ("", ".csv"):
            with self.subTest(suffix=suffix):
                response = self.client.get(f"/api/v1/projects/{PROJECT}/people-roles{suffix}")
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(b"demo.exbob", response.data)
        self._login(self.base_admin_id)
        self.assertEqual(self.client.get(f"/api/v1/projects/{PROJECT}/people-roles").status_code, 200)

    def test_area_dashboard_is_not_found_for_a_demo_user(self):
        from app.services import area_dashboard_service

        self._login(str(self.alice.user_id))
        for path in (f"/api/v1/area/staff?project={PROJECT}", f"/api/v1/area/summary?project={PROJECT}",
                     f"/api/v1/area/summary?project={PROJECT}&format=csv"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/area/projects").get_json()["projects"], [])
        self.assertEqual(self.client.get("/api/v1/me/kpis").get_json()["projects"], [])
        self.assertIsNone(area_dashboard_service.resolve_area_scope(self.alice, PROJECT))
        # The same grants on an ordinary account do reach the area.
        db.session.add(VaUserAccessGrants(
            user_id=self.base_coder_user.user_id, role=VaAccessRoles.coder,
            scope_type=VaAccessScopeTypes.project, project_id=PROJECT, grant_status=VaStatuses.active))
        db.session.commit()
        self.assertIsNotNone(area_dashboard_service.resolve_area_scope(self.base_coder_user, PROJECT))

    def test_translation_suggestions_are_not_open_to_a_demo_user(self):
        from app.services import instrument_translation_suggestion_service as suggestions

        with self.assertRaises(suggestions.SuggestionError) as ctx:
            suggestions.suggest(self.alice, PROJECT, "hi", {})
        self.assertEqual(ctx.exception.status, 403)

    def test_unit_people_is_not_found_for_a_demo_user(self):
        self._login(str(self.alice.user_id))
        response = self.client.get(f"/api/v1/organization/units/{self.unit_id}/people")
        self.assertEqual(response.status_code, 404)
        for project in self.client.get("/api/v1/organization/me").get_json()["projects"]:
            self.assertTrue(all(not unit["people"] for unit in project["above"] + project["my_level"]))


class CaseRouteIsolationTests(PublicDemoBase):
    def setUp(self):
        super().setUp()
        self.alice = self._account("demo.rtalice")
        self.bob = self._account("demo.rtbob")
        self._case(self.alice, "pub-rt-alice")
        self._case(self.bob, "pub-rt-bob")

    def test_workspace_of_another_demo_users_case_is_refused(self):
        self._login(str(self.alice.user_id))
        own = self.client.get("/api/v1/va/pub-rt-alice/workspace?mode=view")
        self.assertEqual(own.status_code, 200, own.get_data(as_text=True)[:300])
        other = self.client.get("/api/v1/va/pub-rt-bob/workspace?mode=view")
        self.assertIn(other.status_code, (403, 404))
        self.assertNotIn(b"pub-rt-bob", other.data.replace(b"Submission not found", b""))

    def test_attachment_of_another_demo_users_case_is_refused(self):
        from flask import Response

        names = {}
        for sid in ("pub-rt-alice", "pub-rt-bob"):
            names[sid] = uuid.uuid4().hex + ".png"
            db.session.add(VaSubmissionAttachments(
                va_sid=sid, filename=f"{sid}.png", local_path=f"{sid}.png", mime_type="image/png",
                exists_on_odk=True, storage_name=names[sid]))
        db.session.commit()
        self._login(str(self.alice.user_id))
        with mock.patch("app.routes.api.attachments.attachment_service.deliver",
                        return_value=Response(b"bytes", mimetype="image/png")):
            own = self.client.get(f"/api/v1/attachments/{names['pub-rt-alice']}")
            other = self.client.get(f"/api/v1/attachments/{names['pub-rt-bob']}")
        self.assertEqual((own.status_code, own.data), (200, b"bytes"))
        self.assertEqual(other.status_code, 403)


class DemoDeviceTests(PublicDemoBase):
    """Sign-in on an enrolled device with a username, and the device upload."""

    def setUp(self):
        super().setUp()
        from tests.routes import test_device_api as device_tests

        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self.user = self._account("demo.device")
        from app.services import device_auth_service as devices

        _row, code = devices.create_enrolment_code(PROJECT, actor=self.base_admin_user)
        device, secret = devices.enrol_device(code, device_name="Phone", platform="android", app_version="1")
        db.session.commit()
        self.device = {"device_id": str(device.device_id), "device_secret": secret}

    def _sign_in(self, username="demo.device", password=PASSWORD):
        return self.client.post("/api/v1/auth/sessions", json={
            **self.device, "email": username, "password": password})

    def test_has_device_access(self):
        from app.services.device_auth_service import has_device_access

        self.assertTrue(has_device_access(self.user))

    def test_username_signs_in_with_the_flag_on_and_not_off(self):
        response = self._sign_in("Demo.Device")
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertTrue(response.get_json()["access"]["account"]["device_access"])
        self.assertEqual(self._sign_in(password="wrong-demo-password").status_code, 401)
        limiter.reset()
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=False):
            self.assertEqual(self._sign_in().status_code, 401)

    def test_device_upload_over_the_submission_limit_is_429_demo_limit(self):
        import hashlib
        import json

        tokens = self._sign_in().get_json()
        answers = json.dumps({"Id10013": "yes", "Id10017": "Bina", "Id10018": "Sahu", "Id10019": "female",
                              "Id10023": (date.today() - timedelta(days=5)).isoformat(),
                              "finalAgeInYears": "71", "narr_language": "english"}, separators=(",", ":"))
        body = {
            "client_draft_id": str(uuid.uuid4()), "project_id": PROJECT, "site_id": self.site_id,
            "draft": {"startedAt": datetime.now(UTC).isoformat()},
            "completion": {"valid": True, "issues": []}, "answers_json": answers,
            "answers_sha256": hashlib.sha256(answers.encode()).hexdigest(),
        }
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_SUBMISSIONS_PER_DAY=0):
            response = self.client.post("/api/v1/intake/submissions", json=body, headers=headers)
        self.assertEqual((response.status_code, response.get_json()["code"]), (429, demo.LIMIT_CODE))


class SignInCodeRefusalTests(PublicDemoBase):
    def test_admin_and_data_manager_cannot_issue_a_code_for_a_demo_account(self):
        user = self._account("demo.nocode")
        manager = self._get_or_make_user("demo.nocode.dm@test.local", "Manager123")
        db.session.add(VaUserAccessGrants(
            user_id=manager.user_id, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project, project_id=PROJECT, grant_status=VaStatuses.active))
        db.session.commit()
        for actor, path in ((self.base_admin_id, "/admin"), (str(manager.user_id), "/data-management")):
            with self.subTest(path=path):
                self._login(actor)
                response = self.client.post(f"{path}/api/users/{user.user_id}/sign-in-code",
                                            headers=self._csrf_headers())
                self.assertEqual(response.status_code, 400, response.get_json())
        self.assertNotIn("sign_in_code", response.get_json())


class IcdRateLimitTests(PublicDemoBase):
    def test_demo_users_share_one_icd_bucket_and_others_are_exempt(self):
        alice = self._account("demo.icd")
        self._case(alice, "pub-icd-1")
        self._login(str(alice.user_id))
        url = "/api/v1/icd11/coding-search/pub-icd-1?q=heart"
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ICD_RATE_LIMIT="2 per hour"):
            statuses = [self.client.get(url).status_code for _ in range(3)]
            doris = self.client.post("/api/v1/doris-clinical/terms/pub-icd-1", json={}, headers=self._csrf_headers())
            self._login(self.base_admin_id)
            admin = [self.client.get(url).status_code for _ in range(3)]
        self.assertNotIn(429, statuses[:2])
        self.assertEqual(statuses[2], 429)
        self.assertEqual(doris.status_code, 429)  # the same bucket
        self.assertNotIn(429, admin)


class ConfiguredLimitDefaultsTests(BaseTestCase):
    """The shipped defaults (policy section 8), read from the class so a
    developer's environment cannot change what is asserted."""

    def test_defaults(self):
        from config import Config

        self.assertEqual(Config.PUBLIC_DEMO_SUBMISSIONS_PER_DAY, 5)
        self.assertEqual(Config.PUBLIC_DEMO_SUBMISSIONS_TOTAL, 10)
        self.assertEqual(Config.PUBLIC_DEMO_SIGNUP_RATE_LIMIT, "30 per hour;200 per day")
        self.assertEqual(Config.PUBLIC_DEMO_SIGNUP_GLOBAL_RATE_LIMIT, "100 per hour")
        self.assertEqual(
            (Config.PUBLIC_DEMO_OPEN_DRAFTS, Config.PUBLIC_DEMO_DRAFTS_PER_DAY, Config.PUBLIC_DEMO_DRAFTS_TOTAL),
            (3, 10, 30),
        )
        self.assertEqual(Config.PUBLIC_DEMO_ICD_RATE_LIMIT, "300 per hour")
        self.assertEqual(Config.PUBLIC_DEMO_ICD_GLOBAL_RATE_LIMIT, "2000 per hour")
        self.assertEqual(Config.PUBLIC_DEMO_MAX_ACCOUNTS, 500)
        self.assertFalse(Config.PUBLIC_DEMO_PURGE_ENABLED)  # on only once the nightly backup is verified
        self.assertEqual((Config.PUBLIC_DEMO_PURGE_IDLE_DAYS, Config.PUBLIC_DEMO_EVICT_IDLE_DAYS), (30, 7))


class NewLimitTests(PublicDemoBase):
    def setUp(self):
        super().setUp()
        self.user = self._account("demo.newlimits")

    def test_submissions_total_default_is_ten(self):
        # The test config carries the shipped default (10); nine submissions
        # (aged past the daily window) still leave room, the tenth does not.
        self.assertEqual(self.app.config["PUBLIC_DEMO_SUBMISSIONS_TOTAL"], 10)
        for i in range(9):
            self._case(self.user, f"pub-total-{i}")
        db.session.execute(sa.update(VaWebIntakeDraft).where(VaWebIntakeDraft.user_id == self.user.user_id).values(
            submitted_at=datetime.now(UTC) - timedelta(days=2)))
        demo.check_new_submission(self.user, PROJECT)
        self._case(self.user, "pub-total-9")
        db.session.execute(sa.update(VaWebIntakeDraft).where(VaWebIntakeDraft.user_id == self.user.user_id).values(
            submitted_at=datetime.now(UTC) - timedelta(days=2)))
        with self.assertRaises(WebIntakeError) as ctx:
            demo.check_new_submission(self.user, PROJECT)
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (429, demo.LIMIT_CODE))
        self.assertIn("10 submissions", str(ctx.exception))

    def _start_and_discard(self):
        draft = intake.start_draft(self.user, project_id=PROJECT, site_id=self.site_id)
        intake.discard_draft(draft, self.user)
        db.session.flush()
        return draft

    def test_drafts_per_day_count_discarded_drafts(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_DRAFTS_PER_DAY=2):
            self._start_and_discard()
            self._start_and_discard()
            with self.assertRaises(WebIntakeError) as ctx:
                intake.start_draft(self.user, project_id=PROJECT, site_id=self.site_id)
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (429, demo.LIMIT_CODE))
        # A day later the daily window is clear again (the total still has room).
        db.session.execute(sa.update(VaWebIntakeDraft).where(VaWebIntakeDraft.user_id == self.user.user_id).values(
            created_at=datetime.now(UTC) - timedelta(days=2)))
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_DRAFTS_PER_DAY=2):
            demo.check_new_draft(self.user, PROJECT)

    def test_drafts_total_counts_every_status(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_DRAFTS_TOTAL=2):
            self._start_and_discard()
            self._start_and_discard()
            db.session.execute(sa.update(VaWebIntakeDraft).where(
                VaWebIntakeDraft.user_id == self.user.user_id).values(
                created_at=datetime.now(UTC) - timedelta(days=2)))
            with self.assertRaises(WebIntakeError) as ctx:
                demo.check_new_draft(self.user, PROJECT)
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (429, demo.LIMIT_CODE))
        self.assertIn("2 interviews", str(ctx.exception))

    def test_draft_limits_apply_only_to_demo_accounts(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_DRAFTS_TOTAL=0, PUBLIC_DEMO_DRAFTS_PER_DAY=0):
            demo.check_new_draft(self.base_coder_user, PROJECT)


class SignUpLimitTests(PublicDemoBase):
    def test_client_key_is_the_ipv4_address_or_the_ipv6_slash_64(self):
        key = demo.signup_client_key
        self.assertEqual(key("203.0.113.9"), "203.0.113.9")
        self.assertEqual(key("2001:db8:1:2:aaaa:bbbb:cccc:dddd"), "2001:db8:1:2::/64")
        self.assertEqual(key("2001:db8:1:2::1"), key("2001:db8:1:2:ffff::9"))
        self.assertNotEqual(key("2001:db8:1:2::1"), key("2001:db8:1:3::1"))
        self.assertEqual(key("::ffff:203.0.113.9"), "203.0.113.9")  # IPv4-mapped
        self.assertEqual(key("not an address"), "not an address")
        self.assertEqual(key(None), "")

    def test_route_key_func_reads_the_request_address(self):
        with self.app.test_request_context(environ_base={"REMOTE_ADDR": "2001:db8:5:6::77"}):
            self.assertEqual(demo.signup_remote_key(), "2001:db8:5:6::/64")
        with self.app.test_request_context(environ_base={"REMOTE_ADDR": "198.51.100.4"}):
            self.assertEqual(demo.signup_remote_key(), "198.51.100.4")

    def test_route_key_func_is_never_empty(self):
        # An empty key makes flask-limiter skip the limit.
        for remote in (None, ""):
            with self.subTest(remote=remote), self.app.test_request_context(
                environ_base={"REMOTE_ADDR": remote}
            ):
                self.assertTrue(demo.signup_remote_key())
                self.assertEqual(demo.signup_remote_key(), demo.signup_client_key(get_remote_address()))

    def test_ipv6_addresses_in_one_prefix_share_a_quota(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_SIGNUP_RATE_LIMIT="1 per hour",
                             PUBLIC_DEMO_SIGNUP_GLOBAL_RATE_LIMIT="100 per hour"):
            first = demo.hit_signup_quota("2001:db8:7:8::1")
            same_prefix = demo.hit_signup_quota("2001:db8:7:8:dead:beef::2")
            other_prefix = demo.hit_signup_quota("2001:db8:7:9::1")
            mapped_first = demo.hit_signup_quota("::ffff:192.0.2.55")
            mapped_again = demo.hit_signup_quota("192.0.2.55")
        self.assertEqual([first, same_prefix, other_prefix, mapped_first, mapped_again],
                         [True, False, True, True, False])

    def test_default_per_client_windows_are_thirty_an_hour_and_two_hundred_a_day(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_SIGNUP_RATE_LIMIT="30 per hour;200 per day",
                             PUBLIC_DEMO_SIGNUP_GLOBAL_RATE_LIMIT="1000 per hour"):
            hits = [demo.hit_signup_quota("203.0.113.77") for _ in range(31)]
        self.assertEqual(hits, [True] * 30 + [False])

    def test_demo_wide_quota_is_shared_across_addresses(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_SIGNUP_RATE_LIMIT="5 per hour",
                             PUBLIC_DEMO_SIGNUP_GLOBAL_RATE_LIMIT="2 per hour"):
            hits = [demo.hit_signup_quota(ip) for ip in ("203.0.113.1", "203.0.113.2", "203.0.113.3")]
        self.assertEqual(hits, [True, True, False])

    def test_a_refused_client_does_not_spend_the_demo_wide_quota(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_SIGNUP_RATE_LIMIT="1 per hour",
                             PUBLIC_DEMO_SIGNUP_GLOBAL_RATE_LIMIT="2 per hour"):
            hits = [demo.hit_signup_quota(ip) for ip in ("203.0.113.1", "203.0.113.1", "203.0.113.1", "203.0.113.2")]
        self.assertEqual(hits, [True, False, False, True])

    def test_demo_wide_quota_refuses_the_sign_up_with_429_and_creates_nothing(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_SIGNUP_RATE_LIMIT="50 per hour",
                             PUBLIC_DEMO_SIGNUP_GLOBAL_RATE_LIMIT="1 per hour"):
            first = self._api_signup("demo.wide1")
            second = self._api_signup("demo.wide2")
            web = self._post_signup(username="demo.wide3")
        self.assertEqual((first.status_code, second.status_code), (201, 429))
        self.assertEqual(second.get_json()["code"], "rate_limited")
        self.assertNotEqual(urlparse(web.headers.get("Location", "")).path, "/app/")
        self.assertIsNotNone(self._user("demo.wide1"))
        self.assertIsNone(self._user("demo.wide2"))
        self.assertIsNone(self._user("demo.wide3"))

    def test_quota_uses_the_limiters_key_prefix(self):
        stored = []

        class Strategy:
            def hit(self, item, *identifiers):
                stored.append(identifiers)
                return True

        with mock.patch.object(limiter, "_limiter", Strategy(), create=True), \
                mock.patch.dict(self.app.config, RATELIMIT_KEY_PREFIX="demo"):
            self.assertTrue(demo.hit_signup_quota("2001:db8:1:2::9"))
        self.assertIn(("demo", "public_demo_signup", "2001:db8:1:2::/64"), stored)
        self.assertIn(("demo", "public_demo_signup_all"), stored)


class JsonSignUpProofOfWorkTests(PublicDemoBase):
    def setUp(self):
        super().setUp()
        # The single-use marker lives in the shared dev Redis, where another
        # xdist worker's cache.clear() can wipe it between two posts; keep it
        # in a private in-memory cache for these tests.
        from cachelib import SimpleCache

        from app import cache

        patcher = mock.patch.object(cache, "add", SimpleCache().add)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, captcha, username="demo.pow"):
        body = {"username": username, "password": PASSWORD}
        if captcha is not None:
            body["captcha"] = captcha
        return self.client.post("/api/v1/auth/demo-signup", json=body)

    def _assert_refused(self, response, username="demo.pow"):
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()["code"], "captcha_failed")
        self.assertEqual(response.get_json()["fields"], ["captcha"])
        self.assertIsNone(self._user(username))

    def test_challenge_endpoint_returns_the_web_challenge_shape(self):
        response = self.client.get("/api/v1/auth/demo-signup/challenge")
        self.assertEqual(response.status_code, 200)
        challenge = response.get_json()
        self.assertEqual(set(challenge), {"salt", "difficulty", "expires", "signature"})
        self.assertEqual(challenge["difficulty"], self.app.config["CAPTCHA_DIFFICULTY"])
        self.assertNotEqual(challenge["salt"], self.client.get(
            "/api/v1/auth/demo-signup/challenge").get_json()["salt"])

    def test_challenge_endpoint_is_rate_limited(self):
        statuses = [self.client.get("/api/v1/auth/demo-signup/challenge").status_code for _ in range(31)]
        self.assertEqual(statuses[:30], [200] * 30)
        self.assertEqual(statuses[30], 429)

    def test_missing_captcha_is_refused(self):
        self._assert_refused(self._post(None))
        self._assert_refused(self._post({}))
        self._assert_refused(self._post("solved"))
        self._assert_refused(self._post(["x"]))

    def test_wrong_solution_is_refused(self):
        import hashlib

        challenge = self.client.get("/api/v1/auth/demo-signup/challenge").get_json()
        difficulty = challenge["difficulty"]
        number = 0
        while (int.from_bytes(hashlib.sha256(f"{challenge['salt']}{number}".encode()).digest(), "big")
               >> (256 - difficulty)) == 0:
            number += 1
        self._assert_refused(self._post({**challenge, "solution": str(number)}))
        self._assert_refused(self._post({**challenge, "solution": "abc"}))
        self._assert_refused(self._post({**challenge}))

    def test_tampered_or_expired_challenge_is_refused(self):
        solved = self._captcha()
        self._assert_refused(self._post({**solved, "difficulty": 0}))
        self._assert_refused(self._post({**solved, "signature": "0" * 64}))
        self._assert_refused(self._post({**solved, "salt": "f" * 32}))
        with mock.patch("app.services.pow_captcha_service.time.time", return_value=solved["expires"] + 1):
            self._assert_refused(self._post(solved))

    def test_a_valid_solution_signs_up_once(self):
        solved = self._captcha()
        ok = self._post(solved)
        self.assertEqual(ok.status_code, 201, ok.get_json())
        self.assertIsNotNone(self._user("demo.pow"))
        again = self._post(solved, username="demo.pow2")  # the same solution, spent
        self._assert_refused(again, "demo.pow2")

    def test_the_proof_is_checked_before_the_username_and_a_later_refusal_spends_it(self):
        solved = self._captcha()
        bad = self._post(solved, username="1bad")
        self.assertEqual((bad.status_code, bad.get_json()["code"]), (400, "invalid_username"))
        self._assert_refused(self._post(solved, username="demo.after"), "demo.after")
        self.assertEqual(self._post(self._captcha(), username="demo.after").status_code, 201)

    def test_flag_off_has_no_challenge_endpoint(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=False):
            self.assertEqual(self.client.get("/api/v1/auth/demo-signup/challenge").status_code, 404)


class DemoIcdGlobalLimitTests(PublicDemoBase):
    def test_all_demo_accounts_share_one_hourly_bucket_and_others_are_exempt(self):
        alice, bob = self._account("demo.icda"), self._account("demo.icdb")
        self._case(alice, "pub-icda")
        self._case(bob, "pub-icdb")
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ICD_RATE_LIMIT="100 per hour",
                             PUBLIC_DEMO_ICD_GLOBAL_RATE_LIMIT="3 per hour"):
            self._login(str(alice.user_id))
            first = [self.client.get("/api/v1/icd11/coding-search/pub-icda?q=heart").status_code for _ in range(2)]
            self._login(str(bob.user_id))
            # Bob is far below his own limit, but the demo-wide bucket has one call left.
            second = self.client.get("/api/v1/icd11/coding-search/pub-icdb?q=heart").status_code
            third = self.client.get("/api/v1/icd11/coding-search/pub-icdb?q=heart").status_code
            doris = self.client.post("/api/v1/doris-clinical/terms/pub-icdb", json={},
                                     headers=self._csrf_headers()).status_code
            self._login(self.base_admin_id)
            admin = [self.client.get("/api/v1/icd11/coding-search/pub-icdb?q=heart").status_code for _ in range(4)]
        self.assertNotIn(429, first)
        self.assertNotEqual(second, 429)
        self.assertEqual((third, doris), (429, 429))
        self.assertNotIn(429, admin)

    def test_the_global_bucket_is_checked_before_any_who_call(self):
        alice = self._account("demo.icdc")
        self._case(alice, "pub-icdc")
        self._login(str(alice.user_id))
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ICD_GLOBAL_RATE_LIMIT="1 per hour"), \
                mock.patch("app.routes.api.icd11.proxy_who_icd_request") as who:
            self.client.get("/api/v1/icd11/coding-search/pub-icdc?q=heart")
            calls_after_first = who.call_count
            blocked = self.client.get("/api/v1/icd11/coding-search/pub-icdc?q=heart")
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(who.call_count, calls_after_first)


class IsolationProbeTests(PublicDemoBase):
    def test_another_demo_users_case_and_an_unknown_one_look_the_same(self):
        from app.services.authz import AuthzError, require

        alice, bob = self._account("demo.probea"), self._account("demo.probeb")
        self._case(bob, "pub-probe-bob")
        for action in (Action.VIEW, Action.CODE, Action.REVIEW):
            with self.subTest(action=action):
                with self.assertRaises(AuthzError) as theirs:
                    require(alice, action, "pub-probe-bob")
                with self.assertRaises(AuthzError) as unknown:
                    require(alice, action, "pub-does-not-exist")
                self.assertEqual(theirs.exception.status_code, 404)
                self.assertEqual(
                    (theirs.exception.status_code, str(theirs.exception)),
                    (unknown.exception.status_code, str(unknown.exception)),
                )
        # Their own case is still allowed; a main-style account keeps its 403 for a case out of its scope.
        self._case(alice, "pub-probe-alice")
        self.assertTrue(can(alice, Action.VIEW, "pub-probe-alice"))


class MyOrganizationBelowTests(PublicDemoBase):
    def test_below_units_show_no_head_count_for_a_demo_account(self):
        from app.models import MasOrgUnitWorker
        from app.services import organization_service as org

        user = self._account("demo.below")
        cadre = org.create_cadre(PROJECT, cadre_code="NURSE", cadre_name="Nurse")
        db.session.add(MasOrgUnitWorker(
            project_id=PROJECT, org_unit_id=self.unit_id, cadre_id=cadre.cadre_id,
            worker_code="W1", worker_name="W One"))
        db.session.flush()

        def counts():
            below = org.my_organization(user)["projects"][0]["below"]
            return {unit["org_unit_id"]: unit["people_count"] for unit in below}

        self.assertEqual(counts(), {str(self.unit_id): 0})
        # The same query does count the worker for any other kind of account.
        user.is_public_demo = False
        self.assertEqual(counts(), {str(self.unit_id): 1})


class MainDatabaseGuardTests(BaseTestCase):
    """The real guard against a demo deployment pointed at the main database
    (the demo fixtures patch it out: the base test project makes every test
    database look like the main one)."""

    def _demo(self):
        return mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=True, PUBLIC_DEMO_PROJECT_ID="PUB01")

    def test_any_project_but_the_demos_is_seen(self):
        with self._demo():
            self.assertTrue(demo.foreign_projects_exist())
        others = db.session.scalar(sa.select(sa.func.count()).select_from(VaProjectMaster).where(
            VaProjectMaster.project_id != self.BASE_PROJECT_ID))
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_PROJECT_ID=self.BASE_PROJECT_ID):
            self.assertEqual(demo.foreign_projects_exist(), others > 0)

    def test_sign_up_and_setup_refuse_with_a_clear_error_and_write_nothing(self):
        users = db.session.scalar(sa.select(sa.func.count()).select_from(VaUsers))
        with self._demo(), self.assertLogs("app.services.public_demo_service", "ERROR") as logs:
            with self.assertRaises(demo.PublicDemoError) as signup:
                demo.create_account("demo.wrongdb", PASSWORD)
            with self.assertRaises(demo.PublicDemoError) as setup:
                demo.setup_public_demo_project(self.base_admin_user)
        for refusal in (signup.exception, setup.exception):
            self.assertEqual((refusal.code, refusal.status_code), ("wrong_database", 503))
        self.assertEqual(len(logs.records), 2)
        self.assertTrue(all("main database" in record.getMessage() for record in logs.records))
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaUsers)), users)
        self.assertIsNone(db.session.get(VaProjectMaster, "PUB01"))

    def test_the_flag_off_still_answers_not_found_first(self):
        with self.assertRaises(demo.PublicDemoError) as ctx:
            demo.create_account("demo.flagoff", PASSWORD)
        self.assertEqual(ctx.exception.code, "not_enabled")


class ImportCycleTests(BaseTestCase):
    def test_the_upload_service_loads_the_demo_service_only_when_it_stores(self):
        from app.services import web_intake_attachment_service as uploads

        # public_demo_service -> case_transition_service -> ... -> uploads is a cycle at import.
        self.assertNotIn("public_demo_service", vars(uploads))


class DemoNamespaceTests(BaseTestCase):
    """The demo's Redis and Celery namespace is chosen in ``create_app`` before
    the extensions read their settings; the flag off changes nothing."""

    def _app(self, enabled):
        from config import TestConfig
        from tests.base import create_app_without_celery_takeover

        class Config(TestConfig):
            PUBLIC_DEMO_ENABLED = enabled

        saved = limiter._key_prefix
        self.addCleanup(setattr, limiter, "_key_prefix", saved)
        limiter._key_prefix = ""
        return create_app_without_celery_takeover(Config)

    def test_flag_on_namespaces_cache_rate_limit_grants_locks_and_celery(self):
        from app import cache

        app = self._app(True)
        self.assertEqual(app.config["CACHE_KEY_PREFIX"], "digitva_demo:")
        self.assertEqual(app.config["RATELIMIT_KEY_PREFIX"], "demo")
        self.assertEqual(limiter._key_prefix, "demo")  # read at limiter.init_app
        self.assertEqual(app.config["AUTHZ_GRANT_CACHE_PREFIX"], "digitva_demo_authz:")
        self.assertEqual(app.config["NOTIFICATION_CACHE_PREFIX"], "digitva_demo_msg:last:")
        self.assertEqual(app.config["SWEEP_LOCK_KEY_PREFIX"], "demo:")
        with app.app_context():
            self.assertEqual(cache.cache.key_prefix, "digitva_demo:")
        conf = app.extensions["celery"].conf
        self.assertEqual(conf.task_default_queue, "demo")
        self.assertEqual(conf.broker_transport_options["global_keyprefix"], "demo:")
        self.assertEqual(conf.result_backend_transport_options["global_keyprefix"], "demo:")
        # The rest of the Celery settings are kept.
        self.assertEqual(conf.worker_prefetch_multiplier, 1)
        self.assertTrue(conf.task_ignore_result)

    def test_a_demo_app_leaves_the_limiter_prefix_as_it_found_it(self):
        before = limiter._key_prefix
        self._app(True)
        self.doCleanups()
        self.assertEqual(limiter._key_prefix, before)

    def test_flag_off_keeps_the_main_deployments_names(self):
        from app import cache

        app = self._app(False)
        self.assertEqual(app.config["CACHE_KEY_PREFIX"], "digitva_cache:")
        self.assertNotIn("RATELIMIT_KEY_PREFIX", app.config)
        self.assertEqual(limiter._key_prefix, "")
        self.assertEqual(app.config["AUTHZ_GRANT_CACHE_PREFIX"], "digitva_authz:")
        self.assertEqual(app.config["NOTIFICATION_CACHE_PREFIX"], "digitva_msg:last:")
        self.assertNotIn("SWEEP_LOCK_KEY_PREFIX", app.config)
        with app.app_context():
            self.assertEqual(cache.cache.key_prefix, "digitva_cache:")
        conf = app.extensions["celery"].conf
        self.assertEqual(conf.task_default_queue, "celery")
        self.assertFalse(conf.broker_transport_options)
        self.assertFalse(conf.result_backend_transport_options)

    def test_the_sweep_lock_key_is_namespaced_only_on_the_demo(self):
        from app.tasks import sync_tasks

        calls = []

        class Client:
            def set(self, key, token, nx, ex):
                calls.append(key)
                return True

            def get(self, key):
                return None

            def delete(self, key):
                pass

        with mock.patch.object(sync_tasks, "_lock_client", return_value=Client()):
            with sync_tasks._sweep_lock("digitva:lock:x", 10):
                pass
            with mock.patch.dict(self.app.config, SWEEP_LOCK_KEY_PREFIX="demo:"):
                with sync_tasks._sweep_lock("digitva:lock:x", 10):
                    pass
        self.assertEqual(calls, ["digitva:lock:x", "demo:digitva:lock:x"])

    def test_no_task_or_beat_row_names_a_queue(self):
        # Every task rides the default queue, which the worker (started
        # without -Q) consumes; a queue named anywhere would bypass "demo".
        import pathlib
        import re

        root = pathlib.Path(self.app.root_path)
        offenders = [
            str(path.relative_to(root))
            for path in root.rglob("*.py")
            if re.search(r"\b(queue|routing_key|task_routes)\s*=\s*[\"'{]", path.read_text())
        ]
        self.assertEqual(offenders, [])


class BeatScheduleTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        # The base test project makes this database look like the main one.
        patcher = mock.patch.object(demo, "foreign_projects_exist", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _patch_all(self):
        """Patch every ensure_* seeder and return {name: mock}."""
        targets = {
            "ensure_sync_scheduled": "app.tasks.sync_tasks",
            "ensure_smartva_sweep_scheduled": "app.tasks.sync_tasks",
            "ensure_coding_timeout_cleanup_scheduled": "app.tasks.sync_tasks",
            "ensure_demo_cleanup_scheduled": "app.tasks.sync_tasks",
            "ensure_submission_analytics_mv_refresh_scheduled": "app.tasks.sync_tasks",
            "ensure_attachment_s3_upload_scheduled": "app.tasks.sync_tasks",
            "ensure_db_backup_scheduled": "app.tasks.backup_tasks",
            "ensure_weekly_demo_reset_scheduled": "app.tasks.organization_demo_tasks",
            "ensure_tls_health_scheduled": "app.tasks.tls_health_tasks",
            "ensure_coding_search_telemetry_prune_scheduled": "app.tasks.coding_search_telemetry_tasks",
            "ensure_notification_purge_scheduled": "app.tasks.notification_tasks",
            "ensure_sign_in_ip_wipe_scheduled": "app.tasks.security_event_tasks",
            "ensure_web_intake_upload_purge_scheduled": "app.tasks.web_intake_upload_tasks",
            "ensure_public_demo_purge_scheduled": "app.tasks.public_demo_tasks",
        }
        patches = {}
        for name, module in targets.items():
            patcher = mock.patch(f"{module}.{name}")
            patches[name] = patcher.start()
            self.addCleanup(patcher.stop)
        return patches

    def test_worker_startup_branches_on_the_flag_and_keeps_the_main_sequence(self):
        import pathlib

        source = (pathlib.Path(self.app.root_path).parent / "make_celery.py").read_text()
        on, off = source.split('if flask_app.config.get("PUBLIC_DEMO_ENABLED"):')[1].split("    else:")
        self.assertIn("seed_demo_beat_schedule()", on)
        self.assertNotIn("ensure_sync_scheduled", on)
        order = [
            "ensure_sync_scheduled()", "ensure_smartva_sweep_scheduled()",
            "ensure_coding_timeout_cleanup_scheduled()", "ensure_demo_cleanup_scheduled()",
            "ensure_submission_analytics_mv_refresh_scheduled()", "ensure_db_backup_scheduled()",
            "ensure_weekly_demo_reset_scheduled()", "ensure_tls_health_scheduled()",
            "ensure_attachment_s3_upload_scheduled()", "ensure_coding_search_telemetry_prune_scheduled()",
            "ensure_notification_purge_scheduled()", "ensure_sign_in_ip_wipe_scheduled()",
            "ensure_web_intake_upload_purge_scheduled()",
        ]
        self.assertEqual([off.index(call) for call in order], sorted(off.index(call) for call in order))

    def test_flag_on_seeds_only_the_allowlist_and_disables_the_rest(self):
        from app.tasks.beat_schedule import seed_demo_beat_schedule

        ensures = self._patch_all()
        with mock.patch("app.tasks.beat_schedule.disable_off_allowlist", return_value=0) as disable:
            seed_demo_beat_schedule()
        called = {name for name, patched in ensures.items() if patched.called}
        self.assertEqual(called, {
            "ensure_smartva_sweep_scheduled", "ensure_coding_timeout_cleanup_scheduled",
            "ensure_web_intake_upload_purge_scheduled", "ensure_notification_purge_scheduled",
            "ensure_sign_in_ip_wipe_scheduled", "ensure_coding_search_telemetry_prune_scheduled",
            "ensure_db_backup_scheduled", "ensure_public_demo_purge_scheduled",
        })
        ensures["ensure_smartva_sweep_scheduled"].assert_called_once_with(bundle_applier=False)
        disable.assert_called_once_with()

    def test_smartva_sweep_seeds_the_bundle_applier_unless_told_not_to(self):
        from app.tasks import sync_tasks

        with mock.patch.object(sync_tasks, "ensure_bundle_pending_coding_scheduled") as bundle, \
                mock.patch.object(sync_tasks, "_ensure_interval_task", return_value=False):
            sync_tasks.ensure_smartva_sweep_scheduled()
            self.assertEqual(bundle.call_count, 1)
            sync_tasks.ensure_smartva_sweep_scheduled(bundle_applier=False)
            self.assertEqual(bundle.call_count, 1)

    def test_allowlist_names_real_registered_tasks_and_not_main_only_ones(self):
        import app.tasks.backup_tasks  # noqa: F401  (register the tasks)
        import app.tasks.coding_search_telemetry_tasks  # noqa: F401
        import app.tasks.notification_tasks  # noqa: F401
        import app.tasks.public_demo_tasks  # noqa: F401
        import app.tasks.security_event_tasks  # noqa: F401
        import app.tasks.sync_tasks  # noqa: F401
        import app.tasks.web_intake_upload_tasks  # noqa: F401
        from app.tasks.beat_schedule import DEMO_BEAT_TASKS

        registered = set(self.app.extensions["celery"].tasks)
        self.assertLessEqual(set(DEMO_BEAT_TASKS), registered)
        for main_only in ("app.tasks.sync_tasks.run_odk_sync", "app.tasks.sync_tasks.apply_bundle_pending_coding"):
            self.assertNotIn(main_only, DEMO_BEAT_TASKS)

    def test_disable_off_allowlist_updates_only_rows_outside_the_list(self):
        from contextlib import contextmanager

        from app.tasks import beat_schedule

        writes = []

        class Conn:
            def execute(self, statement, params=None):
                writes.append((str(statement), params))
                return mock.Mock(rowcount=3)

        @contextmanager
        def begin():
            yield Conn()

        with mock.patch("app.db", mock.Mock(engine=mock.Mock(begin=begin))):
            self.assertEqual(beat_schedule.disable_off_allowlist(), 3)
        update, params = writes[0]
        self.assertIn("UPDATE public.celery_periodictask SET enabled = false", update)
        self.assertIn("task NOT IN", update)
        self.assertEqual(params, {"allowed": sorted(beat_schedule.DEMO_BEAT_TASKS)})
        self.assertTrue(any("celery_periodictaskchanged" in sql for sql, _ in writes[1:]))

    def test_disable_off_allowlist_leaves_the_change_marker_alone_when_nothing_changed(self):
        from contextlib import contextmanager

        from app.tasks import beat_schedule

        writes = []

        class Conn:
            def execute(self, statement, params=None):
                writes.append(str(statement))
                return mock.Mock(rowcount=0)

        @contextmanager
        def begin():
            yield Conn()

        with mock.patch("app.db", mock.Mock(engine=mock.Mock(begin=begin))):
            self.assertEqual(beat_schedule.disable_off_allowlist(), 0)
        self.assertEqual(len(writes), 1)

    def test_the_purge_is_on_the_allowlist(self):
        from app.tasks.beat_schedule import DEMO_BEAT_TASKS
        from app.tasks.public_demo_tasks import PUBLIC_DEMO_PURGE_TASK_NAME

        self.assertIn(PUBLIC_DEMO_PURGE_TASK_NAME, DEMO_BEAT_TASKS)

    def test_a_main_database_is_left_alone(self):
        from app.tasks import beat_schedule

        ensures = self._patch_all()
        with mock.patch.object(demo, "foreign_projects_exist", return_value=True), \
                mock.patch("app.db") as db_mock:
            self.assertEqual(beat_schedule.seed_demo_beat_schedule(), 0)
            self.assertEqual(beat_schedule.disable_off_allowlist(), 0)
        self.assertFalse(any(patched.called for patched in ensures.values()))
        db_mock.engine.begin.assert_not_called()
