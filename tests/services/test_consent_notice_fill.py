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
ONE_YEAR = {
    "en": "We keep your name, phone number, address and identity numbers for 1 year from the interview, "
          "then erase them. The answers about the death are kept permanently without these details.",
    "hi": "हम आपका नाम, फ़ोन नंबर, पता और पहचान नंबर साक्षात्कार से 1 वर्ष तक रखते हैं, फिर उन्हें मिटा देते हैं। "
          "मृत्यु के बारे में उत्तर इन विवरणों के बिना हमेशा रखे जाते हैं।",
}
HEALTH_WORKER = {
    "en": "Your district team: the health worker who visits you will give you their name and phone number.",
    "hi": "आपकी ज़िला टीम: आपसे मिलने आने वाले स्वास्थ्यकर्मी आपको अपना नाम और फ़ोन नंबर बताएँगे।",
}
CENTRAL = {"en": "The mentoring institution: through the central team below.",
           "hi": "मार्गदर्शक संस्थान: नीचे दिए केंद्रीय टीम के माध्यम से।"}
DISTRICT_UNIT_1, DISTRICT_UNIT_2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
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
            self.assertEqual(PLACEHOLDER.findall(row.text), [])
            self.assertIn(CENTRAL[language], row.text)
            self.assertEqual(row.text_sha256, hashlib.sha256(row.text.encode("utf-8")).hexdigest())
            labels = {p["code"]: p["label"] for p in row.purposes}
            self.assertIn("Org X", labels["narrative_automated_processing"])
            self.assertFalse(any(PLACEHOLDER.search(label) for label in labels.values()), labels)
        # The module constants (and so the Collect Plus bundle hash) are untouched.
        self.assertEqual(SEED_PURPOSES, purposes_before)
        self.assertEqual(standalone_bundle_sha256(), bundle_before)

    def test_demo_lines_appear_only_on_the_demo_project(self):
        rows = self._seed(self.PROJECT)
        for language, row in rows.items():
            self.assertIn(ONE_YEAR[language], row.text)
            self.assertIn(HEALTH_WORKER[language], row.text)
            self.assertIn("Org X", row.text)  # the shared fills still apply
            self.assertNotIn("public demo", row.text)
            self.assertNotIn("सार्वजनिक डेमो", row.text)

    def test_demo_retention_promise_waits_for_the_purge_and_the_demo(self):
        # Purge off: the demo's deletion promise would be untrue, so the project's own retention
        # sentence (the default) stands; the district line is still the demo's.
        rows = self._seed(self.DEMO, PUBLIC_DEMO_PURGE_ENABLED=False)
        self.assertIn("Your district team: not applicable in the public demo.", rows["en"].text)
        self.assertIn(ONE_YEAR["en"], rows["en"].text)
        self.assertIn(ONE_YEAR["hi"], rows["hi"].text)
        self.assertNotIn("is deleted 30 days", rows["en"].text)

    def test_demo_lines_need_a_demo_deployment(self):
        # A project that happens to be called PUB01 on a non-demo deployment is an ordinary project.
        rows = self._seed(self.DEMO, PUBLIC_DEMO_ENABLED=False)
        self.assertIn("Org X", rows["en"].text)
        self.assertIn(HEALTH_WORKER["en"], rows["en"].text)
        self.assertIn(ONE_YEAR["en"], rows["en"].text)
        self.assertNotIn("public demo", rows["en"].text)

    def test_unset_settings_leave_their_placeholders_and_the_phone_goes(self):
        # An officer without an email is not enough to fill the officer line.
        rows = self._seed(self.PROJECT, **{**EMPTY, "PUBLIC_GRIEVANCE_OFFICER": "Dr A B"})
        for language, row in rows.items():
            # Only the three digitva-7amd.26 defaults are filled when no PUBLIC_* setting is.
            expected = (SEED_TEXT[language].replace("[PROJECT NAME]", "Fill CNF01")
                        .replace(", [PHONE]", "").replace(", [फ़ोन]", ""))
            for placeholder in ("[RETENTION PERIOD AND WHAT HAPPENS AFTER]", "[रखने की अवधि और उसके बाद क्या होगा]"):
                expected = expected.replace(placeholder, ONE_YEAR[language])
            expected = (expected.replace("[DISTRICT CONTACT NAME, EMAIL, PHONE]", HEALTH_WORKER["en"].split(": ")[1][:-1])
                        .replace("[ज़िला संपर्क का नाम, ईमेल, फ़ोन]", HEALTH_WORKER["hi"].split(": ")[1][:-1])
                        .replace("[INSTITUTION NAME, EMAIL, PHONE]", CENTRAL["en"].split(": ")[1][:-1])
                        .replace("[संस्थान का नाम, ईमेल, फ़ोन]", CENTRAL["hi"].split(": ")[1][:-1]))
            self.assertEqual(row.text, expected)
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

    # ── defaults and settings-built lines (digitva-7amd.26) ────────────────

    def _set(self, project_id, **body):
        consent_service.save_settings(self.base_admin_user, project_id, body)
        db.session.flush()

    def test_a_fresh_project_seeds_without_any_placeholder_and_with_the_one_year_sentence(self):
        rows = self._seed(self.PROJECT)
        for language, row in rows.items():
            self.assertEqual(PLACEHOLDER.findall(row.text), [], language)
            self.assertIn(ONE_YEAR[language], row.text)

    def test_retention_follows_the_projects_period_and_action(self):
        cases = [
            (730, "lock", "2 years from the interview, then lock them so that no one can see them.",
             "2 वर्ष तक रखते हैं, फिर उन्हें लॉक कर देते हैं ताकि कोई उन्हें देख न सके।"),
            (180, "erase", "6 months from the interview, then erase them.", "6 महीने तक रखते हैं, फिर उन्हें मिटा देते हैं।"),
            (30, "erase", "1 month from the interview, then erase them.", "1 महीना तक रखते हैं"),
            (45, "erase", "45 days from the interview, then erase them.", "45 दिन तक रखते हैं"),
            (1, "erase", "1 day from the interview", "1 दिन तक रखते हैं"),
        ]
        for days, action, english, hindi in cases:
            with self.subTest(days=days, action=action):
                self._set(self.PROJECT, retention={"period_days": days, "expiry_action": action})
                rows = self._seed(self.PROJECT)
                self.assertIn(english, rows["en"].text)
                self.assertIn(hindi, rows["hi"].text)
                self.assertNotIn("[", rows["en"].text.split("How long we keep it.")[1].split("\n")[0])
                db.session.execute(sa.delete(MasConsentNoticeVersion).where(
                    MasConsentNoticeVersion.project_id == self.PROJECT))

    def test_one_district_contact_fills_the_district_line_two_or_none_do_not(self):
        person = {"name": "Dr Rao", "email": "rao@example.org", "phone": "99999"}
        self._set(self.PROJECT, contacts={"districts": {DISTRICT_UNIT_1: person}})
        rows = self._seed(self.PROJECT)
        self.assertIn("Your district team: Dr Rao, rao@example.org, 99999.", rows["en"].text)
        self.assertIn("आपकी ज़िला टीम: Dr Rao, rao@example.org, 99999।", rows["hi"].text)
        db.session.execute(sa.delete(MasConsentNoticeVersion).where(MasConsentNoticeVersion.project_id == self.PROJECT))

        # Empty parts drop cleanly.
        self._set(self.PROJECT, contacts={"districts": {DISTRICT_UNIT_1: {"name": "Dr Rao", "phone": "99999"}}})
        rows = self._seed(self.PROJECT)
        self.assertIn("Your district team: Dr Rao, 99999.", rows["en"].text)
        db.session.execute(sa.delete(MasConsentNoticeVersion).where(MasConsentNoticeVersion.project_id == self.PROJECT))

        self._set(self.PROJECT, contacts={"districts": {DISTRICT_UNIT_1: person, DISTRICT_UNIT_2: {"name": "Dr Two"}}})
        rows = self._seed(self.PROJECT)
        self.assertIn(HEALTH_WORKER["en"], rows["en"].text)
        self.assertIn(HEALTH_WORKER["hi"], rows["hi"].text)
        db.session.execute(sa.delete(MasConsentNoticeVersion).where(MasConsentNoticeVersion.project_id == self.PROJECT))

        self._set(self.PROJECT, contacts={"districts": {}})
        self.assertIn(HEALTH_WORKER["en"], self._seed(self.PROJECT)["en"].text)

    def test_the_mentoring_institution_is_the_set_contact_else_the_central_team(self):
        self._set(self.PROJECT, contacts={"mentor_institution": {"name": "AIIMS", "email": "m@example.org"}})
        rows = self._seed(self.PROJECT)
        self.assertIn("The mentoring institution: AIIMS, m@example.org.", rows["en"].text)
        self.assertIn("मार्गदर्शक संस्थान: AIIMS, m@example.org।", rows["hi"].text)
        db.session.execute(sa.delete(MasConsentNoticeVersion).where(MasConsentNoticeVersion.project_id == self.PROJECT))
        self._set(self.PROJECT, contacts={"mentor_institution": {}})
        rows = self._seed(self.PROJECT)
        self.assertIn(CENTRAL["en"], rows["en"].text)
        self.assertIn(CENTRAL["hi"], rows["hi"].text)

    def test_fill_saves_no_version_when_the_seed_already_filled_everything(self):
        self._seed(self.PROJECT)
        with patch.dict(self.app.config, self._settings()):
            with self.assertRaises(consent_service.ConsentError) as caught:
                consent_service.fill_notice_versions(self.base_admin_user, self.PROJECT)
        self.assertEqual(caught.exception.code, "conflict")

    def test_fill_replaces_the_retention_placeholder_of_an_older_notice(self):
        text = SEED_TEXT["en"].replace("[PROJECT NAME]", "Old")
        consent_service.create_notice_version(self.base_admin_user, self.PROJECT, {
            "version": 1, "language": "en", "text": text, "purposes": SEED_PURPOSES["en"],
            "allowed_modes": ["spoken"]})
        db.session.flush()
        self._set(self.PROJECT, retention={"period_days": 730, "expiry_action": "lock"})
        with patch.dict(self.app.config, self._settings(**EMPTY)):
            (row,) = consent_service.fill_notice_versions(self.base_admin_user, self.PROJECT)
        self.assertEqual(row.version, 2)
        self.assertIn("2 years from the interview, then lock them", row.text)
        self.assertNotIn("[RETENTION", row.text)

    def test_a_project_without_settings_reports_the_default_retention(self):
        config = consent_service.get_consent_config("CNF-NONE")
        self.assertEqual(config["retention"], {"period_days": 365, "expiry_action": "erase"})

    def test_a_first_save_creates_the_row_with_the_default_retention(self):
        self._set(self.PROJECT, contacts={"central_team": {"email": "c@example.org"}})
        settings = consent_service.get_settings(self.PROJECT)
        self.assertEqual((settings.retention_period_days, settings.expiry_action), (365, "erase"))
