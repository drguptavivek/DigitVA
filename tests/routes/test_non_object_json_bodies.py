"""A JSON body that is not an object, or a field of the wrong type, is a 400
``invalid_request`` on the API routes that read it, never a 500; and the
coder's current allocation reports its submission date in the user's
timezone (digitva-2s6p #8, #9)."""
import uuid
from datetime import UTC, datetime, timedelta

from app import db, limiter
from app.models import (
    AuthWebauthnCredential,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaForms,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
)
from tests.base import BaseTestCase

_SUFFIX = uuid.uuid4().hex[:4].upper()


class NonObjectBodyTests(BaseTestCase):
    BASE_PROJECT_ID = f"JB{_SUFFIX}"
    BASE_SITE_ID = f"J{_SUFFIX[:3]}"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_base_research_project_and_site()
        form = VaForms(
            form_id=f"{cls.BASE_PROJECT_ID}{cls.BASE_SITE_ID}01",
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            odk_form_id="JSON_BODY_FORM",
            odk_project_id="1",
            form_type="WHO 2022 VA",
            form_status=VaStatuses.active,
        )
        db.session.add(form)
        db.session.flush()
        cls.sid = f"uuid:json-body-{_SUFFIX.lower()}"
        db.session.add(
            VaSubmissions(
                va_sid=cls.sid,
                va_form_id=form.form_id,
                # 20:00 UTC is 01:30 the next day in Asia/Kolkata.
                va_submission_date=datetime(2026, 3, 10, 20, 0, tzinfo=UTC),
                va_odk_updatedat=datetime.now(UTC),
                va_data_collector="tester",
                va_instance_name="JSON-1",
                va_uniqueid_masked="JSON-1",
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=50,
                va_deceased_gender="male",
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()

    def _assert_invalid(self, response):
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        body = response.get_json()
        self.assertEqual(body["code"], "invalid_request")
        self.assertTrue(body["error"])

    def _send(self, method, path, body):
        return self.client.open(
            path, method=method, json=body, headers=self._csrf_headers()
        )

    # -- coding allocation ------------------------------------------------

    def test_coding_allocation_refuses_non_object_and_non_text_fields(self):
        self._login(self.base_admin_id)
        for body in ([1], 7, "sid", {"project_id": 5}, {"sid": 5}):
            with self.subTest(body=body):
                self._assert_invalid(self._send("POST", "/api/v1/coding/allocation", body))
        # Present first: an object body still reaches the allocator.
        reached = self._send("POST", "/api/v1/coding/allocation", {"sid": "NO-SUCH-SID"})
        self.assertEqual(reached.status_code, 404)

    # -- ICD-10 policy ----------------------------------------------------

    def test_icd10_policy_refuses_a_list_body(self):
        self._login(self.base_admin_id)
        self._assert_invalid(self._send("PATCH", "/api/v1/icd10/2019-2/node/A00/policy", [1]))

    # -- profile ----------------------------------------------------------

    def test_profile_timezone_refuses_list_and_numeric_timezone(self):
        self._login(self.base_admin_id)
        for body in ([1], {"timezone": 5}):
            with self.subTest(body=body):
                self._assert_invalid(self._send("PATCH", "/api/v1/profile/timezone", body))

    def test_profile_interviewer_refuses_a_list_body(self):
        self._login(self.base_admin_id)
        self._assert_invalid(self._send("PATCH", "/api/v1/profile/interviewer", [1]))

    def test_profile_reauth_refuses_list_and_numeric_password(self):
        self._login(self.base_admin_id)
        self._assert_invalid(self._send("POST", "/api/v1/profile/reauth", [1]))
        wrong_type = self._send("POST", "/api/v1/profile/reauth", {"password": 5})
        self.assertEqual(wrong_type.status_code, 403)
        self.assertEqual(wrong_type.get_json()["error"], "Incorrect password.")

    def _reauthenticated(self):
        self._login(self.base_admin_id)
        with self.client.session_transaction() as sess:
            sess["auth_verified_at"] = datetime.now(UTC).isoformat()

    def test_passkey_register_refuses_a_list_body(self):
        self._reauthenticated()
        for body in ([1], {"name": 5, "credential": {}}):
            with self.subTest(body=body):
                self._assert_invalid(self._send("POST", "/api/v1/profile/passkeys", body))

    def test_passkey_rename_refuses_list_body_and_numeric_name(self):
        cred = AuthWebauthnCredential(
            user_id=self.base_admin_user.user_id,
            credential_id=uuid.uuid4().bytes,
            public_key=b"key",
            sign_count=0,
            name="Key",
        )
        db.session.add(cred)
        db.session.commit()
        self._reauthenticated()
        path = f"/api/v1/profile/passkeys/{cred.id}"
        for body in ([1], {"name": 5}):
            with self.subTest(body=body):
                self._assert_invalid(self._send("PATCH", path, body))

    # -- data management --------------------------------------------------

    def _login_data_manager(self):
        db.session.add(
            VaUserAccessGrants(
                user_id=self.base_project_pi_user.user_id,
                role=VaAccessRoles.data_manager,
                scope_type=VaAccessScopeTypes.project,
                project_id=self.BASE_PROJECT_ID,
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()
        self._login(self.base_project_pi_id)

    def test_dm_sync_preview_refuses_list_body_and_non_list_ids(self):
        self._login_data_manager()
        for body in ([1], {"project_ids": 5}, {"site_ids": [{"a": 1}]}):
            with self.subTest(body=body):
                self._assert_invalid(
                    self._send("POST", "/api/v1/data-management/sync/preview", body)
                )

    def test_dm_org_unit_pin_refuses_a_list_body(self):
        self._login_data_manager()
        self._assert_invalid(
            self._send("POST", f"/api/v1/data-management/submissions/{self.sid}/org-unit", [1])
        )

    # -- #8: the allocation's date is the user's local date ----------------

    def test_current_allocation_date_is_in_the_user_timezone(self):
        self.base_coder_user.timezone = "Asia/Kolkata"
        db.session.add(
            VaAllocations(
                va_sid=self.sid,
                va_allocated_to=self.base_coder_user.user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
                va_allocation_createdat=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        db.session.commit()
        self._login(self.base_coder_id)

        allocation = self.client.get("/api/v1/coding/allocation").get_json()["allocation"]

        self.assertIsNotNone(allocation)
        self.assertEqual(allocation["va_sid"], self.sid)
        self.assertEqual(allocation["va_submission_date"], "2026-03-11")
