"""Consent notice placeholders filled from the PUBLIC_* settings (digitva-e9hx):
on "Seed from draft" and on Project Setup's "Fill from settings", only when a
version is saved. Policy: docs/policy/respondent-consent-notice-draft.md
"Seed text for Project Setup"."""
import copy
import hashlib
import re
from datetime import UTC, datetime
from unittest.mock import patch

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    MapConsentAudit,
    MasConsentNoticeVersion,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import consent_service
from app.services.consent_notice_seed import SEED_PURPOSES, SEED_TEXT, standalone_bundle_sha256
from tests.base import BaseTestCase

PLACEHOLDER = re.compile(r"\[[^]]*\]")
INSTITUTION = {"en": "[INSTITUTION NAME, EMAIL, PHONE]", "hi": "[संस्थान का नाम, ईमेल, फ़ोन]"}
EMPTY = {"PUBLIC_ORG_NAME": "", "PUBLIC_CONTACT_EMAIL": "", "PUBLIC_GRIEVANCE_OFFICER": ""}


class ConsentNoticeFillTests(BaseTestCase):
    PROJECT = "CNF01"
    DEMO = "CNF02"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id in (cls.PROJECT, cls.DEMO):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=f"Fill {project_id}",
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
        db.session.flush()
        cls.interviewer = cls._get_or_make_user("consent.fill.interviewer@test.local", "Consent123!")
        db.session.add(VaUserAccessGrants(
            user_id=cls.interviewer.user_id, role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project, project_id=cls.PROJECT,
            notes="consent fill test grant", grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()

    def _settings(self, **overrides):
        return {
            "PUBLIC_ORG_NAME": "Org X", "PUBLIC_CONTACT_EMAIL": "privacy@example.org",
            "PUBLIC_GRIEVANCE_OFFICER": "Dr A B", "PUBLIC_DEMO_PROJECT_ID": self.DEMO,
            "PUBLIC_DEMO_PURGE_IDLE_DAYS": 30, "PUBLIC_DEMO_ENABLED": True,
            "PUBLIC_DEMO_PURGE_ENABLED": True, **overrides,
        }

    def _seed(self, project_id, **settings):
        with patch.dict(self.app.config, self._settings(**settings)):
            rows = consent_service.seed_notice_versions(self.base_admin_user, project_id)
        db.session.flush()
        return {row.language: row for row in rows}

    def _versions(self, project_id):
        return db.session.scalars(sa.select(MasConsentNoticeVersion).where(
            MasConsentNoticeVersion.project_id == project_id)).all()

    # ── the shared filling, through the seed ───────────────────────────────

    def test_seed_fills_every_placeholder_in_both_languages_on_the_demo(self):
        purposes_before, bundle_before = copy.deepcopy(SEED_PURPOSES), standalone_bundle_sha256()
        rows = self._seed(self.DEMO)
        expected = {
            "en": ["Fill CNF02: information", "controlled by Org X in India",
                   "complain to the Grievance Officer, Dr A B (privacy@example.org) and then",
                   "Deletion or exclusion of your data: privacy@example.org. Quote",
                   "The central team: privacy@example.org.\n",
                   "How long we keep it. This is a public demo for practice only. Everything entered, including "
                   "this interview, is deleted 30 days after the demo account was last used.\n",
                   "Your district team: not applicable in the public demo.\n"],
            "hi": ["Fill CNF02: आपके", "भारत में Org X द्वारा",
                   "आप शिकायत अधिकारी, Dr A B (privacy@example.org) से",
                   "बाहर रखने के लिए: privacy@example.org। आपको",
                   "केंद्रीय टीम: privacy@example.org।\n",
                   "हम इसे कितने समय तक रखते हैं। यह केवल अभ्यास के लिए एक सार्वजनिक डेमो है। इसमें दर्ज सब कुछ, "
                   "यह साक्षात्कार भी, डेमो खाते के अंतिम उपयोग के 30 दिन बाद मिटा दिया जाता है।\n",
                   "आपकी ज़िला टीम: सार्वजनिक डेमो में लागू नहीं।\n"],
        }
        for language, row in rows.items():
            for fragment in expected[language]:
                self.assertIn(fragment, row.text)
            # The mentoring institution is the only placeholder no setting fills.
            self.assertEqual(set(PLACEHOLDER.findall(row.text)), {INSTITUTION[language]})
            self.assertEqual(row.text_sha256, hashlib.sha256(row.text.encode("utf-8")).hexdigest())
            labels = {p["code"]: p["label"] for p in row.purposes}
            self.assertIn("Org X", labels["narrative_automated_processing"])
            self.assertFalse(any(PLACEHOLDER.search(label) for label in labels.values()), labels)
        # The module constants (and so the Collect Plus bundle hash) are untouched.
        self.assertEqual(SEED_PURPOSES, purposes_before)
        self.assertEqual(standalone_bundle_sha256(), bundle_before)

    def test_demo_lines_appear_only_on_the_demo_project(self):
        rows = self._seed(self.PROJECT)
        self.assertIn("[RETENTION PERIOD AND WHAT HAPPENS AFTER]", rows["en"].text)
        self.assertIn("[DISTRICT CONTACT NAME, EMAIL, PHONE]", rows["en"].text)
        self.assertIn("[रखने की अवधि और उसके बाद क्या होगा]", rows["hi"].text)
        self.assertIn("[ज़िला संपर्क का नाम, ईमेल, फ़ोन]", rows["hi"].text)
        for row in rows.values():
            self.assertIn("Org X", row.text)  # the shared fills still apply
            self.assertNotIn("public demo", row.text)
            self.assertNotIn("सार्वजनिक डेमो", row.text)

    def test_demo_retention_promise_waits_for_the_purge_and_the_demo(self):
        # Purge off: the deletion promise would be untrue, so its placeholder stays; the district line fills.
        rows = self._seed(self.DEMO, PUBLIC_DEMO_PURGE_ENABLED=False)
        self.assertIn("Your district team: not applicable in the public demo.", rows["en"].text)
        self.assertIn("[RETENTION PERIOD AND WHAT HAPPENS AFTER]", rows["en"].text)
        self.assertIn("[रखने की अवधि और उसके बाद क्या होगा]", rows["hi"].text)
        self.assertNotIn("is deleted 30 days", rows["en"].text)

    def test_demo_lines_need_a_demo_deployment(self):
        # A project that happens to be called PUB01 on a non-demo deployment is an ordinary project.
        rows = self._seed(self.DEMO, PUBLIC_DEMO_ENABLED=False)
        self.assertIn("Org X", rows["en"].text)
        self.assertIn("[DISTRICT CONTACT NAME, EMAIL, PHONE]", rows["en"].text)
        self.assertIn("[RETENTION PERIOD AND WHAT HAPPENS AFTER]", rows["en"].text)
        self.assertNotIn("public demo", rows["en"].text)

    def test_unset_settings_leave_their_placeholders_and_the_phone_goes(self):
        # An officer without an email is not enough to fill the officer line.
        rows = self._seed(self.PROJECT, **{**EMPTY, "PUBLIC_GRIEVANCE_OFFICER": "Dr A B"})
        for language, row in rows.items():
            self.assertEqual(row.text, SEED_TEXT[language].replace("[PROJECT NAME]", "Fill CNF01")
                             .replace(", [PHONE]", "").replace(", [फ़ोन]", ""))
            self.assertEqual([(p["code"], p["label"]) for p in row.purposes],
                             sorted((p["code"], p["label"]) for p in SEED_PURPOSES[language]))
        self.assertIn("[DATA PROTECTION OFFICER]", rows["en"].text)
        self.assertIn("Deletion or exclusion of your data: [DELETION AND EXCLUSION EMAIL]. Quote", rows["en"].text)
        self.assertIn("[ORGANISATION]", rows["hi"].text)
        self.assertIn("[डेटा मिटाने और बाहर रखने का ईमेल]। आपको", rows["hi"].text)
        for row in rows.values():
            self.assertNotIn("[PHONE]", row.text)
            self.assertNotIn("[फ़ोन]", row.text)
            # "[EMAIL, PHONE]" is not cut by the phone drop.
            self.assertTrue("[EMAIL, PHONE]" in row.text or "[ईमेल, फ़ोन]" in row.text)

    # ── Project Setup: Fill from settings ──────────────────────────────────

    def test_fill_saves_a_new_audited_version_and_leaves_the_old_one(self):
        old = self._seed(self.PROJECT, **EMPTY)
        db.session.commit()
        before = {row.notice_version_id: (row.text, row.text_sha256, row.purposes) for row in old.values()}
        url = f"/api/v1/projects/{self.PROJECT}/consent-notices/fill"
        self._login(self.base_admin_id)
        with patch.dict(self.app.config, self._settings()):
            self.assertEqual(self.client.post(url).status_code, 400)  # no CSRF
            self.assertEqual(len(self._versions(self.PROJECT)), 2)
            response = self.client.post(url, headers=self._csrf_headers())
            self.assertEqual(response.status_code, 201, response.get_json())
            created = response.get_json()["notice_versions"]
            self.assertEqual([(v["version"], v["language"]) for v in created], [(2, "en"), (2, "hi")])
            for version in created:
                self.assertIn("Org X", version["text"])
                self.assertNotIn("[DATA PROTECTION OFFICER]", version["text"])
                self.assertEqual(version["text_sha256"], hashlib.sha256(version["text"].encode()).hexdigest())
                self.assertEqual(version["allowed_modes"], old[version["language"]].allowed_modes)
                self.assertEqual(version["covered_fields"], old[version["language"]].covered_fields)
            # Nothing left to fill: no version, and the reply says so.
            again = self.client.post(url, headers=self._csrf_headers())
            self.assertEqual((again.status_code, again.get_json()["code"]), (409, "conflict"))
            self.assertIn("Nothing to fill", again.get_json()["error"])
        db.session.expire_all()
        self.assertEqual(len(self._versions(self.PROJECT)), 4)
        for notice_version_id, kept in before.items():
            row = db.session.get(MasConsentNoticeVersion, notice_version_id)
            self.assertEqual((row.text, row.text_sha256, row.purposes), kept)
        audited = set(db.session.scalars(sa.select(MapConsentAudit.notice_version_id).where(
            MapConsentAudit.project_id == self.PROJECT, MapConsentAudit.event == "consent_notice_created")))
        self.assertTrue({str(v["notice_version_id"]) for v in created} <= {str(a) for a in audited})

    def test_fill_is_refused_to_an_interviewer_and_without_a_notice(self):
        url = f"/api/v1/projects/{self.PROJECT}/consent-notices/fill"
        self._login(self.base_admin_id)
        response = self.client.post(url, headers=self._csrf_headers())
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "conflict"))
        self._seed(self.PROJECT, **EMPTY)
        db.session.commit()
        self._login(str(self.interviewer.user_id))
        with patch.dict(self.app.config, self._settings()):
            self.assertEqual(self.client.post(url, headers=self._csrf_headers()).status_code, 403)
        self.assertEqual(len(self._versions(self.PROJECT)), 2)
