"""Public demo retention (digitva-77v5.6): the 30-day purge and the eviction at
the account cap. Policy: docs/policy/public-demo.md sections 8 and 9.

A demo account is seeded with a row in every table the purge covers (via a
filler that satisfies each NOT NULL column), purged, and every table is
compared with its count before the account existed; a second account's rows
must survive. Presence is asserted before absence.
"""
import os
import tempfile
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest import mock

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg

from app import db
from app.models import (
    AuthDevice,
    AuthDeviceEnrolmentCode,
    AuthDeviceSession,
    AuthDeviceSigningKey,
    AuthSecurityEvent,
    AuthSignInToken,
    MapCaseContactAttempt,
    MapCaseTransition,
    MapConsentAudit,
    MapDeathIdentifier,
    MapIdentifierAudit,
    MapPayloadVersionPii,
    MapUserNotification,
    MasDeathIdentifierType,
    MasPiiAccessLog,
    VaAiQueryAuditLog,
    VaAiSavedQuery,
    VaAllocations,
    VaCoderReview,
    VaCodingEpisode,
    VaConsentRecord,
    VaConsentRecordPurpose,
    VaDataManagerReview,
    VaDeathRegister,
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaForms,
    VaInitialAssessments,
    VaNarrativeAssessment,
    VaResearchProjects,
    VaReviewerFinalAssessments,
    VaReviewerInitialAssessments,
    VaReviewerReview,
    VaSites,
    VaSmartvaFormRun,
    VaSmartvaResults,
    VaSmartvaRun,
    VaSmartvaRunOutput,
    VaSocialAutopsyAnalysis,
    VaSocialAutopsyAnalysisOption,
    VaSubmissionAttachments,
    VaSubmissionNotification,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaSubmissionUpstreamChange,
    VaSubmissionWorkflowEvent,
    VaUsernotes,
    VaUsers,
    VaWebIntakeAttachment,
    VaWebIntakeDraft,
    VaWebIntakeDraftSection,
)
from app.services import consent_service
from app.services import public_demo_purge_service as purge
from app.services import public_demo_service as demo
from tests.test_public_demo import PROJECT, PublicDemoBase


def make(model, **values):
    """An instance of *model* with *values* and a dummy for every NOT NULL
    column that has no default of its own."""
    for attr in sa.inspect(model).column_attrs:
        col = attr.columns[0]
        if attr.key in values or col.nullable and not col.primary_key:
            continue
        if col.default is not None or col.server_default is not None or col.identity is not None:
            continue
        kind = col.type
        if isinstance(kind, sa.Integer) and col.primary_key:
            continue
        if isinstance(kind, sa.Enum):
            value = kind.enums[0]
        elif isinstance(kind, sa.Uuid):
            value = uuid.uuid4()
        elif isinstance(kind, sa.Boolean):
            value = False
        elif isinstance(kind, (sa.Integer, sa.Numeric, sa.Float)):
            value = 0
        elif isinstance(kind, sa.DateTime):
            value = datetime.now(UTC)
        elif isinstance(kind, sa.Date):
            value = date.today()
        elif isinstance(kind, sa.JSON):
            value = {}
        elif isinstance(kind, pg.ARRAY):
            value = []
        elif isinstance(kind, sa.LargeBinary):
            value = b"x"
        else:
            value = uuid.uuid4().hex[: getattr(kind, "length", None) or 12]
        values[attr.key] = value
    return model(**values)


class PurgeBase(PublicDemoBase):
    def setUp(self):
        super().setUp()
        self._data = tempfile.TemporaryDirectory()
        self.addCleanup(self._data.cleanup)
        patch = mock.patch.dict(
            self.app.config, PUBLIC_DEMO_PURGE_ENABLED=True, APP_DATA=self._data.name,
            PUBLIC_DEMO_MAX_ACCOUNTS=500,
        )
        patch.start()
        self.addCleanup(patch.stop)
        self.app.extensions.pop("attachment_store", None)
        self.addCleanup(self.app.extensions.pop, "attachment_store", None)

    # -- helpers ----------------------------------------------------------

    def _add(self, model, **values):
        row = make(model, **values)
        db.session.add(row)
        db.session.flush()
        return row

    def _idle(self, user, days):
        """Make the account's last activity *days* ago: sign-in, creation, any
        device session and any draft."""
        then = datetime.now(UTC) - timedelta(days=days)
        user.last_signed_in_at = then
        user.user_created_at = then - timedelta(days=1)
        db.session.execute(sa.update(AuthDeviceSession).where(AuthDeviceSession.user_id == user.user_id).values(
            created_at=then, last_seen_at=None, refreshed_at=None))
        db.session.execute(sa.update(VaWebIntakeDraft).where(VaWebIntakeDraft.user_id == user.user_id).values(
            created_at=then, updated_at=then))
        db.session.commit()

    def _other_project_form(self):
        """A form of a project other than the demo's."""
        self._add(VaResearchProjects, project_id="PGOP01")
        self._add(VaSites, site_id="PGS1", project_id="PGOP01")
        return self._add(VaForms, form_id="PGOF01", project_id="PGOP01", site_id="PGS1",
                         form_source="web", form_type="WHO_2022_VA").form_id

    def _file(self, name, form_id=None):
        path = os.path.join(self._data.name, form_id or self.form_id, "media", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"demo")
        return path

    def _snapshot(self):
        return {t: db.session.scalar(sa.text(f"SELECT count(*) FROM {t}")) for t in sorted(purge.PURGED_TABLES)}

    def _seed_small(self, user, sid):
        """A submitted case with a draft upload and a notification."""
        self._case(user, sid)
        draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.va_sid == sid))
        name = uuid.uuid4().hex
        self._file(name)
        self._add(VaWebIntakeAttachment, draft_id=draft.draft_id, client_attachment_id=uuid.uuid4(),
                  filename="b.png", storage_name=name, store_state="local", mime_type="image/png",
                  size_bytes=4, sha256="0" * 64)
        self._add(MapUserNotification, user_id=user.user_id, kind="x", project_id=PROJECT,
                  va_sid=sid, draft_id=draft.draft_id)
        db.session.commit()
        return [os.path.join(self._data.name, self.form_id, "media", name)]

    def _seed_full(self, user, sid):
        """A row in every table the purge covers except the bundle ones (a
        bundle ingest needs an offline station configuration). Returns the
        stored files."""
        uid = user.user_id
        self._case(user, sid, state="coded")
        draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.va_sid == sid))
        now = datetime.now(UTC)
        death = self._add(
            VaDeathRegister, project_id=PROJECT, site_id=self.site_id, org_unit_id=self.unit_id,
            registered_by=uid, started_by_user_id=uid, va_sid=sid, unique_id=f"purge-{sid}", source="register", status="draft_identity",
        )
        draft.death_id = death.death_id
        other_death = self._add(
            VaDeathRegister, project_id=PROJECT, site_id=self.site_id, org_unit_id=self.unit_id,
            registered_by=uid, unique_id=f"purge-dup-{sid}", source="register", status="draft_identity",
            duplicate_of_death_id=death.death_id,
        )
        pv = self._add(VaSubmissionPayloadVersion, va_sid=sid, created_by=uid, version_status="active")
        sub = db.session.get(VaSubmissions, sid)
        sub.active_payload_version_id = pv.payload_version_id
        self._add(MapPayloadVersionPii, va_sid=sid, payload_version_id=pv.payload_version_id)
        # Files: one shared by the submission and its draft upload, one only a draft holds.
        shared, draft_only = uuid.uuid4().hex, uuid.uuid4().hex
        self._file(shared)
        self._file(draft_only)
        self._add(VaSubmissionAttachments, va_sid=sid, filename="narration.mp3", storage_name=shared)
        self._add(VaWebIntakeAttachment, draft_id=draft.draft_id, client_attachment_id=uuid.uuid4(),
                  filename="narration.amr", storage_name=shared, store_state="local",
                  mime_type="audio/amr", size_bytes=4, sha256="0" * 64)
        self._add(VaWebIntakeAttachment, draft_id=draft.draft_id, client_attachment_id=uuid.uuid4(),
                  filename="record.png", storage_name=draft_only, store_state="local",
                  mime_type="image/png", size_bytes=4, sha256="1" * 64)
        self._add(VaWebIntakeDraftSection, draft_id=draft.draft_id, section_name="s1", data={})
        # SmartVA.
        run = self._add(VaSmartvaRun, va_sid=sid, payload_version_id=pv.payload_version_id)
        self._add(VaSmartvaRunOutput, va_smartva_run_id=run.va_smartva_run_id)
        self._add(VaSmartvaResults, va_sid=sid, payload_version_id=pv.payload_version_id,
                  smartva_run_id=run.va_smartva_run_id)
        # Coding and review.
        initial = self._add(VaInitialAssessments, va_sid=sid, va_iniassess_by=uid)
        final = self._add(VaFinalAssessments, va_sid=sid, va_finassess_by=uid,
                          source_initial_assessment_id=initial.va_iniassess_id,
                          payload_version_id=pv.payload_version_id)
        r_initial = self._add(VaReviewerInitialAssessments, va_sid=sid, va_riniassess_by=uid,
                              payload_version_id=pv.payload_version_id)
        r_final = self._add(VaReviewerFinalAssessments, va_sid=sid, va_rfinassess_by=uid,
                            source_reviewer_initial_assessment_id=r_initial.va_riniassess_id,
                            supersedes_coder_final_assessment_id=final.va_finassess_id,
                            payload_version_id=pv.payload_version_id)
        self._add(VaFinalCodAuthority, va_sid=sid, updated_by=uid,
                  authoritative_final_assessment_id=final.va_finassess_id,
                  authoritative_reviewer_final_assessment_id=r_final.va_rfinassess_id)
        self._add(VaCodingEpisode, va_sid=sid, started_by=uid,
                  base_final_assessment_id=final.va_finassess_id,
                  replacement_final_assessment_id=final.va_finassess_id)
        self._add(VaReviewerReview, va_sid=sid, va_rreview_by=uid, payload_version_id=pv.payload_version_id)
        self._add(VaCoderReview, va_sid=sid, va_creview_by=uid)
        self._add(VaDataManagerReview, va_sid=sid, va_dmreview_by=uid)
        self._add(VaAllocations, va_sid=sid, va_allocated_to=uid)
        self._add(VaNarrativeAssessment, va_sid=sid, va_nqa_by=uid, payload_version_id=pv.payload_version_id)
        analysis = self._add(VaSocialAutopsyAnalysis, va_sid=sid, va_saa_by=uid,
                             payload_version_id=pv.payload_version_id)
        self._add(VaSocialAutopsyAnalysisOption, va_saa_id=analysis.va_saa_id)
        self._add(VaUsernotes, note_vasubmission=sid, note_by=uid)
        self._add(VaSubmissionsAuditlog, va_sid=sid)
        self._add(VaSubmissionWorkflowEvent, va_sid=sid)
        change = self._add(VaSubmissionUpstreamChange, va_sid=sid, resolved_by=uid,
                           previous_payload_version_id=pv.payload_version_id,
                           incoming_payload_version_id=pv.payload_version_id,
                           previous_final_assessment_id=final.va_finassess_id)
        self._add(VaSubmissionNotification, va_sid=sid, upstream_change_id=change.upstream_change_id)
        # Death registration side: consent, identifier, transition, contact attempt.
        notice = consent_service.active_versions(PROJECT)[0]
        consent = self._add(VaConsentRecord, project_id=PROJECT, death_id=death.death_id,
                            notice_version_id=notice.notice_version_id, recorded_by=uid, event="granted",
                            mode="tap", channel="web")
        self._add(VaConsentRecordPurpose, consent_id=consent.consent_id, purpose_code="research")
        id_type = db.session.scalar(sa.select(MasDeathIdentifierType).where(
            MasDeathIdentifierType.project_id == PROJECT))
        if id_type is None:
            id_type = self._add(MasDeathIdentifierType, project_id=PROJECT, code="crs", label="CRS",
                                sort_order=1, min_length=6, max_length=12, char_type="digits")
        self._add(MapDeathIdentifier, death_id=death.death_id, identifier_type_id=id_type.identifier_type_id,
                  entered_by=uid)
        self._add(MapCaseTransition, death_id=death.death_id, actor_user_id=uid)
        self._add(MapCaseContactAttempt, death_id=death.death_id, by_user_id=uid, outcome="reached")
        self._add(MapConsentAudit, project_id=PROJECT, actor_user_id=uid)
        self._add(MapIdentifierAudit, project_id=PROJECT, actor_user_id=uid)
        self._add(MasPiiAccessLog, user_id=uid, submission_id=sid)
        self._add(VaAiQueryAuditLog, user_id=uid, mode="ai_llm")
        self._add(VaAiSavedQuery, owner_user_id=uid, title="Deaths", original_prompt="Deaths",
                  validated_sql="SELECT 1 AS x", layout_recipe={})
        self._add(MapUserNotification, user_id=uid, kind="x", project_id=PROJECT, va_sid=sid,
                  draft_id=draft.draft_id, death_id=other_death.death_id)
        # A device only this account used, enrolled by a code it created.
        code = self._add(AuthDeviceEnrolmentCode, project_id=PROJECT, created_by=uid,
                         expires_at=now + timedelta(days=1))
        device = self._add(AuthDevice, project_id=PROJECT, enrolled_via=code.id)
        self._add(AuthDeviceSigningKey, device_id=device.device_id)
        self._add(AuthDeviceSession, device_id=device.device_id, user_id=uid,
                  access_expires_at=now, refresh_expires_at=now)
        self._redeemed_sign_in_qr(uid)
        db.session.commit()
        return [os.path.join(self._data.name, self.form_id, "media", name) for name in (shared, draft_only)]

    def _redeemed_sign_in_qr(self, uid):
        """A sign-in QR the account redeemed: the token and the device it
        enrolled reference each other. Returns ``(token, device)``."""
        now = datetime.now(UTC)
        token = self._add(AuthSignInToken, user_id=uid, token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
                          issued_by=uid, expires_at=now + timedelta(minutes=5), redeemed_at=now,
                          user_session_version=0)
        device = self._add(AuthDevice, project_id=PROJECT, enrolled_via_sign_in_token=token.id)
        token.redeemed_device_id = device.device_id
        self._add(AuthDeviceSession, device_id=device.device_id, user_id=uid,
                  access_expires_at=now, refresh_expires_at=now)
        db.session.flush()
        return token, device

    #: Covered by the purge but not seeded: a bundle ingest needs an offline
    #: station configuration, which a demo account never has.
    UNSEEDED = {"va_bundle_ingests", "map_bundle_records", "va_bundle_pending_coding", "mas_org_unit_worker",
                "map_mentor_institute_user", "map_training_participants", "auth_mobile_codes",
                "auth_recovery_codes", "auth_totp", "auth_webauthn_credentials"}


class PurgeTests(PurgeBase):
    def test_purge_removes_every_row_of_the_account_and_leaves_the_others(self):
        bob = self._account("demo.pgb")
        b_files = self._seed_small(bob, "pg-bob")
        without = self._snapshot()
        alice = self._account("demo.pga")
        a_files = self._seed_full(alice, "pg-alice")
        with_alice = self._snapshot()
        # Presence first: every covered table that can be seeded holds a row of hers.
        seeded = {t for t in purge.PURGED_TABLES if with_alice[t] > without[t]}
        self.assertEqual(set(purge.PURGED_TABLES) - seeded, self.UNSEEDED)
        self.assertEqual(with_alice["va_users"] - without["va_users"], 1)
        for path in a_files + b_files:
            self.assertTrue(os.path.exists(path))
        self._idle(alice, 31)
        self._idle(bob, 1)

        result = purge.purge_run(apply=True)

        self.assertEqual((result["status"], result["accounts"], result["failed"], result["refused"]),
                         ("ok", 1, 0, {}))
        # Hers are gone from every table, bob's are all still there.
        self.assertEqual(self._snapshot(), without)
        self.assertIsNone(self._user("demo.pga"))
        self.assertIsNotNone(self._user("demo.pgb"))
        self.assertIsNotNone(db.session.get(VaSubmissions, "pg-bob"))
        self.assertIsNone(db.session.get(VaSubmissions, "pg-alice"))
        # ... and so are her stored files; his remain.
        self.assertFalse(any(os.path.exists(path) for path in a_files))
        self.assertTrue(all(os.path.exists(path) for path in b_files))

    def test_a_redeemed_sign_in_qr_and_its_device_go_together_and_others_stay(self):
        alice = self._account("demo.pgq")
        bob = self._account("demo.pgr")
        a_token, a_device = self._redeemed_sign_in_qr(alice.user_id)
        b_token, b_device = self._redeemed_sign_in_qr(bob.user_id)
        db.session.commit()
        ids = (a_token.id, a_device.device_id, b_token.id, b_device.device_id)
        a_token_id, a_device_id, b_token_id, b_device_id = ids
        self.assertIsNotNone(db.session.get(AuthSignInToken, b_token_id))
        self.assertIsNotNone(db.session.get(AuthDevice, b_device_id))
        self._idle(alice, 40)
        self._idle(bob, 1)

        result = purge.purge_run(apply=True)

        self.assertEqual((result["accounts"], result["failed"]), (1, 0))
        self.assertIsNone(db.session.get(AuthSignInToken, a_token_id))
        self.assertIsNone(db.session.get(AuthDevice, a_device_id))
        bob_token = db.session.get(AuthSignInToken, b_token_id)
        self.assertIsNotNone(bob_token)
        self.assertEqual(bob_token.redeemed_device_id, b_device_id)
        self.assertEqual(db.session.get(AuthDevice, b_device_id).enrolled_via_sign_in_token, b_token_id)

    def test_a_second_full_account_leaves_no_trace_either(self):
        before = self._snapshot()
        alice = self._account("demo.pgc")
        self._seed_full(alice, "pg-cover")
        self.assertGreater(self._snapshot()["va_death_register"], before["va_death_register"])
        self._idle(alice, 40)
        self.assertEqual(purge.purge_run(apply=True)["accounts"], 1)
        self.assertEqual(self._snapshot(), before)

    def test_files_are_removed_only_after_the_commit(self):
        alice = self._account("demo.pgd")
        files = self._seed_full(alice, "pg-late")
        self._idle(alice, 40)
        counts = purge.delete_account(alice.user_id, 30)
        self.assertEqual(counts["files"], 2)
        self.assertTrue(all(os.path.exists(path) for path in files))  # rows deleted, files still there
        db.session.rollback()
        self.assertTrue(all(os.path.exists(path) for path in files))
        self.assertIsNotNone(self._user("demo.pgd"))
        purge.delete_account(alice.user_id, 30)
        db.session.commit()
        self.assertFalse(any(os.path.exists(path) for path in files))

    def test_a_failure_on_one_account_leaves_it_whole_and_goes_on(self):
        alice, bob = self._account("demo.pge"), self._account("demo.pgf")
        self._seed_small(alice, "pg-fail-a")
        self._seed_small(bob, "pg-fail-b")
        self._idle(alice, 40)
        self._idle(bob, 50)  # bob is older, so he goes first
        # A row in a table the purge does not cover that points at bob's account.
        db.session.add(make(MapConsentAudit, project_id=PROJECT, actor_user_id=bob.user_id))
        db.session.commit()
        with mock.patch.object(purge, "PLAN", tuple(row for row in purge.PLAN if row[0] != "map_consent_audit")):
            result = purge.purge_run(apply=True)
        self.assertEqual((result["accounts"], result["failed"]), (1, 1))
        self.assertIsNotNone(self._user("demo.pgf"))
        self.assertIsNotNone(db.session.get(VaSubmissions, "pg-fail-b"))
        self.assertIsNone(self._user("demo.pge"))

    def test_only_accounts_idle_that_long_are_taken(self):
        old, fresh, never = self._account("demo.pgg"), self._account("demo.pgh"), self._account("demo.pgi")
        self._idle(old, 31)
        self._idle(fresh, 29)
        never.last_signed_in_at = None
        never.user_created_at = datetime.now(UTC) - timedelta(days=45)
        db.session.commit()
        result = purge.purge_run(apply=True)
        self.assertEqual(result["accounts"], 2)
        self.assertEqual([self._user(n) is None for n in ("demo.pgg", "demo.pgh", "demo.pgi")], [True, False, True])

    def test_device_use_keeps_an_account_whose_last_sign_in_is_old(self):
        alice = self._account("demo.pgj")
        self._seed_full(alice, "pg-active")
        self._idle(alice, 40)
        device_session = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.user_id == alice.user_id))
        device_session.refreshed_at = datetime.now(UTC) - timedelta(days=2)
        db.session.commit()
        self.assertEqual(purge.purge_run(apply=True)["accounts"], 0)
        self.assertIsNotNone(self._user("demo.pgj"))

    def test_the_run_is_audited_with_counts_only(self):
        alice = self._account("demo.pgk")
        self._seed_small(alice, "pg-audit")
        self._idle(alice, 40)
        purge.purge_run(apply=True)
        event = db.session.scalar(sa.select(AuthSecurityEvent).where(AuthSecurityEvent.event_type == purge.PURGE_EVENT))
        self.assertEqual((event.user_id, event.detail["accounts"], event.detail["failed"]), (None, 1, 0))
        self.assertEqual(event.detail["rows"]["va_users"], 1)
        self.assertNotIn("demo.pgk", str(event.detail))

    def test_the_batch_bounds_a_run(self):
        users = [self._account(f"demo.batch{i}") for i in range(3)]
        for user in users:
            self._idle(user, 40)
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_PURGE_BATCH=2):
            self.assertEqual(purge.purge_run(apply=True)["accounts"], 2)
        self.assertEqual(sum(self._user(f"demo.batch{i}") is not None for i in range(3)), 1)

    def test_refused_accounts_do_not_starve_the_batch(self):
        refused = [self._account("demo.stv1"), self._account("demo.stv2")]
        for i, user in enumerate(refused):
            self._seed_small(user, f"pg-stv{i}")
            db.session.execute(sa.update(VaWebIntakeDraft).where(VaWebIntakeDraft.user_id == user.user_id).values(
                project_id=self.BASE_PROJECT_ID))
            db.session.commit()
        eligible = [self._account("demo.stv3"), self._account("demo.stv4"), self._account("demo.stv5")]
        for user, days in zip(refused + eligible, (60, 55, 40, 38, 36)):
            self._idle(user, days)  # the refused ones are the oldest: selected first
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_PURGE_BATCH=2):
            result = purge.purge_run(apply=True)
        self.assertEqual((result["accounts"], result["refused"], result["failed"]), (2, {"not_demo_project": 2}, 0))
        self.assertEqual([self._user(n) is None for n in ("demo.stv3", "demo.stv4", "demo.stv5")],
                         [True, True, False])
        self.assertTrue(all(self._user(n) for n in ("demo.stv1", "demo.stv2")))

    def test_the_scan_is_bounded(self):
        for i in range(3):
            self._idle(self._account(f"demo.scan{i}"), 40)
        with mock.patch.object(purge, "PURGE_SCAN_LIMIT", 2), mock.patch.dict(
                self.app.config, PUBLIC_DEMO_PURGE_BATCH=1):
            self.assertEqual(purge.purge_run(apply=True)["accounts"], 1)
        self.assertEqual(sum(self._user(f"demo.scan{i}") is None for i in range(3)), 1)

    def test_a_draft_edit_keeps_an_account_whose_sign_in_is_old(self):
        alice = self._account("demo.draftuse")
        self._seed_small(alice, "pg-draftuse")
        self._idle(alice, 40)
        self.assertEqual(purge.idle_user_ids(30, limit=10), [alice.user_id])  # idle by sign-in and drafts alone
        db.session.execute(sa.update(VaWebIntakeDraft).where(VaWebIntakeDraft.user_id == alice.user_id).values(
            updated_at=datetime.now(UTC) - timedelta(days=2)))
        db.session.commit()
        self.assertEqual(purge.idle_user_ids(30, limit=10), [])
        self.assertEqual(purge.purge_run(apply=True)["accounts"], 0)
        self.assertIsNotNone(self._user("demo.draftuse"))

    def test_other_accounts_rows_on_a_purged_case_go_with_it(self):
        alice, bob = self._account("demo.oth1"), self._account("demo.oth2")
        self._seed_small(alice, "pg-oth")
        self._add(VaAllocations, va_sid="pg-oth", va_allocated_to=bob.user_id)
        self._add(VaUsernotes, note_vasubmission="pg-oth", note_by=bob.user_id)
        self._add(MapUserNotification, user_id=bob.user_id, kind="x", project_id=PROJECT, va_sid="pg-oth")
        db.session.commit()
        for model, column, expected in ((VaAllocations, VaAllocations.va_sid, 1),
                                        (VaUsernotes, VaUsernotes.note_vasubmission, 1),
                                        (MapUserNotification, MapUserNotification.va_sid, 2)):  # present before purge
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(model).where(
                column == "pg-oth")), expected)
        self._idle(alice, 40)
        self._idle(bob, 1)
        self.assertEqual(purge.purge_run(apply=True)["accounts"], 1)
        for model, column in ((VaAllocations, VaAllocations.va_sid), (VaUsernotes, VaUsernotes.note_vasubmission),
                              (MapUserNotification, MapUserNotification.va_sid)):
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(model).where(
                column == "pg-oth")), 0)
        self.assertIsNotNone(self._user("demo.oth2"))


class PurgeGuardTests(PurgeBase):
    def setUp(self):
        super().setUp()
        self.alice = self._account("demo.guard")
        self._seed_small(self.alice, "pg-guard")
        self._idle(self.alice, 40)

    def _untouched(self):
        self.assertIsNotNone(self._user("demo.guard"))
        self.assertIsNotNone(db.session.get(VaSubmissions, "pg-guard"))

    def test_flag_off_refuses(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=False):
            self.assertEqual(purge.purge_run(apply=True)["status"], "not_enabled")
            self.assertEqual(purge.purge_run(apply=False)["status"], "not_enabled")
            with self.assertRaises(purge.PurgeRefused) as ctx:
                purge.delete_account(self.alice.user_id, 30)
        self.assertEqual(ctx.exception.reason, "not_enabled")
        self._untouched()

    def test_purge_disabled_refuses_apply_but_not_a_dry_run(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_PURGE_ENABLED=False):
            self.assertEqual(purge.purge_run(apply=True)["status"], "purge_disabled")
            with self.assertRaises(purge.PurgeRefused):
                purge.delete_account(self.alice.user_id, 30)
            self.assertEqual(purge.purge_run(apply=False)["accounts"], 1)
            self.assertFalse(purge.evict_one())
        self._untouched()

    def test_main_database_refuses(self):
        with mock.patch.object(demo, "foreign_projects_exist", return_value=True), \
                self.assertLogs("app.services.public_demo_service", "ERROR") as logs:
            self.assertEqual(purge.purge_run(apply=True)["status"], "main_database")
            self.assertEqual(purge.purge_run(apply=False)["status"], "main_database")
            self.assertFalse(purge.evict_one())
        self.assertIn("main database", logs.output[0])
        self._untouched()

    def test_a_non_demo_account_is_never_selected_or_deleted(self):
        coder = self.base_coder_user
        coder.last_signed_in_at = datetime.now(UTC) - timedelta(days=400)
        db.session.commit()
        self.assertNotIn(coder.user_id, purge.idle_user_ids(30, limit=100))
        with self.assertRaises(purge.PurgeRefused) as ctx:
            purge.delete_account(coder.user_id, 30)
        self.assertEqual(ctx.exception.reason, "not_eligible")
        self.assertIsNotNone(db.session.get(VaUsers, coder.user_id))

    def test_an_account_active_since_the_cutoff_is_not_eligible(self):
        self.alice.last_signed_in_at = datetime.now(UTC)
        db.session.commit()
        with self.assertRaises(purge.PurgeRefused) as ctx:
            purge.delete_account(self.alice.user_id, 30)
        self.assertEqual(ctx.exception.reason, "not_eligible")

    def test_a_submission_outside_the_demo_project_refuses_the_account(self):
        other_form = self._other_project_form()
        db.session.execute(sa.update(VaSubmissions).where(VaSubmissions.va_sid == "pg-guard").values(
            va_form_id=other_form))
        db.session.commit()
        result = purge.purge_run(apply=True)
        self.assertEqual((result["accounts"], result["refused"]), (0, {"not_demo_project": 1}))
        self._untouched()

    def test_a_draft_or_grant_outside_the_demo_project_refuses_the_account(self):
        draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.va_sid == "pg-guard"))
        draft.project_id = self.BASE_PROJECT_ID
        db.session.commit()
        self._idle(self.alice, 40)  # the edit above touched the draft
        self.assertEqual(purge.purge_run(apply=True)["refused"], {"not_demo_project": 1})
        draft.project_id = PROJECT
        db.session.execute(sa.update(purge.VaUserAccessGrants).where(
            purge.VaUserAccessGrants.user_id == self.alice.user_id,
            purge.VaUserAccessGrants.role == demo.VaAccessRoles.coder,
        ).values(project_id=self.BASE_PROJECT_ID))
        db.session.commit()
        self._idle(self.alice, 40)
        self.assertEqual(purge.purge_run(apply=True)["refused"], {"grant_outside_demo": 1})
        self._untouched()

    def test_a_case_another_account_shares_refuses_the_account(self):
        bob = self._account("demo.guardb")
        db.session.add(make(VaWebIntakeDraft, project_id=PROJECT, site_id=self.site_id, form_id=self.form_id,
                            user_id=bob.user_id, va_sid="pg-guard", status="submitted"))
        db.session.commit()
        self.assertEqual(purge.purge_run(apply=True)["refused"], {"shared_case": 1})
        self._untouched()

    def test_dry_run_deletes_nothing_and_reports_the_counts_of_a_real_run(self):
        self._seed_full(self._account("demo.dry"), "pg-dry")
        self._idle(self._user("demo.dry"), 50)
        before = self._snapshot()
        dry = purge.purge_run(apply=False)
        self.assertEqual(self._snapshot(), before)
        self.assertIsNotNone(db.session.get(VaSubmissions, "pg-dry"))
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == purge.PURGE_EVENT)), 0)
        real = purge.purge_run(apply=True)
        self.assertEqual(dry["accounts"], real["accounts"])
        self.assertEqual(dry["rows"], real["rows"])
        self.assertEqual(dry["rows"]["va_users"], 2)


class EvictionTests(PurgeBase):
    def _fill(self, days_by_name):
        """Accounts idle for the given days, and a cap equal to their number."""
        users = {}
        for name, days in days_by_name.items():
            users[name] = self._account(name)
            self._idle(users[name], days)
        return users

    def _cap(self):
        return mock.patch.dict(self.app.config, PUBLIC_DEMO_MAX_ACCOUNTS=demo.active_account_count())

    def test_the_oldest_account_idle_a_week_makes_room(self):
        self._fill({"demo.ev1": 8, "demo.ev2": 20, "demo.ev3": 10, "demo.ev4": 2})
        with self._cap():
            demo.create_account("demo.ev.new", "plain-demo-password-1")
            db.session.commit()
        self.assertIsNone(self._user("demo.ev2"))  # idle 20 days: the oldest
        self.assertIsNotNone(self._user("demo.ev.new"))
        self.assertTrue(all(self._user(n) for n in ("demo.ev1", "demo.ev3", "demo.ev4")))
        event = db.session.scalar(sa.select(AuthSecurityEvent).where(AuthSecurityEvent.event_type == purge.EVICT_EVENT))
        self.assertEqual(event.detail["rows"]["va_users"], 1)
        self.assertNotIn("demo.ev2", str(event.detail))

    def test_an_evicted_account_goes_with_its_data_and_files(self):
        users = self._fill({"demo.ev5": 9, "demo.ev6": 1})
        files = self._seed_full(users["demo.ev5"], "pg-evict")
        self._idle(users["demo.ev5"], 9)
        with self._cap():
            demo.create_account("demo.ev.new2", "plain-demo-password-1")
            self.assertTrue(all(os.path.exists(path) for path in files))  # not before the commit
            db.session.commit()
        self.assertFalse(any(os.path.exists(path) for path in files))
        self.assertIsNone(db.session.get(VaSubmissions, "pg-evict"))

    def test_a_rolled_back_sign_up_keeps_the_account_it_would_have_evicted(self):
        users = self._fill({"demo.ev7": 9, "demo.ev8": 1})
        files = self._seed_small(users["demo.ev7"], "pg-keep")
        self._idle(users["demo.ev7"], 9)
        with self._cap():
            demo.create_account("demo.ev.new3", "plain-demo-password-1")
            db.session.rollback()
        self.assertIsNotNone(self._user("demo.ev7"))
        self.assertIsNone(self._user("demo.ev.new3"))
        self.assertTrue(all(os.path.exists(path) for path in files))

    def test_nobody_idle_a_week_refuses_with_the_stable_message_and_code(self):
        self._fill({"demo.ev9": 6, "demo.ev10": 1})
        with self._cap():
            with self.assertRaises(demo.PublicDemoError) as ctx:
                demo.create_account("demo.ev.new4", "plain-demo-password-1")
        self.assertEqual((ctx.exception.code, ctx.exception.status_code, ctx.exception.message),
                         ("cap_reached", 503, "The demo is full; try again later."))
        self.assertIsNone(self._user("demo.ev.new4"))

    def test_eviction_off_with_the_purge_refuses_even_when_someone_is_idle(self):
        self._fill({"demo.ev11": 30})
        with self._cap(), mock.patch.dict(self.app.config, PUBLIC_DEMO_PURGE_ENABLED=False):
            with self.assertRaises(demo.PublicDemoError) as ctx:
                demo.create_account("demo.ev.new5", "plain-demo-password-1")
        self.assertEqual(ctx.exception.code, "cap_reached")
        self.assertIsNotNone(self._user("demo.ev11"))

    def test_both_sign_up_paths_answer_the_same_when_full(self):
        self._fill({"demo.ev12": 1})
        with self._cap():
            api = self._api_signup("demo.ev.api")
            web = self._post_signup(username="demo.ev.web")
        self.assertEqual((api.status_code, api.get_json()["code"]), (503, "cap_reached"))
        self.assertEqual(api.get_json()["error"], demo.CAP_REACHED_MESSAGE)
        self.assertIn(demo.CAP_REACHED_MESSAGE, web.get_data(as_text=True))

    def test_json_sign_up_at_the_cap_evicts_and_creates(self):
        self._fill({"demo.ev13": 12})
        with self._cap():
            response = self._api_signup("demo.ev.api2")
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(self._user("demo.ev13"))

    def test_an_account_that_cannot_be_deleted_is_skipped_for_the_next(self):
        users = self._fill({"demo.ev14": 20, "demo.ev15": 10})
        draft_project = self._seed_small(users["demo.ev14"], "pg-skip")
        draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.va_sid == "pg-skip"))
        draft.project_id = self.BASE_PROJECT_ID  # the oldest one is refused by a guard
        db.session.commit()
        self._idle(users["demo.ev14"], 20)
        with self._cap():
            demo.create_account("demo.ev.new6", "plain-demo-password-1")
            db.session.commit()
        self.assertIsNotNone(self._user("demo.ev14"))
        self.assertIsNone(self._user("demo.ev15"))
        self.assertTrue(draft_project)

    def test_a_failed_eviction_keeps_the_files_and_rows_of_the_account_it_tried(self):
        users = self._fill({"demo.ev17": 20, "demo.ev18": 10})
        first_files = self._seed_full(users["demo.ev17"], "pg-failev")
        second_files = self._seed_small(users["demo.ev18"], "pg-okev")
        self._idle(users["demo.ev17"], 20)
        self._idle(users["demo.ev18"], 10)
        real = purge.record_security_event
        calls = []

        def fail_once(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("audit write failed")
            return real(**kwargs)

        with self._cap(), mock.patch.object(purge, "record_security_event", side_effect=fail_once), \
                self.assertLogs("app.services.public_demo_purge_service", "ERROR"):
            demo.create_account("demo.ev.new8", "plain-demo-password-1")
            db.session.commit()  # the sign-up's commit runs the queued file removal
        self.assertEqual(len(calls), 2)
        # The account whose attempt failed is whole: rows and stored files.
        self.assertIsNotNone(self._user("demo.ev17"))
        self.assertIsNotNone(db.session.get(VaSubmissions, "pg-failev"))
        self.assertTrue(all(os.path.exists(path) for path in first_files))
        # The next candidate went, with its files.
        self.assertIsNone(self._user("demo.ev18"))
        self.assertFalse(any(os.path.exists(path) for path in second_files))
        self.assertIsNotNone(self._user("demo.ev.new8"))

    def test_eviction_looks_past_accounts_the_guards_refuse(self):
        users = self._fill({"demo.ev19": 30, "demo.ev20": 29, "demo.ev21": 10})
        for i, name in enumerate(("demo.ev19", "demo.ev20")):
            self._seed_small(users[name], f"pg-refused{i}")
            db.session.execute(sa.update(VaWebIntakeDraft).where(VaWebIntakeDraft.user_id == users[name].user_id).values(
                project_id=self.BASE_PROJECT_ID))
        db.session.commit()
        for name, days in (("demo.ev19", 30), ("demo.ev20", 29)):
            self._idle(users[name], days)
        with self._cap(), mock.patch.object(purge, "EVICT_SCAN_LIMIT", 2):
            with self.assertRaises(demo.PublicDemoError):
                demo.create_account("demo.ev.new9", "plain-demo-password-1")  # the scan ends inside the refused ones
            db.session.rollback()
        with self._cap():
            demo.create_account("demo.ev.new10", "plain-demo-password-1")
            db.session.commit()
        self.assertIsNone(self._user("demo.ev21"))

    def test_a_deployment_pointed_at_the_main_database_neither_signs_up_nor_evicts(self):
        self._fill({"demo.ev16": 30})
        with self._cap(), mock.patch.object(demo, "foreign_projects_exist", return_value=True), \
                self.assertLogs("app.services.public_demo_service", "ERROR"):
            with self.assertRaises(demo.PublicDemoError) as ctx:
                demo.create_account("demo.ev.new7", "plain-demo-password-1")
        self.assertEqual((ctx.exception.code, ctx.exception.status_code), ("wrong_database", 503))
        self.assertIsNotNone(self._user("demo.ev16"))


class PurgeCoverageTests(PurgeBase):
    def test_every_table_pointing_at_an_account_or_a_case_is_purged_or_deliberately_kept(self):
        """Walks the foreign keys from the four roots, into the children of
        every purged table. A table added by a later migration fails here
        until it is added to ``PLAN`` or to ``RETAINED_TABLES`` with a reason."""
        roots = {"va_users", "va_submissions", "va_web_intake_drafts", "va_death_register", "auth_devices"}
        children: dict[str, set[str]] = {}
        for table in db.metadata.tables.values():
            for fk in table.foreign_keys:
                children.setdefault(fk.column.table.name, set()).add(table.name)
        found, queue = set(), list(roots)
        while queue:
            parent = queue.pop()
            for child in children.get(parent, ()):
                if child not in found:
                    found.add(child)
                    if child in purge.PURGED_TABLES:
                        queue.append(child)
        found -= roots
        self.assertEqual(sorted(found - set(purge.PURGED_TABLES) - set(purge.RETAINED_TABLES)), [])
        self.assertEqual(sorted(set(purge.PURGED_TABLES) & set(purge.RETAINED_TABLES)), [])
        for table in purge.PURGED_TABLES | set(purge.RETAINED_TABLES):
            self.assertIn(table, db.metadata.tables)

    def test_plan_deletes_children_before_the_rows_they_reference(self):
        order = {table: i for i, (table, _) in enumerate(purge.PLAN)}
        for table in db.metadata.tables.values():
            if table.name not in order:
                continue
            for fk in table.foreign_keys:
                parent = fk.column.table.name
                if parent in order and parent != table.name and fk.ondelete != "SET NULL" \
                        and (table.name, parent) not in {
                            ("va_submissions", "va_submission_payload_versions"),  # nulled first
                            ("auth_devices", "auth_sign_in_tokens"),  # nulled first; tokens reference devices too
                        }:
                    with self.subTest(child=str(table.name), parent=str(parent)):
                        self.assertLess(order[table.name], order[parent])


class PurgeTaskAndCliTests(PurgeBase):
    def test_the_task_runs_the_purge_and_never_raises(self):
        from app.tasks.public_demo_tasks import purge_public_demo_task

        alice = self._account("demo.task")
        self._idle(alice, 40)
        self.assertEqual(purge_public_demo_task.run()["accounts"], 1)
        with mock.patch.object(purge, "purge_run", side_effect=RuntimeError("boom")):
            self.assertEqual(purge_public_demo_task.run()["status"], "unexpected")

    def test_the_task_does_nothing_while_the_purge_is_disabled(self):
        from app.tasks.public_demo_tasks import purge_public_demo_task

        alice = self._account("demo.taskoff")
        self._idle(alice, 40)
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_PURGE_ENABLED=False):
            self.assertEqual(purge_public_demo_task.run()["status"], "purge_disabled")
        self.assertIsNotNone(self._user("demo.taskoff"))

    def test_cli_dry_run_and_apply(self):
        import json

        alice = self._account("demo.cli")
        self._idle(alice, 40)
        runner = self.app.test_cli_runner()
        dry = runner.invoke(args=["public-demo", "purge", "--dry-run"])
        self.assertEqual(dry.exit_code, 0, dry.output)
        self.assertEqual(json.loads(dry.output)["accounts"], 1)
        self.assertIsNotNone(self._user("demo.cli"))
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_PURGE_ENABLED=False):
            refused = runner.invoke(args=["public-demo", "purge", "--apply"])
        self.assertNotEqual(refused.exit_code, 0)
        self.assertIn("purge_disabled", refused.output)
        applied = runner.invoke(args=["public-demo", "purge", "--apply"])
        self.assertEqual(applied.exit_code, 0, applied.output)
        self.assertIsNone(self._user("demo.cli"))
        self.assertNotEqual(runner.invoke(args=["public-demo", "purge"]).exit_code, 0)


class SmartvaRunFolderTests(PurgeBase):
    """The daily purge also ages out the demo project's SmartVA run folders."""

    def setUp(self):
        super().setUp()
        self._runs = tempfile.TemporaryDirectory()
        self.addCleanup(self._runs.cleanup)
        patch = mock.patch.dict(self.app.config, APP_SMARTVA_RUNS=self._runs.name)
        patch.start()
        self.addCleanup(patch.stop)

    def _run(self, days, *, project=PROJECT, form_id=None, sid=None, state="local", key_prefix=None, write=True):
        """A form run started *days* ago with a folder on disk; *sid* makes a
        ``va_smartva_runs`` row reference it."""
        form_id = form_id or self.form_id
        run_id = uuid.uuid4()
        rel = f"{project}/{form_id}/{run_id}"
        if write:
            os.makedirs(os.path.join(self._runs.name, rel))
            with open(os.path.join(self._runs.name, rel, "out.csv"), "w") as handle:
                handle.write("x")
        run = self._add(
            VaSmartvaFormRun, form_run_id=run_id, form_id=form_id, project_id=project, trigger_source="t",
            pending_sid_count=1, disk_path=rel if write else None, archive_state=state, archive_key_prefix=key_prefix,
            run_started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days),
        )
        if sid:
            self._add(VaSmartvaRun, va_sid=sid, form_run_id=run_id)
        db.session.commit()
        return run.form_run_id, os.path.join(self._runs.name, rel)

    def _row(self, run_id):
        db.session.expire_all()
        return db.session.get(VaSmartvaFormRun, run_id)

    def test_old_unreferenced_runs_go_with_their_rows_and_new_ones_stay(self):
        old, old_dir = self._run(40)
        new, new_dir = self._run(5)
        other_form = self._other_project_form()
        foreign, foreign_dir = self._run(60, project="PGOP01", form_id=other_form)
        for path in (old_dir, new_dir, foreign_dir):
            self.assertTrue(os.path.isdir(path))
        result = purge.purge_smartva_runs(30, apply=True)
        self.assertEqual(result, {"runs": 1, "files_only": 0, "failed": 0})
        self.assertIsNone(self._row(old))
        self.assertFalse(os.path.exists(old_dir))
        self.assertIsNotNone(self._row(new))
        self.assertTrue(os.path.isdir(new_dir))
        self.assertIsNotNone(self._row(foreign))  # another project's run is never touched
        self.assertTrue(os.path.isdir(foreign_dir))

    def test_a_referenced_run_loses_its_files_but_keeps_its_row(self):
        keeper = self._account("demo.runkeep")
        self._case(keeper, "pg-runkeep")
        run, run_dir = self._run(45, sid="pg-runkeep")
        self.assertEqual(purge.purge_smartva_runs(30, apply=True), {"runs": 0, "files_only": 1, "failed": 0})
        row = self._row(run)
        self.assertIsNotNone(row)
        self.assertEqual((row.disk_path, row.archive_key_prefix, row.archive_state), (None, None, "absent"))
        self.assertFalse(os.path.exists(run_dir))
        self.assertEqual(db.session.scalar(sa.select(VaSmartvaRun.form_run_id).where(
            VaSmartvaRun.va_sid == "pg-runkeep")), run)
        # The cleaned row is not selected again.
        self.assertEqual(purge.purge_smartva_runs(30, apply=True), {"runs": 0, "files_only": 0, "failed": 0})

    def test_dry_run_counts_and_deletes_nothing(self):
        run, run_dir = self._run(40)
        self.assertEqual(purge.purge_smartva_runs(30, apply=False), {"runs": 1, "files_only": 0, "failed": 0})
        self.assertIsNotNone(self._row(run))
        self.assertTrue(os.path.isdir(run_dir))

    def test_a_run_is_bounded_per_call(self):
        runs = [self._run(40 + i) for i in range(3)]
        self.assertEqual(purge.purge_smartva_runs(30, apply=True, limit=2)["runs"], 2)
        self.assertEqual(sum(self._row(run) is None for run, _ in runs), 2)
        self.assertEqual(purge.purge_smartva_runs(30, apply=True, limit=2)["runs"], 1)

    def test_a_row_whose_path_is_not_its_own_folder_is_kept_and_counted(self):
        run, run_dir = self._run(40)
        db.session.execute(sa.update(VaSmartvaFormRun).where(VaSmartvaFormRun.form_run_id == run).values(
            disk_path=f"{PROJECT}/{self.form_id}"))
        db.session.commit()
        with self.assertLogs("app.services.public_demo_purge_service", "ERROR"):
            self.assertEqual(purge.purge_smartva_runs(30, apply=True), {"runs": 0, "files_only": 0, "failed": 1})
        self.assertIsNotNone(self._row(run))
        self.assertTrue(os.path.isdir(run_dir))

    def test_archived_objects_are_deleted_from_the_store(self):
        class Store:
            key_prefix = "demo/"

            def __init__(self):
                self.deleted = []

            def absolute_key(self, key):
                return f"demo/{key}"

            def iter_keys(self, prefix):
                self.listed = prefix
                yield f"{prefix}out.csv", 1, "e"
                yield f"{prefix}report.txt", 1, "e"

            def delete_key(self, key):
                self.deleted.append(key)

        store = Store()
        run, _dir = self._run(40, state="archived", write=False)
        expected = f"smartva_runs/{PROJECT}/{self.form_id}/{run}/"
        with mock.patch("app.services.smartva_run_archive_service.archiving_enabled", return_value=True), \
                mock.patch("app.services.attachment_store.get_attachment_store", return_value=store):
            result = purge.purge_smartva_runs(30, apply=True)
        self.assertEqual(result, {"runs": 1, "files_only": 0, "failed": 0})
        self.assertEqual(store.listed, f"demo/{expected}")
        self.assertEqual(store.deleted, [f"{expected}out.csv", f"{expected}report.txt"])
        self.assertIsNone(self._row(run))

    def test_a_store_failure_keeps_the_row_for_tomorrow(self):
        class Broken:
            key_prefix = "demo/"

            def absolute_key(self, key):
                return key

            def iter_keys(self, prefix):
                raise RuntimeError("store down")

        run, _dir = self._run(40, state="archived", write=False)
        with mock.patch("app.services.smartva_run_archive_service.archiving_enabled", return_value=True), \
                mock.patch("app.services.attachment_store.get_attachment_store", return_value=Broken()), \
                self.assertLogs("app.services.public_demo_purge_service", "ERROR"):
            self.assertEqual(purge.purge_smartva_runs(30, apply=True)["failed"], 1)
        self.assertIsNotNone(self._row(run))

    def test_the_daily_purge_runs_it_audits_counts_and_honours_the_guards(self):
        run, run_dir = self._run(40)
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_PURGE_ENABLED=False):
            self.assertEqual(purge.purge_run(apply=True)["status"], "purge_disabled")
        self.assertTrue(os.path.isdir(run_dir))
        dry = purge.purge_run(apply=False)
        self.assertEqual(dry["smartva_runs"]["runs"], 1)
        self.assertTrue(os.path.isdir(run_dir))
        result = purge.purge_run(apply=True)
        self.assertEqual((result["accounts"], result["smartva_runs"]["runs"]), (0, 1))
        self.assertFalse(os.path.exists(run_dir))
        event = db.session.scalar(sa.select(AuthSecurityEvent).where(AuthSecurityEvent.event_type == purge.PURGE_EVENT))
        self.assertEqual(event.detail["smartva_runs"], {"runs": 1, "files_only": 0, "failed": 0})
        self.assertNotIn(str(run), str(event.detail))
