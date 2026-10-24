"""Streaming data-manager exports are byte-identical to the in-memory ones.

digitva-lj7u: ``dm_submissions_export_csv`` and ``dm_smartva_input_export_csv``
used to hold every row and its full payload in memory. They now stream the
query through a server-side cursor, spool each row to a scratch file and write
the CSV from the spool. The golden files under tests/fixtures/dm_export_streaming
were generated from the code BEFORE that change; these tests pin the new code to
them.

Row order: the export query has no ORDER BY, so the database is free to return
rows in any order. The golden comparison therefore pins the header line and the
set of whole records byte for byte, and not their sequence. The SmartVA input
export also orders its payload columns by first sight across rows, so its
comparison pins the leading columns and the trailing ``sid`` and treats the
payload columns and the rows as sets. Byte identity in real order was checked
on a 7k-row dev clone, where the plan is the production one.
"""
import csv
import io
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaFinalAssessments,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import export_store_service
from app.services.data_management_service import (
    dm_smartva_input_export_csv,
    dm_submissions_export_csv,
    write_dm_smartva_input_export_csv,
    write_dm_submissions_export_csv,
)
from app.services.field_mapping_service import PiiSetStatus, get_mapping_service
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import WORKFLOW_CODER_FINALIZED
from tests.base import BaseTestCase

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "dm_export_streaming"

PROJECT = "LJ7U01"
SITE_OK = "LJA1"
SITE_UNCONFIRMED = "LJB1"
FORM_OK = "LJ7U01LJA101"
FORM_UNCONFIRMED = "LJ7U01LJB101"
USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")

#: Fixed moments: every timestamp in the fixture is pinned so the output is
#: deterministic. The UTC value is deliberately a different calendar day from
#: the user's local (Asia/Kolkata) day to exercise the timezone conversion.
T0 = datetime(2031, 3, 10, 20, 0, tzinfo=timezone.utc)
T1 = datetime(2031, 3, 11, 6, 15, 30, tzinfo=timezone.utc)

PII_STATUS = {
    "LJ_OK": PiiSetStatus(
        confirmed=True, field_ids=frozenset({"pii_name", "Id10120"}), owned_flagged_count=1
    ),
}
UNCONFIRMED = PiiSetStatus(confirmed=False, field_ids=frozenset(), owned_flagged_count=0)


SMARTVA_FRONT = ["project_id", "site_id", "va_form_id", "va_uniqueid_masked", "workflow_state"]


def _smartva_view(text):
    """The SmartVA input CSV with its row-order-dependent column order factored out."""
    header, *rows = csv.reader(io.StringIO(text.removeprefix(export_store_service.UTF8_BOM)))
    return (
        header[:5],
        header[-1],
        sorted(header[5:-1]),
        sorted(sorted(zip(header, row)) for row in rows),
    )


def _split_records(text, record_start):
    """Header line plus whole records (a cell may hold a newline), order dropped."""
    header, *records = re.split(rf"(?m)^(?={re.escape(record_start)})", text)
    return header, sorted(records)


class DmExportStreamingTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        db.session.add(VaProjectMaster(
            project_id=PROJECT, project_code=PROJECT, project_name="Streaming Export",
            project_nickname="StreamingExport", project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now,
        ))
        db.session.add(VaResearchProjects(
            project_id=PROJECT, project_code=PROJECT, project_name="Streaming Export",
            project_nickname="StreamingExport", project_status=VaStatuses.active,
        ))
        for site_id in (SITE_OK, SITE_UNCONFIRMED):
            db.session.add(VaSiteMaster(
                site_id=site_id, site_name=f"Site {site_id}", site_abbr=site_id,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        for site_id in (SITE_OK, SITE_UNCONFIRMED):
            db.session.add(VaSites(
                site_id=site_id, project_id=PROJECT, site_name=f"Site {site_id}",
                site_abbr=site_id, site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        for site_id in (SITE_OK, SITE_UNCONFIRMED):
            db.session.add(VaProjectSites(
                project_id=PROJECT, site_id=site_id,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
        for form_id, site_id in ((FORM_OK, SITE_OK), (FORM_UNCONFIRMED, SITE_UNCONFIRMED)):
            db.session.add(VaForms(
                form_id=form_id, project_id=PROJECT, site_id=site_id,
                odk_form_id=f"ODK_{site_id}", odk_project_id="399",
                form_type="WHO VA 2022", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        db.session.flush()

        cls.user = VaUsers(
            user_id=USER_ID, name="lj7u.dm", email="lj7u.dm@test.local",
            vacode_language=["English"], permission={}, landing_page="data_manager",
            pw_reset_t_and_c=True, email_verified=True, user_status=VaStatuses.active,
            timezone="Asia/Kolkata",
        )
        cls.user.set_password("Lj7uDm123")
        db.session.add(cls.user)
        db.session.flush()
        db.session.add(VaUserAccessGrants(
            user_id=USER_ID, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project, project_id=PROJECT,
            grant_status=VaStatuses.active,
        ))

        root_level = MasOrgLevel(project_id=PROJECT, level_code="ljstate", level_name="State", depth=1)
        child_level = MasOrgLevel(project_id=PROJECT, level_code="ljdist", level_name="District", depth=2)
        db.session.add_all([root_level, child_level])
        db.session.flush()
        root = MasOrgUnit(
            project_id=PROJECT, org_level_id=root_level.org_level_id,
            unit_code="LJROOT", unit_name="Root, \"State\"", path="LJROOT",
        )
        child = MasOrgUnit(
            project_id=PROJECT, org_level_id=child_level.org_level_id,
            unit_code="LJCHILD", unit_name="Child District", path="LJROOT.LJCHILD",
        )
        db.session.add_all([root, child])
        db.session.flush()

        # (sid, form, payload, org unit, review comments, collector)
        cls.sids = []
        for sid, form_id, payload, org_unit, comments, collector in (
            (
                "uuid:lj7u-1", FORM_OK,
                {
                    "sid": "uuid:lj7u-1",
                    "unique_id": "omitted-by-policy",
                    "pii_name": "Jane Doe",
                    "note_multiline": "first line\nsecond line",
                    "note_quotes": 'she said "hi", then left',
                    "empty_string": "",
                    "null_value": None,
                    "count": 5,
                    # Read by SmartVA, so they reach the SmartVA input export.
                    "Id10019": "female",
                    "Id10099": 'quoted "x", y\nz',
                    "Id10004": "",
                    "Id10023": None,
                    "Id10120": "flagged-value-xyz",
                },
                child, [{"comment": "check, please"}], "Collector, One",
            ),
            (
                "uuid:lj7u-2", FORM_OK,
                {"sid": "uuid:lj7u-2", "note_multiline": "x", "nested": {"a": [1, "b"]}, "flag": True,
                 "Id10019": "male", "Id10147": "7"},
                root, None, "Collector Two",
            ),
            (
                "uuid:lj7u-3", FORM_UNCONFIRMED,
                {"sid": "uuid:lj7u-3", "withheld_field": "must not leave", "note_multiline": "y",
                 "Id10147": "unconfirmed-form value", "Id10148": "1"},
                None, None, "Collector Three",
            ),
            ("uuid:lj7u-4", FORM_OK, {}, None, None, "Collector Four"),
        ):
            submission = VaSubmissions(
                va_sid=sid, va_form_id=form_id, va_submission_date=T0, va_odk_updatedat=T1,
                va_data_collector=collector, va_odk_reviewstate=None,
                va_odk_reviewcomments=comments, va_instance_name=sid,
                va_uniqueid_real=None, va_uniqueid_masked=sid, va_consent="yes",
                va_narration_language="English", va_deceased_age=42,
                va_deceased_gender="female", va_summary=[], va_catcount={},
                va_category_list=[],
            )
            if org_unit is not None:
                # ck_va_submissions_org_unit_resolution_pair: set both together.
                submission.org_unit_id = org_unit.org_unit_id
                submission.org_unit_resolution = "manual"
            db.session.add(submission)
            db.session.flush()
            ensure_active_payload_version(
                submission, payload_data=payload, source_updated_at=T1,
                created_by_role="vasystem",
            )
            db.session.add(VaSubmissionWorkflow(
                va_sid=sid, workflow_state=WORKFLOW_CODER_FINALIZED,
                workflow_created_at=T0, workflow_updated_at=T1,
            ))
            cls.sids.append(sid)
        # Populates a staff identity column so redaction is not vacuous.
        db.session.add(VaFinalAssessments(
            va_sid="uuid:lj7u-1", va_finassess_by=USER_ID,
            va_conclusive_cod="I21 Acute myocardial infarction",
            va_finassess_status=VaStatuses.active,
            va_finassess_createdat=T0, va_finassess_updatedat=T1,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        mapping = get_mapping_service()
        patchers = [
            patch(
                "app.utils.va_get_form_type_code_for_form",
                side_effect=lambda form_id: "LJ_OK" if form_id == FORM_OK else "LJ_UNCONFIRMED",
            ),
            patch.object(
                mapping, "get_pii_set_status",
                side_effect=lambda code: PII_STATUS.get(code, UNCONFIRMED),
            ),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _golden(self, name):
        with open(GOLDEN_DIR / name, encoding="utf-8", newline="") as handle:
            return handle.read()

    def _submissions(self, *, redact):
        with patch(
            "app.services.data_management_service.should_redact_pii", return_value=redact
        ):
            return dm_submissions_export_csv(self.user, project=PROJECT)

    # -- golden: byte-identical to the pre-streaming output -------------------

    def test_submissions_export_matches_the_golden_file_unredacted(self):
        self.assertEqual(
            _split_records(self._submissions(redact=False), "uuid:lj7u-"),
            _split_records(self._golden("submissions_plain.csv"), "uuid:lj7u-"),
        )

    def test_submissions_export_matches_the_golden_file_redacted(self):
        self.assertEqual(
            _split_records(self._submissions(redact=True), "uuid:lj7u-"),
            _split_records(self._golden("submissions_redacted.csv"), "uuid:lj7u-"),
        )

    def test_smartva_input_export_matches_the_golden_file(self):
        actual = _smartva_view(dm_smartva_input_export_csv(self.user, project=PROJECT))
        self.assertEqual(actual[:2], (SMARTVA_FRONT, "sid"))
        self.assertEqual(actual, _smartva_view(self._golden("smartva_input.csv")))

    def test_export_carries_the_country_stamp(self):
        """rou1: the header has the column and the row cell reads the stamp."""
        from app.services.data_management_service import _dm_submission_export_row

        self.assertIn("va_country_iso3", self._submissions(redact=False).splitlines()[0].split(","))
        self.assertEqual(
            _dm_submission_export_row({"va_country_iso3": "BGD"}, "UTC", False)["va_country_iso3"],
            "BGD",
        )

    def test_the_golden_files_exercise_what_they_are_meant_to(self):
        """Non-vacuity: the fixture really hits each case the goldens pin."""
        plain = self._golden("submissions_plain.csv")
        redacted = self._golden("submissions_redacted.csv")
        smartva = self._golden("smartva_input.csv")
        self.assertIn('"first line\nsecond line"', plain)
        self.assertIn('"she said ""hi"", then left"', plain)
        self.assertIn('Root, ""State"" / Child District', plain)
        self.assertIn("Child District", plain)
        self.assertIn(str(USER_ID), plain)
        self.assertNotIn(str(USER_ID), redacted)
        # Unconfirmed form: payload withheld from the submissions export only.
        self.assertNotIn("must not leave", plain)
        self.assertNotIn("unconfirmed-form value", plain)
        self.assertIn("unconfirmed-form value", smartva)
        self.assertIn('"quoted ""x"", y\nz"', smartva)
        # PII-flagged and omitted fields are stripped everywhere.
        for text in (plain, smartva):
            self.assertNotIn("flagged-value-xyz", text)
            self.assertNotIn("Jane Doe", text)
            self.assertNotIn("omitted-by-policy", text)
        # has_smartva_failed is set on the row but is not an exported column.
        self.assertNotIn("has_smartva_failed", plain)

    # -- the streaming writers -------------------------------------------------

    def test_streaming_writers_give_the_same_text_as_the_string_wrappers(self):
        with patch(
            "app.services.data_management_service.should_redact_pii", return_value=False
        ):
            handle = io.StringIO()
            write_dm_submissions_export_csv(handle, self.user, project=PROJECT)
            wrapped = dm_submissions_export_csv(self.user, project=PROJECT)
        self.assertEqual(
            _split_records(handle.getvalue(), "uuid:lj7u-"),
            _split_records(wrapped, "uuid:lj7u-"),
        )

        handle = io.StringIO()
        write_dm_smartva_input_export_csv(handle, self.user, project=PROJECT)
        self.assertEqual(
            _smartva_view(handle.getvalue()),
            _smartva_view(dm_smartva_input_export_csv(self.user, project=PROJECT)),
        )

    def test_the_export_query_is_streamed_with_yield_per(self):
        seen = []
        sets = []

        def record(conn, cursor, statement, parameters, context, executemany):
            if "payload_data" in statement and statement.lstrip().upper().startswith("SELECT"):
                seen.append(context.execution_options.get("yield_per"))
            if "cursor_tuple_fraction" in statement:
                sets.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", record)
        try:
            self._submissions(redact=False)
            dm_smartva_input_export_csv(self.user, project=PROJECT)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", record)
        # One execution per export, each through a yield_per cursor.
        self.assertEqual(seen, [500, 500])
        # Planned like the buffered query, so the unordered result keeps its order.
        self.assertEqual(len(sets), 2)
        self.assertTrue(all("cursor_tuple_fraction = 1.0" in sql for sql in sets))

    def test_the_spool_is_removed_and_lives_under_the_configured_tmp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = self.app.config.get("DB_BACKUP_TMP_DIR")
            self.app.config["DB_BACKUP_TMP_DIR"] = tmp
            try:
                self._submissions(redact=False)
                dm_smartva_input_export_csv(self.user, project=PROJECT)
            finally:
                self.app.config["DB_BACKUP_TMP_DIR"] = old
            # TemporaryFile is unlinked on creation: nothing may be left behind.
            self.assertEqual(os.listdir(tmp), [])

    # -- the route -----------------------------------------------------------------

    def test_route_stores_a_bom_plus_the_golden_text(self):
        self._login(str(USER_ID))
        with tempfile.TemporaryDirectory() as tmp:
            old = {k: self.app.config.get(k) for k in ("APP_DATA", "DB_BACKUP_TMP_DIR")}
            self.app.config["APP_DATA"] = tmp
            self.app.config["DB_BACKUP_TMP_DIR"] = tmp
            try:
                responses = {
                    "submissions_plain.csv": self.client.get(
                        f"/api/v1/data-management/submissions/export.csv?project={PROJECT}"
                    ),
                    "smartva_input.csv": self.client.get(
                        "/api/v1/data-management/submissions/export-smartva-input.csv"
                        f"?project={PROJECT}"
                    ),
                }
                stored = {
                    path.name: path.read_bytes()
                    for path in Path(tmp, "exports").rglob("*.csv")
                }
            finally:
                for key, value in old.items():
                    self.app.config[key] = value

        self.assertEqual(len(stored), 2)
        for name, response in responses.items():
            self.assertEqual(response.status_code, 200, name)
            self.assertEqual(response.headers["X-Export-Cache"], "MISS", name)
            body = response.get_data()
            self.assertTrue(body.startswith(export_store_service.UTF8_BOM.encode("utf-8")), name)
            if name.startswith("submissions"):
                self.assertEqual(
                    _split_records(body.decode("utf-8"), "uuid:lj7u-"),
                    _split_records(
                        export_store_service.UTF8_BOM + self._golden(name), "uuid:lj7u-"
                    ),
                    name,
                )
            else:
                self.assertEqual(
                    _smartva_view(body.decode("utf-8")), _smartva_view(self._golden(name)), name
                )
            self.assertIn(body, stored.values(), name)

    # -- scratch files never outlive an export ---------------------------------------

    def _recording_temp_files(self):
        """Patch tempfile.TemporaryFile to keep every handle it opens."""
        real = tempfile.TemporaryFile
        opened = []

        def record(*args, **kwargs):
            handle = real(*args, **kwargs)
            opened.append(handle)
            return handle

        return patch("tempfile.TemporaryFile", side_effect=record), opened

    def test_the_spool_is_closed_when_the_export_fails(self):
        patcher, opened = self._recording_temp_files()
        with patcher, patch(
            "app.services.data_management_service.resolve_org_unit_export_labels",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                dm_submissions_export_csv(self.user, project=PROJECT)
        self.assertTrue(opened)
        self.assertTrue(all(handle.closed for handle in opened))

    def test_route_closes_its_scratch_files_on_failure_and_on_bypass(self):
        self._login(str(USER_ID))
        # An empty store, so no earlier export can answer as a cache HIT.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old_app_data = self.app.config.get("APP_DATA")
        self.app.config["APP_DATA"] = tmp.name
        self.addCleanup(self.app.config.__setitem__, "APP_DATA", old_app_data)
        url = f"/api/v1/data-management/submissions/export.csv?project={PROJECT}"

        patcher, opened = self._recording_temp_files()
        with patcher, patch(
            "app.routes.api.data_management.write_dm_submissions_export_csv",
            side_effect=RuntimeError("boom"),
        ):
            try:
                self.assertEqual(self.client.get(url).status_code, 500)
            except RuntimeError:
                pass  # propagated under TESTING
        self.assertTrue(opened)
        self.assertTrue(all(handle.closed for handle in opened))

        patcher, opened = self._recording_temp_files()
        with patcher, patch(
            "app.routes.api.data_management.export_store.write_export",
            side_effect=OSError("store down"),
        ):
            response = self.client.get(url)
            self.assertEqual(response.headers["X-Export-Cache"], "BYPASS")
            body = response.get_data()
            self.assertEqual(response.content_length, len(body))
            response.close()
        self.assertTrue(body.startswith(export_store_service.UTF8_BOM.encode("utf-8")))
        self.assertIn(b"uuid:lj7u-", body)
        self.assertTrue(opened)
        self.assertTrue(all(handle.closed for handle in opened))
