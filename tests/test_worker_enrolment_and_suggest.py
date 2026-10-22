"""Add worker: account suggestions while typing (digitva-r8op) and the app
enrolment email to new data collectors (digitva-o0nq).

Policy: docs/policy/organization-model.md (lookup + suggestions) and
docs/policy/mobile-sign-in.md section 6 (enrolment email).
"""
import json
from datetime import UTC, datetime
from unittest.mock import patch

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.auth_devices import AuthDeviceEnrolmentCode
from app.models.mas_languages import MasLanguages
from app.services import organization_service as org
from app.services.email_service import mail
from tests.base import BaseTestCase

APK = "https://github.com/example/digitva/releases/download/android-v0.1.0/digitva-collect.apk"


def _user(email, *, name, mobile=None, active=True):
    user = VaUsers(
        name=name, email=email, phone=mobile, mobile_login=mobile,
        user_status=VaStatuses.active if active else VaStatuses.deactive,
        permission={}, landing_page="coder", pw_reset_t_and_c=False,
        email_verified=True, vacode_language=["en"],
    )
    user.set_password("UnusedPassword123!")
    db.session.add(user)
    return user


class _OrgProjectCase(BaseTestCase):
    PROJECT = "WENR01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT, project_code=cls.PROJECT, project_name="Enrolment Email Project",
            project_nickname="Enrol", project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now, project_structure_mode="organization",
        ))
        if db.session.get(MasLanguages, "en") is None:
            db.session.add(MasLanguages(language_code="en", language_name="English", is_active=True))
        db.session.add(VaUserAccessGrants(
            user_id=cls.base_project_pi_user.user_id, role=VaAccessRoles.project_pi,
            scope_type=VaAccessScopeTypes.project, project_id=cls.PROJECT, grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()

    def _url(self, suffix=""):
        return f"/admin/api/organization/{self.PROJECT}{suffix}"


class UserSuggestionTests(_OrgProjectCase):
    def setUp(self):
        super().setUp()
        _user("asha.sugg@example.org", name="Asha Sugg", mobile="9811100001")
        _user("asha.sugg.two@example.org", name="Asha Two", mobile="9811100002")
        _user("ashasugg@example.org", name="Asha Exact", mobile="9811100003")
        _user("asha.sugg.gone@example.org", name="Asha Gone", mobile="9811100004", active=False)
        for i in range(10):
            _user(f"bulk.sugg{i:02d}@example.org", name=f"Bulk {i:02d}")
        db.session.commit()

    def _suggest(self, q):
        res = self.client.get(self._url("/users/lookup"), query_string={"q": q, "suggest": "1"})
        self.assertEqual(res.status_code, 200)
        return res.get_json()

    def test_email_contains_match_excludes_inactive(self):
        self._login(str(self.base_admin_id))
        emails = [s["email"] for s in self._suggest("ASHA.SUGG")["suggestions"]]
        self.assertIn("asha.sugg@example.org", emails)
        self.assertIn("asha.sugg.two@example.org", emails)
        self.assertNotIn("asha.sugg.gone@example.org", emails)

    def test_exact_match_first_and_exact_lookup_still_answers(self):
        self._login(str(self.base_admin_id))
        body = self._suggest("ashasugg@example.org")
        self.assertTrue(body["found"])
        self.assertEqual(body["user"]["email"], "ashasugg@example.org")
        self.assertEqual(body["suggestions"][0]["email"], "ashasugg@example.org")

    def test_rank_beats_name_order(self):
        # Name order is the reverse of rank order: exact, then prefix, then contains.
        _user("aa.rank.sugg@example.org", name="Aaa Contains")
        _user("rank.sugg@example.org.extra", name="Mmm Prefix")
        _user("rank.sugg@example.org", name="Zzz Exact")
        db.session.commit()
        self._login(str(self.base_admin_id))
        emails = [s["email"] for s in self._suggest("rank.sugg@example.org")["suggestions"]]
        self.assertEqual(emails, ["rank.sugg@example.org", "rank.sugg@example.org.extra", "aa.rank.sugg@example.org"])

    def test_limit_is_eight(self):
        self._login(str(self.base_admin_id))
        self.assertEqual(len(self._suggest("bulk.sugg")["suggestions"]), 8)

    def test_partial_phone_and_pi_sees_only_typed_channel(self):
        self._login(str(self.base_admin_id))
        admin_rows = self._suggest("98111000")["suggestions"]
        mobiles = {s["mobile"] for s in admin_rows}
        self.assertTrue({"9811100001", "9811100002", "9811100003"} <= mobiles)
        self.assertNotIn("9811100004", mobiles)
        self.assertIsNotNone(admin_rows[0]["email"])

        self._login(str(self.base_project_pi_id))
        pi_rows = self._suggest("1100001")["suggestions"]
        self.assertEqual([s["mobile"] for s in pi_rows], ["9811100001"])
        self.assertIsNone(pi_rows[0]["email"])
        pi_email_rows = self._suggest("asha.sugg.two")["suggestions"]
        self.assertEqual(pi_email_rows[0]["email"], "asha.sugg.two@example.org")
        self.assertIsNone(pi_email_rows[0]["mobile"])
        self.assertEqual(set(pi_email_rows[0]), {"user_id", "name", "email", "mobile"})

    def test_short_queries_and_wildcards_return_nothing(self):
        self._login(str(self.base_admin_id))
        self.assertEqual(self._suggest("as")["suggestions"], [])
        self.assertEqual(self._suggest("981")["suggestions"], [])
        self.assertEqual(self._suggest("%%%")["suggestions"], [])
        self.assertNotIn("suggestions", self.client.get(
            self._url("/users/lookup"), query_string={"q": "asha.sugg"}).get_json())

    def test_role_access(self):
        self._login(str(self.base_coder_id))
        res = self.client.get(self._url("/users/lookup"), query_string={"q": "asha", "suggest": "1"})
        self.assertIn(res.status_code, (302, 403))

    def test_rate_limit_sixty_per_minute(self):
        self._login(str(self.base_admin_id))
        for _ in range(60):
            self.assertEqual(self.client.get(self._url("/users/lookup"), query_string={"q": "zz9", "suggest": "1"}).status_code, 200)
        self.assertEqual(self.client.get(self._url("/users/lookup"), query_string={"q": "zz9", "suggest": "1"}).status_code, 429)


class EnrolmentEmailTests(_OrgProjectCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        org.seed_default_organization(cls.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(cls.PROJECT)}
        cls.cadres = {c.cadre_code: c for c in org.list_cadres(cls.PROJECT)}
        dist = org.create_unit(cls.PROJECT, org_level_id=levels["district"].org_level_id,
                               unit_code="ENRD1", unit_name="Enrol District")
        cls.chc = org.create_unit(cls.PROJECT, org_level_id=levels["chc"].org_level_id,
                                  parent_org_unit_id=dist.org_unit_id, unit_code="ENRC1", unit_name="Enrol CHC")
        phc = org.create_unit(cls.PROJECT, org_level_id=levels["phc"].org_level_id,
                              parent_org_unit_id=cls.chc.org_unit_id, unit_code="ENRP1", unit_name="Enrol PHC")
        cls.sc = org.create_unit(cls.PROJECT, org_level_id=levels["subcentre"].org_level_id,
                                 parent_org_unit_id=phc.org_unit_id, unit_code="ENRS1", unit_name="Enrol SC")
        db.session.commit()

    def setUp(self):
        super().setUp()
        self._login(str(self.base_admin_id))
        self._config = patch.dict(self.app.config, {
            "MAIL_SERVER": "smtp.test.invalid", "MAIL_SUPPRESS_SEND": True,
            "DIGITVA_ANDROID_APK_URL": APK,
        })
        self._config.start()
        self.addCleanup(self._config.stop)

    def _create(self, unit, cadre_code, email, **extra):
        body = {
            "org_unit_id": str(unit.org_unit_id), "cadre_id": str(self.cadres[cadre_code].cadre_id),
            "worker_name": "Field Worker", "email": email, "email_confirm": email, "language_codes": "en",
            **extra,
        }
        return self.client.post(self._url("/workers"), json=body, headers=self._csrf_headers())

    def _codes(self):
        return db.session.scalar(sa.select(sa.func.count()).select_from(AuthDeviceEnrolmentCode).where(
            AuthDeviceEnrolmentCode.project_id == self.PROJECT))

    def _assert_enrolment_message(self, msg, to):
        self.assertEqual(msg.recipients, [to])
        self.assertEqual(msg.subject, "Set up the DigitVA Collect app")
        self.assertIn(APK, msg.html)
        self.assertIn(APK, msg.body)
        self.assertIn('src="cid:enrolment-qr"', msg.html)
        for step in ("allow installing apps from this source", "scan the QR", "Set a PIN"):
            self.assertIn(step.lower(), msg.body.lower())
        [qr] = msg.attachments
        self.assertEqual(qr.content_type, "image/png")
        self.assertEqual(qr.disposition, "inline")
        self.assertEqual(qr.headers, {"Content-ID": "<enrolment-qr>"})
        self.assertTrue(qr.data.startswith(b"\x89PNG"))

    def test_interviewer_gets_qr_apk_and_steps(self):
        before = self._codes()
        with mail.record_messages() as outbox:
            res = self._create(self.chc, "SN", "new.interviewer@example.org")
        self.assertEqual(res.status_code, 201, res.get_json())
        self.assertEqual(res.get_json()["onboarding"]["enrolment_email"], "sent")
        enrolment = [m for m in outbox if m.subject == "Set up the DigitVA Collect app"]
        self.assertEqual(len(enrolment), 1)
        self._assert_enrolment_message(enrolment[0], "new.interviewer@example.org")
        self.assertEqual(self._codes(), before + 1)
        row = db.session.scalars(sa.select(AuthDeviceEnrolmentCode).where(
            AuthDeviceEnrolmentCode.project_id == self.PROJECT).order_by(AuthDeviceEnrolmentCode.created_at.desc())).first()
        self.assertEqual(row.max_uses, 1)
        hours = (row.expires_at - row.created_at).total_seconds() / 3600
        self.assertAlmostEqual(hours, 24, delta=0.1)

    def test_qr_payload_matches_devices_page(self):
        from app.services import device_auth_service as devices

        captured = {}
        real = devices.enrolment_qr_payload

        def spy(row, code):
            captured["payload"] = real(row, code)
            captured["code"] = code
            return captured["payload"]

        with patch.object(devices, "enrolment_qr_payload", side_effect=spy), mail.record_messages() as outbox:
            self._create(self.sc, "ANM", "new.reporter@example.org")
        payload = json.loads(captured["payload"])
        self.assertEqual(set(payload), {"v", "server", "enroll", "project"})
        self.assertEqual(payload["project"], self.PROJECT)
        msg = next(m for m in outbox if m.subject == "Set up the DigitVA Collect app")
        self._assert_enrolment_message(msg, "new.reporter@example.org")
        self.assertIn(captured["code"], msg.body)

    def test_coder_only_gets_no_enrolment_email(self):
        before = self._codes()
        with mail.record_messages() as outbox:
            res = self._create(self.chc, "MO", "new.coder@example.org")
        self.assertEqual(res.status_code, 201, res.get_json())
        self.assertIsNone(res.get_json()["onboarding"]["enrolment_email"])
        self.assertFalse([m for m in outbox if m.subject == "Set up the DigitVA Collect app"])
        self.assertEqual(self._codes(), before)

    def test_no_second_email_when_relinked_unchanged(self):
        with mail.record_messages() as outbox:
            first = self._create(self.chc, "SN", "twice.interviewer@example.org")
            self.assertEqual(first.status_code, 201, first.get_json())
            second = self._create(self.chc, "SN", "twice.interviewer@example.org")
        self.assertEqual(second.status_code, 201, second.get_json())
        self.assertIsNone(second.get_json()["onboarding"]["enrolment_email"])
        self.assertEqual(len([m for m in outbox if m.subject == "Set up the DigitVA Collect app"]), 1)

    def test_send_failure_does_not_block_save(self):
        with patch("app.services.email_service.mail.send", side_effect=OSError("smtp down")):
            res = self._create(self.chc, "SN", "fails.interviewer@example.org")
        self.assertEqual(res.status_code, 201, res.get_json())
        body = res.get_json()
        self.assertEqual(body["onboarding"]["enrolment_email"], "failed")
        self.assertIn("Enrolment email could not be sent.", body["onboarding"]["invite_warnings"])
        self.assertIsNotNone(db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "fails.interviewer@example.org")))

    def test_missing_apk_url_says_supervisor_will_share(self):
        with patch.dict(self.app.config, {"DIGITVA_ANDROID_APK_URL": ""}), mail.record_messages() as outbox:
            res = self._create(self.chc, "SN", "noapk.interviewer@example.org")
        self.assertEqual(res.get_json()["onboarding"]["enrolment_email"], "sent")
        msg = next(m for m in outbox if m.subject == "Set up the DigitVA Collect app")
        self.assertIn("Your supervisor will share the app", msg.body)

    def test_mail_suppress_send_records_but_never_opens_smtp(self):
        with patch("smtplib.SMTP") as smtp, mail.record_messages() as outbox:
            res = self._create(self.chc, "SN", "suppressed.interviewer@example.org")
        self.assertEqual(res.get_json()["onboarding"]["enrolment_email"], "sent")
        self.assertTrue([m for m in outbox if m.subject == "Set up the DigitVA Collect app"])
        smtp.assert_not_called()

    def test_resend_sends_fresh_code_for_admin_and_pi(self):
        created = self._create(self.chc, "SN", "resend.interviewer@example.org")
        worker_id = created.get_json()["worker"]["worker_id"]
        before = self._codes()
        for who in (self.base_admin_id, self.base_project_pi_id):
            self._login(str(who))
            with mail.record_messages() as outbox:
                res = self.client.post(self._url(f"/workers/{worker_id}/enrolment-email"), headers=self._csrf_headers())
            self.assertEqual(res.status_code, 200, res.get_json())
            self.assertEqual(len(outbox), 1)
            self._assert_enrolment_message(outbox[0], "resend.interviewer@example.org")
        self.assertEqual(self._codes(), before + 2)

    def test_resend_refused_for_coder_worker_and_non_manager(self):
        created = self._create(self.chc, "MO", "resend.coder@example.org")
        worker_id = created.get_json()["worker"]["worker_id"]
        res = self.client.post(self._url(f"/workers/{worker_id}/enrolment-email"), headers=self._csrf_headers())
        self.assertEqual(res.status_code, 400)
        self.assertIn("not an interviewer or death reporter", res.get_json()["error"])
        self._login(str(self.base_coder_id))
        res = self.client.post(self._url(f"/workers/{worker_id}/enrolment-email"), headers=self._csrf_headers())
        self.assertIn(res.status_code, (302, 403))

    def test_resend_failure_is_reported(self):
        created = self._create(self.chc, "SN", "resend.fails@example.org")
        worker_id = created.get_json()["worker"]["worker_id"]
        with patch("app.services.email_service.mail.send", side_effect=OSError("smtp down")):
            res = self.client.post(self._url(f"/workers/{worker_id}/enrolment-email"), headers=self._csrf_headers())
        self.assertEqual(res.status_code, 502)
        self.assertEqual(res.get_json()["error"], "Enrolment email could not be sent.")
