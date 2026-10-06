"""Web intake attachments (digitva-ej1): ``PUT/GET /api/v1/intake/drafts/<id>/attachments/<id>``
and the link into the submission at submit.

Covers what the route and ``web_intake_attachment_service`` decide: the 25 MB
cap (413, and 411 without a declared length), the type decided from the leading
bytes (415, whatever the extension or Content-Type said), the interviewer scope
of the draft (404 for another's), idempotency by the client's attachment id,
storage through the attachment store with ``exists_on_odk`` true so the
serving token resolves, and the link into the submission (payload filename,
``va_submission_attachments`` row, case released to SmartVA; a referenced file
that was never uploaded refuses the web submit).
"""
import io
import os
import shutil
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaUserAccessGrants,
    VaUsers,
    VaWebIntakeAttachment,
    VaWebIntakeDraft,
    VaWebIntakeDraftSection,
)
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.services import attachment_service
from app.services import web_intake_attachment_service as svc
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from app.services.workflow.state_store import get_submission_workflow_state
from tests.base import BaseTestCase

# Leading bytes of each accepted type, padded the way a real file would be.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60
PDF = b"%PDF-1.4\n" + b"0" * 60
WEBM = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01\x42\xf2\x81\x04\x42\xf3\x81\x08\x42\x82\x84webm" + b"\x00" * 40
WAV = b"RIFF\x24\x08\x00\x00WAVEfmt " + b"\x00" * 60
AMR = b"#!AMR\n" + b"\x00" * 60
MP3_ID3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 60
MP3_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 60
M4A = b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00" + b"\x00" * 60
EXE = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 60


class DetectTypeTests(BaseTestCase):
    """The accepted list, decided from bytes alone (pure; no request)."""

    def test_each_accepted_type_is_recognised_from_its_leading_bytes(self):
        for head, expected in (
            (JPEG, ("image/jpeg", ".jpg")),
            (PNG, ("image/png", ".png")),
            (PDF, ("application/pdf", ".pdf")),
            (WEBM, ("audio/webm", ".webm")),
            (WAV, ("audio/wav", ".wav")),
            (AMR, ("audio/amr", ".amr")),
            (MP3_ID3, ("audio/mpeg", ".mp3")),
            (MP3_FRAME, ("audio/mpeg", ".mp3")),
            (M4A, ("audio/mp4", ".m4a")),
        ):
            self.assertEqual(svc.detect_type(head), expected, head[:12])

    def test_everything_else_is_refused(self):
        for head in (
            EXE,
            b"<svg xmlns='http://www.w3.org/2000/svg'/>",
            b"GIF89a" + b"\x00" * 20,
            b"\xff\xf1\x50\x80" + b"\x00" * 20,  # AAC ADTS: a frame sync, but not MPEG audio layer
            b"\x00\x00\x00\x18ftypqt  " + b"\x00" * 20,  # a QuickTime brand, not audio
            b"\x1a\x45\xdf\xa3" + b"\x00" * 30 + b"matroska",  # EBML but not webm
            b"",
        ):
            self.assertIsNone(svc.detect_type(head), head[:12])


class IntakeAttachmentTests(BaseTestCase):
    PROJECT_ID = "WIA02"
    SITE_ID = "WA02"
    ODK_FORM_ID = "WIA02WA0201"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID, project_code=cls.PROJECT_ID, project_name="Intake Attachment Project",
            project_nickname="IntakeAtt", project_status=VaStatuses.active, project_registered_at=now,
            project_updated_at=now, web_intake_mode="both",
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID, site_name="Intake Attachment Site", site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT_ID, site_id=cls.SITE_ID, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(cls.PROJECT_ID, cls.SITE_ID)
        db.session.add(VaForms(
            form_id=cls.ODK_FORM_ID, project_id=cls.PROJECT_ID, site_id=cls.SITE_ID, odk_form_id="ODK_INTAKE_ATT",
            odk_project_id="8", form_type="WHO VA 2022", form_source="odk", form_status=VaStatuses.active,
            form_registered_at=now, form_updated_at=now,
        ))
        db.session.flush()
        cls.users = []
        for email in ("att.interviewer@test.local", "att.other@test.local"):
            user = cls._get_or_make_user(email, "IntakeAtt123")
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.interviewer, scope_type=VaAccessScopeTypes.project,
                project_id=cls.PROJECT_ID, notes="intake attachment test grant", grant_status=VaStatuses.active,
            ))
            cls.users.append(str(user.user_id))
        db.session.commit()
        cls.interviewer_id, cls.other_id = cls.users

    def setUp(self):
        super().setUp()
        # The store writes under APP_DATA; keep the test's files out of the tree.
        data_dir = tempfile.mkdtemp(prefix="digitva-att-")
        previous = self.app.config["APP_DATA"]
        self.app.config["APP_DATA"] = data_dir
        self.addCleanup(lambda: self.app.config.__setitem__("APP_DATA", previous))
        self.addCleanup(shutil.rmtree, data_dir, True)
        self.data_dir = data_dir

    # ── helpers ────────────────────────────────────────────────────────────

    def _start_draft(self):
        response = self.client.post(
            "/api/v1/intake/drafts",
            json={"project_id": self.PROJECT_ID, "site_id": self.SITE_ID},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["draft"]

    def _put(self, draft_id, cid, body, **kwargs):
        headers = {"Content-Type": "application/octet-stream", **self._csrf_headers(), **kwargs.pop("headers", {})}
        return self.client.put(
            f"/api/v1/intake/drafts/{draft_id}/attachments/{cid}", data=body, headers=headers, **kwargs
        )

    def _stored_files(self):
        found = []
        for root, _dirs, files in os.walk(self.data_dir):
            found.extend(os.path.join(root, name) for name in files if not name.startswith(".tmp_"))
        return found

    def _reference(self, cid, mime="audio/webm"):
        return {"id": str(cid), "uri": f"who-va-attachment:{cid}", "name": f"{cid}.webm",
                "originalName": f"{cid}.webm", "mimeType": mime, "size": 100, "durationMs": 1000, "processed": True}

    def _complete_data(self, **extra):
        return {
            "Id10013": "yes", "Id10017": "Bina", "Id10018": "Sahu", "Id10019": "female",
            "Id10023": (date.today() - timedelta(days=5)).isoformat(),
            "finalAgeInYears": "71", "narr_language": "english", **extra,
        }

    def _submit(self, draft_id, data):
        return self.client.post(
            f"/api/v1/intake/drafts/{draft_id}/submit",
            json={"completion": {"valid": True, "issues": [], "data": data}},
            headers=self._csrf_headers(),
        )

    # ── upload ─────────────────────────────────────────────────────────────

    def test_upload_stores_the_file_and_a_retry_returns_the_same_record(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        cid = uuid.uuid4()

        first = self._put(draft["draft_id"], cid, WEBM)
        self.assertEqual(first.status_code, 201, first.get_json())
        body = first.get_json()
        self.assertTrue(body["created"])
        self.assertEqual(body["attachment"]["id"], str(cid))
        self.assertEqual(body["attachment"]["filename"], f"{cid}.webm")
        self.assertEqual(body["attachment"]["mime_type"], "audio/webm")
        self.assertEqual(body["attachment"]["size"], len(WEBM))
        row = db.session.get(VaWebIntakeAttachment, (uuid.UUID(draft["draft_id"]), cid))
        self.assertEqual(row.store_state, "local")
        self.assertEqual(row.size_bytes, len(WEBM))
        self.assertRegex(row.storage_name, r"^[a-f0-9]{32}\.webm$")
        self.assertEqual(len(self._stored_files()), 1)
        storage_name = row.storage_name

        again = self._put(draft["draft_id"], cid, WEBM)
        self.assertEqual(again.status_code, 200, again.get_json())
        self.assertFalse(again.get_json()["created"])
        self.assertEqual(again.get_json()["attachment"], body["attachment"])
        self.assertEqual(
            db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeAttachment)
                              .where(VaWebIntakeAttachment.draft_id == uuid.UUID(draft["draft_id"]))), 1)
        self.assertEqual(len(self._stored_files()), 1)
        self.assertEqual(db.session.get(VaWebIntakeAttachment, (uuid.UUID(draft["draft_id"]), cid)).storage_name, storage_name)

        different = self._put(draft["draft_id"], cid, WEBM + b"more")
        self.assertEqual(different.status_code, 409)
        self.assertEqual(different.get_json()["code"], "attachment_id_conflict")

    def test_a_concurrent_identical_upload_that_lost_the_race_is_cleaned_up(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        cid = uuid.uuid4()
        self.assertEqual(self._put(draft["draft_id"], cid, PDF).status_code, 201)
        self.assertEqual(len(self._stored_files()), 1)
        row = db.session.get(VaWebIntakeAttachment, (uuid.UUID(draft["draft_id"]), cid))
        winner_storage_name = row.storage_name
        # Another process's row is not in this session's identity map.
        db.session.expunge(row)

        # The loser saw no row when it started; the winner's row is there when
        # it inserts. It returns the winner's row and removes its own object.
        real = svc.get_upload
        calls = []

        def racing(draft_id, client_id):
            calls.append(1)
            return None if len(calls) == 1 else real(draft_id, client_id)

        draft_row = db.session.get(VaWebIntakeDraft, uuid.UUID(draft["draft_id"]))
        with patch.object(svc, "get_upload", racing):
            result, created = svc.store_upload(draft_row, cid, io.BytesIO(PDF), len(PDF))
        self.assertFalse(created)
        self.assertEqual(result.storage_name, winner_storage_name)
        self.assertEqual(len(self._stored_files()), 1)

    def test_the_cap_is_25_mb_and_the_length_must_be_declared(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        over = svc.MAX_BYTES + 1
        refused = self._put(draft["draft_id"], uuid.uuid4(), JPEG, environ_overrides={"CONTENT_LENGTH": str(over)})
        self.assertEqual(refused.status_code, 413)
        self.assertEqual(refused.get_json()["code"], "payload_too_large")

        undeclared = self.client.put(
            f"/api/v1/intake/drafts/{draft['draft_id']}/attachments/{uuid.uuid4()}",
            input_stream=io.BytesIO(JPEG),
            headers={"Content-Type": "application/octet-stream", **self._csrf_headers()},
            environ_overrides={"CONTENT_LENGTH": None},
        )
        self.assertEqual(undeclared.status_code, 411)
        self.assertEqual(undeclared.get_json()["code"], "length_required")

        empty = self._put(draft["draft_id"], uuid.uuid4(), b"", environ_overrides={"CONTENT_LENGTH": "0"})
        self.assertEqual(empty.status_code, 422)
        self.assertEqual(empty.get_json()["code"], "empty_attachment")
        self.assertEqual(self._stored_files(), [])

        # A body the service itself measures too: more than it was declared to
        # hold is refused whole, nothing stored.
        with patch.object(svc, "MAX_BYTES", 100):
            big = self._put(draft["draft_id"], uuid.uuid4(), JPEG + b"x" * 100)
        self.assertEqual(big.status_code, 413)
        self.assertEqual(self._stored_files(), [])

    def test_the_type_comes_from_the_bytes_not_the_name_or_content_type(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        refused = self._put(draft["draft_id"], uuid.uuid4(), EXE, headers={"Content-Type": "image/jpeg"})
        self.assertEqual(refused.status_code, 415)
        self.assertEqual(refused.get_json()["code"], "unsupported_media_type")
        self.assertEqual(self._stored_files(), [])
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeAttachment)), 0)

        # A PNG sent as audio is stored as the PNG it is.
        cid = uuid.uuid4()
        accepted = self._put(draft["draft_id"], cid, PNG, headers={"Content-Type": "audio/webm"})
        self.assertEqual(accepted.status_code, 201, accepted.get_json())
        self.assertEqual(accepted.get_json()["attachment"]["mime_type"], "image/png")
        self.assertEqual(accepted.get_json()["attachment"]["filename"], f"{cid}.png")

    def test_another_interviewers_draft_is_not_found_and_a_closed_draft_is_a_conflict(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        cid = uuid.uuid4()
        self.assertEqual(self._put(draft["draft_id"], cid, JPEG).status_code, 201)

        self._login(self.other_id)
        self.assertEqual(self._put(draft["draft_id"], uuid.uuid4(), JPEG).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/intake/drafts/{draft['draft_id']}/attachments/{cid}").status_code, 404)
        self.assertEqual(self._put(uuid.uuid4(), uuid.uuid4(), JPEG).status_code, 404)

        self._login(self.interviewer_id)
        self.assertEqual(self._put(draft["draft_id"], "not-a-uuid", JPEG).status_code, 400)
        discarded = self.client.post(f"/api/v1/intake/drafts/{draft['draft_id']}/discard", headers=self._csrf_headers())
        self.assertEqual(discarded.status_code, 200)
        self.assertEqual(self._put(draft["draft_id"], uuid.uuid4(), JPEG).status_code, 409)

    def test_upload_needs_the_csrf_header(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        response = self.client.put(
            f"/api/v1/intake/drafts/{draft['draft_id']}/attachments/{uuid.uuid4()}",
            data=JPEG, headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._stored_files(), [])

    def test_a_draft_holds_a_bounded_number_of_files(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        with patch.object(svc, "MAX_PER_DRAFT", 2):
            self.assertEqual(self._put(draft["draft_id"], uuid.uuid4(), JPEG).status_code, 201)
            self.assertEqual(self._put(draft["draft_id"], uuid.uuid4(), PNG).status_code, 201)
            third = self._put(draft["draft_id"], uuid.uuid4(), PDF)
        self.assertEqual(third.status_code, 422)
        self.assertEqual(third.get_json()["code"], "attachment_limit")

    def test_the_owner_reads_the_file_back_with_no_store(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        cid = uuid.uuid4()
        self.assertEqual(self._put(draft["draft_id"], cid, WEBM).status_code, 201)
        response = self.client.get(f"/api/v1/intake/drafts/{draft['draft_id']}/attachments/{cid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, WEBM)
        self.assertEqual(response.headers["Content-Type"], "audio/webm")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.client.get(f"/api/v1/intake/drafts/{draft['draft_id']}/attachments/{uuid.uuid4()}").status_code, 404)
        # The read left no record-cache entry that could shadow the token's
        # owner once the file is linked to a submission.
        row = db.session.get(VaWebIntakeAttachment, (uuid.UUID(draft["draft_id"]), cid))
        from app import cache as flask_cache
        self.assertIsNone(flask_cache.get(f"att:{row.storage_name}"))

    # ── submit ─────────────────────────────────────────────────────────────

    def test_submit_links_the_uploaded_file_to_the_submission_and_releases_the_case(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        cid = uuid.uuid4()
        self.assertEqual(self._put(draft["draft_id"], cid, WEBM).status_code, 201)
        pending = db.session.get(VaWebIntakeAttachment, (uuid.UUID(draft["draft_id"]), cid))

        submitted = self._submit(draft["draft_id"], self._complete_data(Id10476_audio=self._reference(cid)))
        self.assertEqual(submitted.status_code, 201, submitted.get_json())
        va_sid = submitted.get_json()["va_sid"]

        version = db.session.scalar(sa.select(VaSubmissionPayloadVersion).where(VaSubmissionPayloadVersion.va_sid == va_sid))
        self.assertEqual(version.payload_data["Id10476_audio"], f"{cid}.webm")
        self.assertEqual(version.payload_data["AttachmentsExpected"], 1)
        self.assertEqual(version.payload_data["AttachmentsPresent"], 1)
        linked = db.session.get(VaSubmissionAttachments, (va_sid, f"{cid}.webm"))
        self.assertTrue(linked.exists_on_odk)
        self.assertEqual(linked.storage_name, pending.storage_name)
        self.assertEqual(linked.store_state, "local")
        self.assertEqual(linked.source_state, "available")
        self.assertEqual(linked.mime_type, "audio/webm")
        # The serving token resolves to the new submission, and the renderer
        # finds the URL from the payload's filename.
        record = attachment_service.resolve_attachment_record(pending.storage_name)
        self.assertIsNotNone(record)
        self.assertEqual(record.va_sid, va_sid)
        from app.utils.va_render.va_render_06_processcategorydata import _resolve_attachment_url
        with self.app.test_request_context("/"):
            url = _resolve_attachment_url(va_sid, record.va_form_id, f"{cid}.webm")
        self.assertEqual(url, f"/api/v1/attachments/{pending.storage_name}")
        # Nothing is waiting on attachments: the case moved on to SmartVA.
        self.assertEqual(get_submission_workflow_state(va_sid), "smartva_pending")
        # The bytes are still the one stored object.
        self.assertEqual(len(self._stored_files()), 1)

    def test_a_web_submit_naming_a_file_never_uploaded_is_refused_and_stores_nothing(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        missing = uuid.uuid4()
        refused = self._submit(draft["draft_id"], self._complete_data(Id10476_audio=self._reference(missing)))
        self.assertEqual(refused.status_code, 409, refused.get_json())
        self.assertEqual(refused.get_json()["code"], "attachments_pending")
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaSubmissions)
                                           .where(VaSubmissions.va_sid.like(f"web-{draft['draft_id']}%"))), 0)
        self.assertEqual(db.session.get(VaWebIntakeDraft, uuid.UUID(draft["draft_id"])).status, "draft")

        # Uploaded now, the same submit goes through.
        self.assertEqual(self._put(draft["draft_id"], missing, WEBM).status_code, 201)
        ok = self._submit(draft["draft_id"], self._complete_data(Id10476_audio=self._reference(missing)))
        self.assertEqual(ok.status_code, 201, ok.get_json())

    def test_another_drafts_file_is_not_linked(self):
        self._login(self.interviewer_id)
        first = self._start_draft()
        cid = uuid.uuid4()
        self.assertEqual(self._put(first["draft_id"], cid, WEBM).status_code, 201)
        # A second open draft of the same interviewer (a direct start) naming
        # the first draft's file: it is not that draft's, so it is not held.
        second = self._start_draft()
        refused = self._submit(second["draft_id"], self._complete_data(Id10476_audio=self._reference(cid)))
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.get_json()["code"], "attachments_pending")

    def test_build_web_payload_reads_the_files_of_the_draft_it_is_told_to(self):
        """A supervisor's choice builds the winner's submission from the
        candidate's answers: the candidate's files are the ones held."""
        from app.services import web_intake_service as intake_svc

        self._login(self.interviewer_id)
        owner = self._start_draft()
        cid = uuid.uuid4()
        self.assertEqual(self._put(owner["draft_id"], cid, PNG).status_code, 201)
        self._login(self.other_id)
        other = self._start_draft()
        owner_row = db.session.get(VaWebIntakeDraft, uuid.UUID(owner["draft_id"]))
        other_row = db.session.get(VaWebIntakeDraft, uuid.UUID(other["draft_id"]))
        user = db.session.get(VaUsers, owner_row.user_id)
        data = {"Id10013": "yes", "imagenarr": self._reference(cid, "image/jpeg")}

        own, own_refs = intake_svc.build_web_payload(
            owner_row, data, user, submitted_at=datetime.now(timezone.utc))
        self.assertEqual(own["imagenarr"], f"{cid}.png")
        self.assertEqual(own_refs, {})
        self.assertEqual((own["AttachmentsExpected"], own["AttachmentsPresent"]), (1, 1))

        other_payload, other_refs = intake_svc.build_web_payload(
            other_row, data, user, submitted_at=datetime.now(timezone.utc))
        self.assertIsNone(other_payload["imagenarr"])
        self.assertEqual(list(other_refs), ["imagenarr"])
        self.assertEqual((other_payload["AttachmentsExpected"], other_payload["AttachmentsPresent"]), (1, 0))

        chosen, chosen_refs = intake_svc.build_web_payload(
            other_row, data, user, submitted_at=datetime.now(timezone.utc), attachments_from=owner_row)
        self.assertEqual(chosen["imagenarr"], f"{cid}.png")
        self.assertEqual(chosen_refs, {})

    # ── review fixes ───────────────────────────────────────────────────────

    def test_an_amr_recording_is_capped_at_5_mb(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        with patch.object(svc, "AMR_MAX_BYTES", 40):
            refused = self._put(draft["draft_id"], uuid.uuid4(), AMR)
        self.assertEqual(refused.status_code, 413)
        self.assertEqual(refused.get_json()["code"], "payload_too_large")
        self.assertIn("5 MB", refused.get_json()["error"])
        self.assertEqual(self._stored_files(), [])

    def test_a_failed_conversion_is_422_and_leaves_no_file(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        with patch.object(attachment_service, "_convert_amr_to_mp3", side_effect=attachment_service.AmrConversionError("x")):
            refused = self._put(draft["draft_id"], uuid.uuid4(), AMR)
        self.assertEqual(refused.status_code, 422)
        self.assertEqual(refused.get_json()["code"], "audio_conversion_failed")
        self.assertEqual(self._stored_files(), [])
        media = os.path.join(self.data_dir, self.ODK_FORM_ID, "media")
        self.assertEqual(os.listdir(media) if os.path.isdir(media) else [], [], "temp files are cleaned")

    def test_a_sox_call_that_times_out_is_a_failed_conversion(self):
        import subprocess

        path = os.path.join(self.data_dir, "in.amr")
        with open(path, "wb") as handle:
            handle.write(AMR)
        out = os.path.join(self.data_dir, "out.mp3")

        def hung(*args, **kwargs):
            self.assertEqual(kwargs["timeout"], attachment_service.SOX_TIMEOUT_SECONDS)
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

        with patch("subprocess.run", hung), patch("subprocess.check_output", hung):
            with self.assertRaises(attachment_service.AmrConversionError):
                attachment_service._convert_amr_to_mp3(path, "F", output_path=out)
        self.assertFalse(os.path.exists(out))
        self.assertEqual(attachment_service.SOX_TIMEOUT_SECONDS, 60)

    def test_the_uploaders_file_name_is_never_stored(self):
        import json

        self._login(self.interviewer_id)
        draft = self._start_draft()
        cid = uuid.uuid4()
        self.assertEqual(self._put(draft["draft_id"], cid, PDF).status_code, 201)
        reference = {**self._reference(cid, "application/pdf"), "name": "ramesh_kumar_death_cert.pdf",
                     "originalName": "ramesh_kumar_death_cert.pdf"}
        saved = self.client.patch(
            f"/api/v1/intake/drafts/{draft['draft_id']}",
            json={"sections": {"documents": {"md_im1": reference}}, "current_section": "documents",
                  "meta": {"schemaVersion": 1, "formVersion": "2022"}},
            headers=self._csrf_headers(),
        )
        self.assertEqual(saved.status_code, 200, saved.get_json())
        fetched = self.client.get(f"/api/v1/intake/drafts/{draft['draft_id']}")
        self.assertNotIn("ramesh", json.dumps(fetched.get_json()))
        stored = fetched.get_json()["envelope"]["data"]["md_im1"]
        self.assertEqual(stored["id"], str(cid))  # the reference itself is intact
        self.assertNotIn("originalName", stored)
        rows = db.session.scalars(sa.select(VaWebIntakeDraftSection).where(
            VaWebIntakeDraftSection.draft_id == uuid.UUID(draft["draft_id"]))).all()
        self.assertTrue(rows)
        self.assertNotIn("ramesh", json.dumps([r.data for r in rows]))

        # And the final section a submit writes.
        submitted = self._submit(draft["draft_id"], self._complete_data(md_im1=reference))
        self.assertEqual(submitted.status_code, 201, submitted.get_json())
        rows = db.session.scalars(sa.select(VaWebIntakeDraftSection).where(
            VaWebIntakeDraftSection.draft_id == uuid.UUID(draft["draft_id"]))).all()
        self.assertNotIn("ramesh", json.dumps([r.data for r in rows]))
        self.assertIn(str(cid), json.dumps([r.data for r in rows]))

    def test_the_file_is_served_inert(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        pdf_id, webm_id = uuid.uuid4(), uuid.uuid4()
        self.assertEqual(self._put(draft["draft_id"], pdf_id, PDF).status_code, 201)
        self.assertEqual(self._put(draft["draft_id"], webm_id, WEBM).status_code, 201)
        pdf = self.client.get(f"/api/v1/intake/drafts/{draft['draft_id']}/attachments/{pdf_id}")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.headers["Content-Security-Policy"].replace(" ;", ";"), "sandbox; default-src 'none'")
        self.assertEqual(pdf.headers["Content-Disposition"], f'attachment; filename="{pdf_id}.pdf"')
        audio = self.client.get(f"/api/v1/intake/drafts/{draft['draft_id']}/attachments/{webm_id}")
        self.assertEqual(audio.headers["Content-Security-Policy"].replace(" ;", ";"), "sandbox; default-src 'none'")
        self.assertNotIn("attachment", audio.headers.get("Content-Disposition", ""))
        self.assertEqual(audio.headers["X-Content-Type-Options"], "nosniff")

    def test_discarding_a_draft_deletes_its_uploaded_files_and_objects(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        for body in (JPEG, WEBM):
            self.assertEqual(self._put(draft["draft_id"], uuid.uuid4(), body).status_code, 201)
        self.assertEqual(len(self._stored_files()), 2)
        discarded = self.client.post(f"/api/v1/intake/drafts/{draft['draft_id']}/discard", headers=self._csrf_headers())
        self.assertEqual(discarded.status_code, 200)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeAttachment)
                                           .where(VaWebIntakeAttachment.draft_id == uuid.UUID(draft["draft_id"]))), 0)
        self.assertEqual(self._stored_files(), [])
        from app.models import MapCaseTransition
        actions = db.session.scalars(sa.select(MapCaseTransition.action).where(
            MapCaseTransition.death_id == uuid.UUID(draft["death_id"]))).all()
        self.assertIn("draft_attachments_deleted", actions)

    def test_a_file_linked_to_a_submission_is_not_deleted_by_cleanup(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        cid = uuid.uuid4()
        self.assertEqual(self._put(draft["draft_id"], cid, WEBM).status_code, 201)
        self.assertEqual(self._submit(draft["draft_id"], self._complete_data(Id10476_audio=self._reference(cid))).status_code, 201)
        draft_row = db.session.get(VaWebIntakeDraft, uuid.UUID(draft["draft_id"]))
        self.assertEqual(svc.delete_draft_uploads(draft_row), 1)  # the pending row goes ...
        self.assertEqual(len(self._stored_files()), 1)  # ... the object a submission holds stays

    def test_the_per_draft_cap_is_rechecked_under_the_draft_lock(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        counts = iter([0, svc.MAX_PER_DRAFT])  # the early check sees room; a parallel upload filled it
        with patch.object(svc, "_held_count", lambda _id: next(counts)):
            refused = self._put(draft["draft_id"], uuid.uuid4(), JPEG)
        self.assertEqual(refused.status_code, 422)
        self.assertEqual(refused.get_json()["code"], "attachment_limit")
        self.assertEqual(self._stored_files(), [])

    def test_a_client_checksum_guards_the_body_and_a_retried_id(self):
        import hashlib

        self._login(self.interviewer_id)
        draft = self._start_draft()
        cid = uuid.uuid4()
        sha = hashlib.sha256(PNG).hexdigest()
        wrong = self._put(draft["draft_id"], cid, PNG, headers={"X-Content-SHA256": "0" * 64})
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(wrong.get_json()["code"], "checksum_mismatch")
        self.assertEqual(self._stored_files(), [])
        self.assertEqual(self._put(draft["draft_id"], cid, PNG, headers={"X-Content-SHA256": "xyz"}).status_code, 400)

        self.assertEqual(self._put(draft["draft_id"], cid, PNG, headers={"X-Content-SHA256": sha}).status_code, 201)
        again = self._put(draft["draft_id"], cid, PNG, headers={"X-Content-SHA256": sha})
        self.assertEqual(again.status_code, 200)
        # Same size, different bytes: only the checksum can tell.
        other = PNG[:-1] + b"\x01"
        self.assertEqual(len(other), len(PNG))
        clash = self._put(draft["draft_id"], cid, other, headers={"X-Content-SHA256": hashlib.sha256(other).hexdigest()})
        self.assertEqual(clash.status_code, 409)
        self.assertEqual(clash.get_json()["code"], "attachment_id_conflict")
        # Without the header the size comparison still applies, and this passes it.
        self.assertEqual(self._put(draft["draft_id"], cid, other).status_code, 200)
