"""Golden files for the five data-manager CSV exports (digitva-r8nh.15).

Every exporter in data_management_service is pinned byte for byte against a
file under tests/fixtures/dm_export_golden, generated from the code BEFORE the
exporters were rewritten as column specs. A changed byte is a changed export.

The fixture exercises: None and empty values; commas, quotes and newlines in
text; Devanagari; datetimes whose UTC day differs from the user's and the
project's local day; staff identity redacted in one project and not in the
other; the spreadsheet formula guard (and the raw SmartVA input that skips
it); payload keys that collide with base and org-unit headers; ICD-11 stems
with and without a linearization URI; and an export with no rows.

Row order: only the COD snapshot query has an ORDER BY, so its file is
compared whole. The other four queries are unordered; for them the header and
every record are compared byte for byte, as a multiset (see
tests/services/test_dm_export_streaming.py for why).

Regenerate (only on purpose, on the code whose output you mean to pin):
DM_EXPORT_GOLDEN_REGEN=1 python -m pytest tests/services/test_dm_export_golden.py
"""
import io
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    MasIcd11Mms,
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
    VaSmartvaResults,
    VaSmartvaRun,
    VaSmartvaRunOutput,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import export_store_service
from app.services.data_management_service import (
    dm_coded_cod_snapshot_export_csv,
    dm_smartva_likelihoods_export_csv,
    dm_smartva_results_export_csv,
    write_dm_smartva_input_export_csv,
    write_dm_submissions_export_csv,
)
from app.services.field_mapping_service import PiiSetStatus, get_mapping_service
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE
from app.services.submission_analytics_mv import COD_SNAPSHOT_MV_NAME
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.viewer_pii_service import PiiScope
from app.services.workflow.definition import WORKFLOW_CODER_FINALIZED
from tests.base import BaseTestCase

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "dm_export_golden"
REGEN = os.environ.get("DM_EXPORT_GOLDEN_REGEN") == "1"

P1 = "GLD001"  # Asia/Kolkata clock, PII visible in the "mixed" scope
P2 = "GLD002"  # UTC clock, PII redacted in the "mixed" scope
SITE1 = "GD1A"
SITE1B = "GD1B"
SITE2 = "GD2A"
FORM_OK = "GLD001GD1A01"
FORM_UNCONFIRMED = "GLD001GD1B01"
FORM_P2 = "GLD002GD2A01"
DM_ID = uuid.UUID("aaaaaaaa-1111-2222-3333-444444444444")
CODER_ID = uuid.UUID("bbbbbbbb-1111-2222-3333-444444444444")
SID = "uuid:gld-"

#: 20:00 UTC is the next calendar day in Asia/Kolkata (user and P1 clock).
T0 = datetime(2031, 3, 10, 20, 0, tzinfo=UTC)
T1 = datetime(2031, 3, 11, 6, 15, 30, 123456, tzinfo=UTC)
T2 = datetime(2031, 3, 9, 18, 29, 59, tzinfo=UTC)

PII_STATUS = {
    "GLD_OK": PiiSetStatus(
        confirmed=True, field_ids=frozenset({"pii_name"}), owned_flagged_count=1
    ),
}
UNCONFIRMED = PiiSetStatus(confirmed=False, field_ids=frozenset(), owned_flagged_count=0)

SCOPES = {
    "plain": PiiScope(everywhere=True),
    "mixed": PiiScope(project_ids=frozenset({P1})),
    "redacted": PiiScope(),
}

DEVANAGARI = 'मृत्यु का कारण, "हृदय"\nदूसरी पंक्ति'


def _records(text, prefix):
    """Header line plus whole records (a cell may hold a newline), order dropped."""
    header, *records = re.split(rf"(?m)^(?={re.escape(prefix)})", text)
    return header, sorted(records)


class DmExportGoldenTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id, tz in ((P1, "Asia/Kolkata"), (P2, "UTC")):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=f"Golden {project_id}",
                project_nickname=f"Golden{project_id}", project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, timezone=tz,
            ))
            db.session.add(VaResearchProjects(
                project_id=project_id, project_code=project_id, project_name=f"Golden {project_id}",
                project_nickname=f"Golden{project_id}", project_status=VaStatuses.active,
            ))
        sites = ((P1, SITE1, FORM_OK), (P1, SITE1B, FORM_UNCONFIRMED), (P2, SITE2, FORM_P2))
        for _project, site_id, _form in sites:
            db.session.add(VaSiteMaster(
                site_id=site_id, site_name=f"Site {site_id}", site_abbr=site_id,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        for project_id, site_id, _form in sites:
            db.session.add(VaSites(
                site_id=site_id, project_id=project_id, site_name=f"Site {site_id}",
                site_abbr=site_id, site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        for project_id, site_id, form_id in sites:
            db.session.add(VaProjectSites(
                project_id=project_id, site_id=site_id, project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
            db.session.add(VaForms(
                form_id=form_id, project_id=project_id, site_id=site_id,
                odk_form_id=f"ODK_{site_id}", odk_project_id="398",
                form_type="WHO VA 2022", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        db.session.flush()

        cls.dm = VaUsers(
            user_id=DM_ID, name="gld.dm", email="gld.dm@test.local",
            vacode_language=["English"], permission={}, landing_page="data_manager",
            pw_reset_t_and_c=True, email_verified=True, user_status=VaStatuses.active,
            timezone="Asia/Kolkata",
        )
        cls.dm.set_password("GldDm123")
        coder = VaUsers(
            user_id=CODER_ID, name='Coder, "Devi" देवी', email="gld.coder@test.local",
            vacode_language=["English"], permission={}, landing_page="coder",
            pw_reset_t_and_c=True, email_verified=True, user_status=VaStatuses.active,
            timezone="UTC",
        )
        coder.set_password("GldCoder123")
        db.session.add_all([cls.dm, coder])
        db.session.flush()
        for project_id in (P1, P2):
            db.session.add(VaUserAccessGrants(
                user_id=DM_ID, role=VaAccessRoles.data_manager,
                scope_type=VaAccessScopeTypes.project, project_id=project_id,
                grant_status=VaStatuses.active,
            ))

        level1 = MasOrgLevel(project_id=P1, level_code="gldstate", level_name="State", depth=1)
        level2 = MasOrgLevel(project_id=P1, level_code="glddist", level_name="District", depth=2)
        db.session.add_all([level1, level2])
        db.session.flush()
        root = MasOrgUnit(
            project_id=P1, org_level_id=level1.org_level_id,
            unit_code="GLDROOT", unit_name='राज्य, "State"', path="GLDROOT",
        )
        child = MasOrgUnit(
            project_id=P1, org_level_id=level2.org_level_id,
            unit_code="GLDCHILD", unit_name="Child\nDistrict", path="GLDROOT.GLDCHILD",
        )
        db.session.add_all([root, child])
        db.session.flush()

        rich_payload = {
            "sid": f"{SID}1",
            "unique_id": "omitted-by-policy",
            "pii_name": "Jane Doe",
            "note": DEVANAGARI,
            "note_quotes": 'she said "hi", then left',
            "empty_string": "",
            "null_value": None,
            "count": 5,
            "ratio": 0.25,
            "flag": False,
            "nested": {"b": [1, "दो"], "a": None},
            "formula_eq": "=SUM(A1:A2)",
            "formula_neg": "-5",
            # Collide with a base header and an org-unit header.
            "site_id": "payload-site",
            "org_unit_name": "payload-org",
            "Id10476": "Narrative, \"नरेटिव\"\nline two",
            "Id10019": "female",
            "Id10023": None,
            "Id10120": "=cmd|' /C calc'!A0",
        }
        submissions = (
            # (n, form, payload, org unit, submitted at, consent, language, comments)
            (1, FORM_OK, rich_payload, child, T0, "yes", "हिन्दी", [{"comment": "check, \"please\"\nnow"}]),
            (2, FORM_P2, {"sid": f"{SID}2", "note": "x", "Id10019": "male", "Id10147": "7"},
             None, T1, "", "", None),
            (3, FORM_UNCONFIRMED, {"sid": f"{SID}3", "withheld": "must not leave", "Id10147": "-1"},
             None, T0, "no", "English", "plain comment"),
            (4, FORM_OK, {}, root, T2, "=cmd", "", []),
        )
        for n, form_id, payload, org_unit, submitted, consent, language, comments in submissions:
            sid = f"{SID}{n}"
            submission = VaSubmissions(
                va_sid=sid, va_form_id=form_id, va_submission_date=submitted, va_odk_updatedat=T1,
                va_data_collector=f"Collector {n}, field", va_odk_reviewstate="hasIssues" if n == 1 else None,
                va_odk_reviewcomments=comments, va_instance_name=sid,
                va_uniqueid_real=None, va_uniqueid_masked=f"GLD-{n}", va_consent=consent,
                va_narration_language=language, va_deceased_age=42 if n != 4 else 0,
                va_deceased_gender="female" if n % 2 else "male",
                va_deceased_age_normalized_days=15340.5 if n == 1 else None,
                va_summary=[], va_catcount={}, va_category_list=[],
            )
            if org_unit is not None:
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
        db.session.flush()

        # Staff identity (ids in the submissions export, names in the snapshot)
        # in both projects, so a mixed scope redacts one row and not the other.
        for n, cod, remark in (
            (1, '1B10 Tuberculosis, "pulmonary"', "remark, with comma\nand newline"),
            (2, "8A00 Epilepsy", None),
        ):
            db.session.add(VaFinalAssessments(
                va_sid=f"{SID}{n}", va_finassess_by=CODER_ID, va_conclusive_cod=cod,
                va_finassess_remark=remark, va_finassess_status=VaStatuses.active,
                va_finassess_createdat=T0, va_finassess_updatedat=T1,
            ))
        # 1B10 has a linearization URI; 8A00 has none, so its URI cell is empty.
        db.session.add(MasIcd11Mms(
            release=DEFAULT_ICD11_RELEASE,
            linearization_uri="http://id.who.int/icd/release/11/mms/88616000",
            code="1B10", title="Tuberculosis of the respiratory system",
            class_kind="category", source_version="golden",
        ))

        runs = {}
        for n, outcome in ((1, VaSmartvaResults.OUTCOME_SUCCESS), (2, VaSmartvaResults.OUTCOME_FAILED)):
            run = VaSmartvaRun(
                va_sid=f"{SID}{n}", trigger_source="golden", va_smartva_outcome=outcome,
                va_smartva_run_started_at=T0, va_smartva_run_completed_at=T1,
                va_smartva_run_updated_at=T1,
            )
            db.session.add(run)
            db.session.flush()
            runs[n] = run.va_smartva_run_id
        db.session.add(VaSmartvaResults(
            va_sid=f"{SID}1", smartva_run_id=runs[1], va_smartva_status=VaStatuses.active,
            va_smartva_outcome=VaSmartvaResults.OUTCOME_SUCCESS, va_smartva_resultfor="for_adult",
            va_smartva_age="42", va_smartva_gender="female",
            va_smartva_cause1="=HYPERLINK(\"x\")", va_smartva_likelihood1="0.78",
            va_smartva_keysymptom1=DEVANAGARI, va_smartva_cause1icd="I21",
            va_smartva_cause2="Stroke, \"ischemic\"", va_smartva_likelihood2="",
            va_smartva_allsymptoms="fever, cough", va_smartva_addedat=T0, va_smartva_updatedat=T1,
        ))
        db.session.add(VaSmartvaResults(
            va_sid=f"{SID}2", smartva_run_id=runs[2], va_smartva_status=VaStatuses.active,
            va_smartva_outcome=VaSmartvaResults.OUTCOME_FAILED, va_smartva_failure_stage="prep",
            va_smartva_failure_detail="bad value -1\nsecond line",
            va_smartva_addedat=T2, va_smartva_updatedat=T2,
        ))
        db.session.flush()
        for n, index, payload in (
            (1, 0, {"sid": f"{SID}1", "cause_a": "0.5", "workflow_state": "collides", "मान": 'x, "y"\nz', "neg": "-1"}),
            (1, 1, {"sid": f"{SID}1", "cause_a": None, "cause_b": [0.1, "दो"]}),
            (2, 0, {"cause_b": {"k": 1}, "zeta": ""}),
        ):
            db.session.add(VaSmartvaRunOutput(
                va_smartva_run_id=runs[n], output_kind="likelihood_row",
                output_source_name="likelihoods, \"adult\".csv", output_row_index=index,
                output_sid=f"{SID}{n}", output_resultfor="adult" if n == 1 else None,
                output_payload=payload,
            ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        mapping = get_mapping_service()
        patchers = [
            patch(
                "app.utils.va_get_form_type_code_for_form",
                side_effect=lambda form_id: "GLD_UNCONFIRMED" if form_id == FORM_UNCONFIRMED else "GLD_OK",
            ),
            patch.object(
                mapping, "get_pii_set_status",
                side_effect=lambda code: PII_STATUS.get(code, UNCONFIRMED),
            ),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    # -- running the exporters ---------------------------------------------------

    def _export(self, kind, scope="plain", **filters):
        with patch("app.services.data_management_service.pii_scope", return_value=SCOPES[scope]):
            if kind == "submissions":
                handle = io.StringIO()
                write_dm_submissions_export_csv(handle, self.dm, **filters)
                return handle.getvalue()
            if kind in ("smartva_input", "smartva_input_raw"):
                handle = io.StringIO()
                write_dm_smartva_input_export_csv(
                    handle, self.dm, raw=kind == "smartva_input_raw", **filters
                )
                return handle.getvalue()
            if kind == "smartva_results":
                return dm_smartva_results_export_csv(self.dm, **filters)
            if kind == "smartva_likelihoods":
                return dm_smartva_likelihoods_export_csv(self.dm, **filters)
            if kind == "cod_snapshot":
                # The class transaction rolls back DDL, so the export builds
                # the MV itself, from this fixture (docs/policy/test-harness.md).
                db.session.execute(
                    sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {COD_SNAPSHOT_MV_NAME} CASCADE")
                )
                db.session.commit()
                return dm_coded_cod_snapshot_export_csv(self.dm, **filters)
        raise AssertionError(kind)

    def _golden_bytes(self, name, actual: str) -> bytes:
        path = GOLDEN_DIR / name
        if REGEN:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(actual.encode("utf-8"))
        return path.read_bytes()

    def _assert_golden(self, name, actual: str, record_prefix: str | None):
        """Exact bytes when the export is ordered; header plus record multiset otherwise."""
        golden = self._golden_bytes(name, actual)
        if record_prefix is None:
            self.assertEqual(actual.encode("utf-8"), golden)
        else:
            self.assertEqual(
                _records(actual, record_prefix),
                _records(golden.decode("utf-8"), record_prefix),
            )
            # The multiset compare must not hide a length change.
            self.assertEqual(len(actual.encode("utf-8")), len(golden))

    # -- goldens -------------------------------------------------------------------

    def test_submissions_export_per_scope(self):
        for scope in SCOPES:
            with self.subTest(scope=scope):
                self._assert_golden(f"submissions_{scope}.csv", self._export("submissions", scope), SID)

    def test_smartva_input_export_guarded_and_raw(self):
        # Rows start with project_id; no multi-line cell starts a line with "GLD00".
        for kind in ("smartva_input", "smartva_input_raw"):
            with self.subTest(kind=kind):
                self._assert_golden(f"{kind}.csv", self._export(kind), "GLD00")

    def test_smartva_results_export(self):
        self._assert_golden("smartva_results.csv", self._export("smartva_results"), SID)

    def test_smartva_likelihoods_export(self):
        self._assert_golden("smartva_likelihoods.csv", self._export("smartva_likelihoods"), SID)

    def test_cod_snapshot_export_per_scope(self):
        for scope in SCOPES:
            with self.subTest(scope=scope):
                self._assert_golden(f"cod_snapshot_{scope}.csv", self._export("cod_snapshot", scope), None)

    def test_every_export_with_no_rows(self):
        for kind in (
            "submissions", "smartva_input", "smartva_input_raw",
            "smartva_results", "smartva_likelihoods", "cod_snapshot",
        ):
            with self.subTest(kind=kind):
                self._assert_golden(f"empty_{kind}.csv", self._export(kind, site="NOSUCH"), None)

    def test_the_route_adds_the_bom_to_every_export_but_smartva_input(self):
        self._login(str(DM_ID))
        routes = {
            "submissions_plain.csv": ("export.csv", True, SID),
            "smartva_input.csv": ("export-smartva-input.csv", False, "GLD00"),
            "smartva_input_raw.csv": ("export-smartva-input.csv?for_processing=1", False, "GLD00"),
            "smartva_results.csv": ("export-smartva-results.csv", True, SID),
            "smartva_likelihoods.csv": ("export-smartva-likelihoods.csv", True, SID),
            "cod_snapshot_plain.csv": ("export-coded-cod-snapshot.csv", True, None),
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "app.services.data_management_service.pii_scope", return_value=SCOPES["plain"]
        ):
            old = {k: self.app.config.get(k) for k in ("APP_DATA", "DB_BACKUP_TMP_DIR")}
            self.app.config["APP_DATA"] = tmp
            self.app.config["DB_BACKUP_TMP_DIR"] = tmp
            try:
                for name, (path, bom, prefix) in routes.items():
                    with self.subTest(name=name):
                        if name.startswith("cod_snapshot"):
                            db.session.execute(sa.text(
                                f"DROP MATERIALIZED VIEW IF EXISTS {COD_SNAPSHOT_MV_NAME} CASCADE"
                            ))
                            db.session.commit()
                        response = self.client.get(f"/api/v1/data-management/submissions/{path}")
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.headers["X-Export-Cache"], "MISS")
                        body = response.get_data()
                        response.close()
                        golden = (GOLDEN_DIR / name).read_bytes()
                        expected = (
                            export_store_service.UTF8_BOM.encode("utf-8") if bom else b""
                        ) + golden
                        if prefix is None:
                            self.assertEqual(body, expected)
                        else:
                            self.assertEqual(len(body), len(expected))
                            self.assertEqual(
                                _records(body.decode("utf-8"), prefix),
                                _records(expected.decode("utf-8"), prefix),
                            )
            finally:
                for key, value in old.items():
                    self.app.config[key] = value

    # -- the fixture hits what the goldens are meant to pin -------------------------

    def test_the_golden_files_exercise_what_they_are_meant_to(self):
        def text(name):
            return (GOLDEN_DIR / name).read_bytes().decode("utf-8")

        plain, mixed, redacted = (text(f"submissions_{s}.csv") for s in ("plain", "mixed", "redacted"))
        coder_id = str(CODER_ID)
        self.assertEqual(plain.count(coder_id), 2)
        self.assertEqual(mixed.count(coder_id), 1)
        self.assertNotIn(coder_id, redacted)
        self.assertIn("दूसरी पंक्ति", plain)
        self.assertIn('"she said ""hi"", then left"', plain)
        self.assertIn("'=SUM(A1:A2)", plain)  # payload cell guarded
        self.assertIn(",=cmd,", plain)  # raw base cell not guarded
        # Header collisions: a column listed twice carries the value written
        # last for both cells (payload beats base, org-unit label beats payload).
        header = plain.splitlines()[0].split(",")
        self.assertEqual(header.count("site_id"), 2)
        self.assertEqual(header.count("org_unit_name"), 2)
        self.assertEqual(plain.count("payload-site"), 2)
        self.assertNotIn("payload-org", plain)
        likelihoods_header = text("smartva_likelihoods.csv").splitlines()[0].split(",")
        self.assertEqual(likelihoods_header.count("workflow_state"), 2)
        self.assertIn("Child\nDistrict", plain)
        self.assertNotIn("must not leave", plain)
        self.assertNotIn("Jane Doe", plain)
        self.assertNotIn("omitted-by-policy", plain)
        # 20:00 UTC on the 10th is the 11th in the user's Asia/Kolkata clock.
        self.assertIn("2031-03-11 01:30:00", plain)

        guarded, raw = text("smartva_input.csv"), text("smartva_input_raw.csv")
        self.assertIn("'-1", guarded)
        self.assertNotIn("'-1", raw)
        self.assertIn("-1", raw)

        results = text("smartva_results.csv")
        self.assertIn("'=HYPERLINK", results)
        self.assertIn("दूसरी पंक्ति", results)
        likelihoods = text("smartva_likelihoods.csv")
        self.assertIn("collides", likelihoods)
        self.assertIn("'-1", likelihoods)
        self.assertEqual(likelihoods.count(SID + "1,"), 2)

        snap_plain, snap_mixed, snap_redacted = (
            text(f"cod_snapshot_{s}.csv") for s in ("plain", "mixed", "redacted")
        )
        self.assertEqual(snap_plain.count("Devi"), 2)
        self.assertEqual(snap_mixed.count("Devi"), 1)
        self.assertNotIn("Devi", snap_redacted)
        self.assertIn("http://id.who.int/icd/release/11/", snap_plain)
        self.assertIn("CC BY-ND 3.0 IGO", snap_plain.strip().splitlines()[-1])
        # Four rows, so ORDER BY submission_at desc, va_sid asc is pinned.
        self.assertEqual(len(re.findall(rf"(?m)^{re.escape(SID)}", snap_plain)), 4)

        for kind in ("submissions", "smartva_input", "smartva_results", "smartva_likelihoods"):
            self.assertNotIn(SID, text(f"empty_{kind}.csv"))
