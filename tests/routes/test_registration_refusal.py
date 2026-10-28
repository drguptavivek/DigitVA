"""Registration-only refusal receipts and their authorization boundary."""
import uuid

import sqlalchemy as sa

from app import db
from app.models import VaConsentRecord, VaDeathRegister, VaWebIntakeDraft
from tests.routes.test_consent_api import INTAKE, ConsentApiTests
from tests.routes.test_death_reporter import API, PROJECT, SITE, DeathReporterTests


class RegistrationRefusalTests(DeathReporterTests):
    def test_refusal_receipt_is_minimal_idempotent_and_within_register_scope(self):
        self._login(str(self.reporter.user_id))
        body = {"project_id": PROJECT, "site_id": SITE, "org_unit_id": str(self.sca.org_unit_id),
                "client_draft_id": str(uuid.uuid4()), "refusal_age_group": "65_plus",
                "refusal_sex": "female", "who_consent": "no"}
        def post(payload):
            return self.client.post(API + "/refusals", json=payload, headers=self._csrf_headers())
        response = post(body)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json(), {"client_draft_id": body["client_draft_id"]})
        draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.client_draft_id == uuid.UUID(body["client_draft_id"])))
        self.assertIsNotNone(draft)
        death = db.session.get(VaDeathRegister, draft.death_id)
        self.assertEqual(death.status, "draft_identity")
        self.assertIsNone(death.deceased_name)
        self.assertEqual(draft.prefill, {})
        self.assertEqual(draft.sections[0].data, {"Id10013": "no", "refusal_age_group": "65_plus", "refusal_sex": "female"})
        self.assertEqual(post(body).status_code, 200)
        self.assertEqual(post({**body, "refusal_sex": "male"}).status_code, 409)
        self.assertEqual(post({**body, "deceased_name": "Must not persist"}).status_code, 400)
        self.assertEqual(post({**body, "client_draft_id": str(uuid.uuid4()), "org_unit_id": str(self.scb.org_unit_id)}).status_code, 403)
        self.assertEqual(self.client.get(f"{API}/drafts/{draft.draft_id}").status_code, 403)


class RegistrationRefusalConsentTests(ConsentApiTests):
    def test_data_protection_refusal_does_not_invent_who_answer(self):
        body = {"project_id": self.REQUIRED, "site_id": self.SITE_REQ,
                "client_draft_id": str(uuid.uuid4()), "refusal_sex": "unknown",
                "consent": self._consent(decision="refused")}
        def post(payload):
            return self.client.post(INTAKE + "/refusals", json=payload, headers=self._csrf_headers())
        response = post(body)
        self.assertEqual(response.status_code, 201, response.get_json())
        draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.client_draft_id == uuid.UUID(body["client_draft_id"])))
        self.assertIsNotNone(draft)
        self.assertEqual(draft.sections[0].data, {"refusal_sex": "unknown"})
        consent = db.session.scalar(sa.select(VaConsentRecord).where(VaConsentRecord.death_id == draft.death_id))
        self.assertIsNotNone(consent)
        self.assertEqual(consent.event, "refused")
        self.assertIsNone(consent.client_draft_id)
        self.assertEqual(post(body).status_code, 200)
        self.assertEqual(post({**body, "client_draft_id": str(uuid.uuid4()), "consent": self._consent()}).status_code, 400)
