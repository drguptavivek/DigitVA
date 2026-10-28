"""Minimal refusal receipts for staff authorized to register deaths."""
import hashlib
import json
import uuid

import sqlalchemy as sa

from app import db
from app.models import MasOrgUnit, VaDeathRegister, VaWebIntakeDraft
from app.models.va_web_intake import VaWebIntakeDraftSection
from app.services import case_transition_service as cases
from app.services import consent_service, public_demo_service
from app.services import web_intake_service as intake
from app.services.authz.actions import DEATH_REGISTERING_ROLES

_KEYS = frozenset({"client_draft_id", "project_id", "site_id", "org_unit_id", "refusal_age_group", "refusal_sex", "who_consent", "consent"})
_AGES = frozenset({"neonate", "child", "15_49y", "50_64y", "65_plus", "unknown"})
_SEXES = frozenset({"male", "female", "unknown"})


def record(user, body, project_id, site_id, channel):
    if set(body) - _KEYS:
        raise intake.WebIntakeError("Unexpected refusal fields.", 400)
    try:
        client_id = uuid.UUID(str(body.get("client_draft_id")))
    except (ValueError, TypeError, AttributeError):
        raise intake.WebIntakeError("client_draft_id must be a UUID.", 400) from None
    age, sex, who, consent = (body.get(k) for k in ("refusal_age_group", "refusal_sex", "who_consent", "consent"))
    if (age is not None and (not isinstance(age, str) or age not in _AGES)) or (sex is not None and (not isinstance(sex, str) or sex not in _SEXES)):
        raise intake.WebIntakeError("Invalid refusal profile.", 400)
    if who not in (None, "no") or (who is None and not (isinstance(consent, dict) and consent.get("decision") == "refused")):
        raise intake.WebIntakeError("A refusal decision is required.", 400)
    unit_id = body.get("org_unit_id") or public_demo_service.default_org_unit_id(project_id)
    if not intake._mode_allows(intake.get_web_intake_mode(project_id), death_register=True):
        raise intake.WebIntakeError("This project does not use the death register.", 403)
    intake._require_scope(user, project_id, site_id, unit_id, DEATH_REGISTERING_ROLES)
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    existing = db.session.scalar(sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.client_draft_id == client_id))
    if existing is not None:
        if existing.user_id != user.user_id or existing.meta.get("registration_refusal_sha256") != fingerprint:
            raise intake.WebIntakeError("That client_draft_id is already in use.", 409)
        return False
    public_demo_service.check_new_registration(user, project_id)
    public_demo_service.check_new_draft(user, project_id)
    form = intake.ensure_web_runtime_form(project_id, site_id)
    resolved_unit = uuid.UUID(str(unit_id)) if unit_id else None
    unit = db.session.get(MasOrgUnit, resolved_unit) if resolved_unit else None
    number, unique_id = intake._allocate_unique_id(unit.unit_code if unit else site_id)
    death = cases.open_case(VaDeathRegister(project_id=project_id, site_id=site_id, org_unit_id=resolved_unit,
        death_number=number, unique_id=unique_id, source="direct", registered_by=user.user_id,
        started_by_user_id=user.user_id), actor=user)
    draft = VaWebIntakeDraft(project_id=project_id, site_id=site_id, org_unit_id=resolved_unit,
        death_id=death.death_id, form_id=form.form_id, user_id=user.user_id, unique_id=unique_id,
        client_draft_id=client_id, meta={"registration_refusal_sha256": fingerprint}, prefill={})
    answers = {k: v for k, v in (("refusal_age_group", age), ("refusal_sex", sex), ("Id10013", who)) if v is not None}
    draft.sections.append(VaWebIntakeDraftSection(section_name=intake.DEVICE_SECTION, data=answers))
    db.session.add(draft)
    if consent is not None:
        consent_service.record_consent(user, project_id=project_id, death=death, consent=consent,
            client_draft_id=None, channel=channel)
    db.session.flush()
    return True
