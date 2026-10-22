"""Shared fixture for the Training & demo project tests: a fake source form of 205
consented submissions (names, addresses, identifiers, a narrative, three
attachments) and a TRN01 project with one session created from it."""

import os
import tempfile
import uuid
from datetime import datetime
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    MapTrainingCase,
    MasLanguages,
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaForms,
    VaStatuses,
    VaSubmissionAttachments,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import training_demo_service as svc
from app.services.attachment_service import generate_storage_name
from app.services.coder_workflow_service import get_pick_available_forms
from app.services.submission_payload_version_service import write_payload_version
from tests.base import BaseTestCase

SRC_FORM = "TRNSRC000001"
SOURCE_COUNT = 205  # more than 200: the extras must be left out
FIRST = ("Ramesh", "Sunita", "Gopal", "Meena", "Imran")


def source_payload(i: int) -> dict:
    first = FIRST[i % len(FIRST)]
    last = "Kumarasamy"
    return {
        "sid": f"src-{i:03d}",
        "form_def": SRC_FORM,
        "SubmissionDate": "2024-05-01T10:00:00.000Z",
        "updatedAt": "2024-05-02T10:00:00.000Z",
        "SubmitterName": "Real Interviewer",
        "SubmitterID": "real-submitter-id",
        "DeviceID": "real-device-id",
        "death_register_id": "DR-REAL-1",
        "unique_id": f"UNSW-{i:03d}",
        "unique_id2": f"MASK-{i:03d}",
        "instanceName": f"inst-{i}",
        "Id10013": "yes",
        "Id10019": "female",
        "ageInYears": "55",
        "isAdult": "1",
        "Id10017": first,
        "Id10018": last,
        "Id10007": f"{first} {last}",
        "Id10061": f"Gopal {last}",
        "Id10055": f"{i} Temple Road, Kalpet",
        "Id10070": f"REG-{i:05d}",
        "Id10073": {"last3": "482", "present": True},
        "Id10010c": f"EMP{i:04d}",
        "Id10476": f"{first} {last} had a cough. He lived at {i} Temple Road, Kalpet.",
        "Id10099": "Chest pain for two weeks",
        "narr_language": "english",
        "org_district_code": "REAL_DISTRICT",
        "narrative_image": f"img_{i}.jpg",
    }


class TrainingDemoTestBase(BaseTestCase):
    split = False  # PAYLOAD_PII_SPLIT_ENABLED for the class

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._split = mock.patch.dict(cls.app.config, PAYLOAD_PII_SPLIT_ENABLED=cls.split)
        cls._split.start()
        cls._ensure_form_type("WHO_2022_VA", "WHO VA 2022")
        cls._ensure_base_research_project_and_site()
        if db.session.get(MasLanguages, "english") is None:
            db.session.add(MasLanguages(language_code="english", language_name="English", is_active=True))
        cls._tmp = tempfile.TemporaryDirectory()
        cls._config = mock.patch.dict(
            cls.app.config, DIGITVA_TRAINING_PROJECT_ID="TRN01", APP_DATA=cls._tmp.name
        )
        cls._config.start()
        cls.admin = cls.base_admin_user
        cls._build_source()
        svc.setup_training_project()
        cls.first = svc.create_training_session("Training one", cls.admin, source_form_id=SRC_FORM)
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        cls._config.stop()
        cls._split.stop()
        cls._tmp.cleanup()
        super().tearDownClass()

    @classmethod
    def _build_source(cls):
        form_type = cls._ensure_form_type("WHO_2022_VA")
        db.session.add(
            VaForms(
                form_id=SRC_FORM, project_id=cls.BASE_PROJECT_ID, site_id=cls.BASE_SITE_ID,
                odk_form_id="src", odk_project_id="1", form_type="WHO VA 2022",
                form_type_id=form_type.form_type_id, form_source="odk", form_status=VaStatuses.active,
            )
        )
        db.session.flush()
        cls.source_sids = []
        for i in range(SOURCE_COUNT):
            sid = f"src-{i:03d}"
            consent = "no" if i == 0 else "yes"  # case 0 is refused and must be skipped
            payload = source_payload(i)
            payload["Id10013"] = consent
            sub = VaSubmissions(
                va_sid=sid, va_form_id=SRC_FORM, va_data_collector="Real Interviewer",
                va_uniqueid_masked=f"MASK-{i:03d}", va_consent=consent, va_narration_language="english",
                va_deceased_age=55, va_deceased_gender="female", va_catcount={}, va_category_list=[],
                va_submission_date=datetime(2024, 5, 1),
            )
            db.session.add(sub)
            db.session.flush()
            version = VaSubmissionPayloadVersion(va_sid=sid, version_status="active")
            write_payload_version(version, payload, new=True)
            db.session.add(version)
            db.session.flush()
            sub.active_payload_version_id = version.payload_version_id
            cls.source_sids.append(sid)
        # An answer key for one eligible case (source 1 becomes case 1).
        coder = cls.base_coder_user
        final = VaFinalAssessments(va_sid="src-001", va_finassess_by=coder.user_id, va_conclusive_cod="J18.9")
        db.session.add(final)
        db.session.flush()
        db.session.add(VaFinalCodAuthority(va_sid="src-001", authoritative_final_assessment_id=final.va_finassess_id))
        # Attachments of three eligible cases, with real bytes on disk.
        cls.source_bytes = {}
        for i in (1, 2, 3):
            name = generate_storage_name(f"img_{i}.jpg")
            folder = os.path.join(cls._tmp.name, SRC_FORM, "media")
            os.makedirs(folder, exist_ok=True)
            data = f"image-bytes-{i}".encode()
            with open(os.path.join(folder, name), "wb") as handle:
                handle.write(data)
            cls.source_bytes[f"src-{i:03d}"] = data
            db.session.add(
                VaSubmissionAttachments(
                    va_sid=f"src-{i:03d}", filename=f"img_{i}.jpg", storage_name=name,
                    local_path=os.path.join(folder, name), mime_type="image/jpeg",
                    exists_on_odk=True, source_state="available",
                )
            )
        db.session.flush()

    # -- helpers -----------------------------------------------------------
    def _user(self, tag: str, **kwargs) -> VaUsers:
        user = self._make_user(f"{tag}.{uuid.uuid4().hex[:8]}@test.local", "Passw0rd-test-1")
        user.vacode_language = ["english"]
        db.session.flush()
        return user

    def _grants(self, user, status=None):
        stmt = sa.select(VaUserAccessGrants).where(VaUserAccessGrants.user_id == user.user_id)
        if status is not None:
            stmt = stmt.where(VaUserAccessGrants.grant_status == status)
        return db.session.scalars(stmt).all()

    def _session_sids(self, session_id=None) -> dict:
        rows = db.session.execute(
            sa.select(MapTrainingCase.coder_slot, MapTrainingCase.va_sid).where(
                MapTrainingCase.training_session_id == (session_id or self.first["training_session_id"])
            )
        ).all()
        out: dict = {}
        for slot, sid in rows:
            out.setdefault(slot, set()).add(sid)
        return out

    def _trn_form_id(self) -> str:
        return svc._web_form().form_id

    def _pick_list(self, user) -> set:
        return {r["va_sid"] for r in get_pick_available_forms(user, {self._trn_form_id()})}
