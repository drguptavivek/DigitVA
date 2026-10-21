"""The case list CSV export: GET /api/v1/cases/export.csv (digitva-kzyp stage 5).

Policy: docs/policy/death-registration-identifiers.md decision 9 / "CSV export",
docs/policy/case-list-views.md. Fixture is ``IdentifierFixture`` (tree IDV01,
types ``crs`` and ``mccd``; IDV02 sites project with ``reqd``). Every "absent"
assertion first asserts that its subject is present.
"""
import csv
import io
import logging
import uuid
from datetime import UTC, datetime
from unittest import mock

import sqlalchemy as sa
from flask import current_app

from app import cache, db, limiter
from app.models import (
    AuthDeviceSession,
    MapDeathIdentifier,
    MapIdentifierAudit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services import case_export_service as export
from app.services import case_list_service as case_list
from app.services import case_transition_service as transitions
from app.services import death_identifier_service as ids
from app.services import device_auth_service as devices
from app.services import organization_service as org
from app.services import web_intake_service as intake_svc
from app.utils import pii_crypto
from tests.routes.test_death_identifiers import (
    CASES,
    PROJECT,
    SITE,
    SITES_PROJECT,
    SITES_SITE,
    IdentifierFixture,
    _dod,
    _number,
    _statements,
)

R = VaAccessRoles
URL = f"{CASES}/export.csv"
MCCD = "abc/1234"


class CaseExportTests(IdentifierFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A user who exports for IDV01 and only codes in IDV02: a partial export.
        cls.dmx = cls._get_or_make_user("idv.dmx@test.local", "Identifier123")
        for role, project in ((R.data_manager, PROJECT), (R.coder, SITES_PROJECT)):
            db.session.add(VaUserAccessGrants(
                user_id=cls.dmx.user_id, role=role, grant_status=VaStatuses.active, notes="export",
                scope_type=VaAccessScopeTypes.project, project_id=project))
        # data_manager in IDV01, collaborator_pii in IDV02: values on screen in both, export in one.
        cls.mix = cls._get_or_make_user("idv.dmsup@test.local", "Identifier123")
        for role, project in ((R.data_manager, PROJECT), (R.collaborator_pii, SITES_PROJECT)):
            db.session.add(VaUserAccessGrants(
                user_id=cls.mix.user_id, role=role, grant_status=VaStatuses.active, notes="export",
                scope_type=VaAccessScopeTypes.project, project_id=project))
        # A unit whose name a spreadsheet would run as a formula.
        cls.formula_unit = org.create_unit(
            PROJECT, org_level_id=cls.sca.org_level_id, unit_code="INJ", unit_name="=cmd",
            parent_org_unit_id=cls.sca.parent_org_unit_id)
        db.session.commit()
        cls.crs_one = _number()
        cls.one = cls._case(PROJECT, SITE, cls.wally, cls.sca, {"crs": cls.crs_one, "mccd": MCCD})
        cls.two = cls._case(PROJECT, SITE, cls.wally, cls.formula_unit, {})
        # A value no type rule would accept: the cell must still be neutralised.
        cls.formula_number = "-12345"
        ciphertext, wrapped, key_id = pii_crypto.encrypt_value(
            cls.formula_number, ids.aad(cls.two.death_id, cls.mccd.identifier_type_id))
        db.session.add(MapDeathIdentifier(
            death_id=cls.two.death_id, identifier_type_id=cls.mccd.identifier_type_id, value_ciphertext=ciphertext,
            dek_wrapped=wrapped, value_blind_index=pii_crypto.blind_index(cls.mccd.identifier_type_id.bytes, "x1"),
            key_id=key_id, entered_by=cls.wally.user_id))
        cls.three = intake_svc.register_death(
            cls.wally, project_id=PROJECT, site_id=SITE, org_unit_id=str(cls.sca.org_unit_id),
            deceased_name="Unsubmitted Person", deceased_sex="male", age_years=44, date_of_death=_dod(3),
            identifiers={"crs": _number()})
        cls.reqd_number = "98765432"
        cls.other = cls._case(SITES_PROJECT, SITES_SITE, cls.ivy, None, {"reqd": cls.reqd_number})
        db.session.commit()

    @classmethod
    def _case(cls, project_id, site_id, registrar, unit, identifiers):
        """A submitted register case (so coding reach opens it) with numbers."""
        death = intake_svc.register_death(
            registrar, project_id=project_id, site_id=site_id,
            org_unit_id=str(unit.org_unit_id) if unit else None,
            deceased_name="Submitted Person", deceased_sex="female", age_years=50, date_of_death=_dod(),
            identifiers=identifiers)
        sid = f"uuid:exp-{uuid.uuid4()}"
        now = datetime.now(UTC)
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=f"{project_id}{site_id}01", va_submission_date=now, va_odk_updatedat=now,
            va_data_collector="exp", va_odk_reviewstate="reviewed", va_instance_name=sid, va_uniqueid_real=sid,
            va_uniqueid_masked=sid, va_consent="yes", va_narration_language="English", va_deceased_age=50,
            va_deceased_gender="male", va_summary=[], va_catcount={}, va_category_list=[],
        ))
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(va_sid=sid, workflow_state="ready_for_coding"))
        death.va_sid = sid
        transitions.transition(death, "in_progress", actor=registrar, action="test")
        transitions.transition(death, "submitted", actor=registrar, action="test")
        return death

    # -- helpers ---------------------------------------------------------------

    def _export(self, user, query="", expect=200):
        limiter.reset()
        self._login(str(user.user_id))
        response = self.client.get(URL + query)
        self.assertEqual(response.status_code, expect, (user.email, response.get_data(as_text=True)[:300]))
        return response

    def _rows(self, response):
        text = response.get_data(as_text=True)
        self.assertTrue(text.startswith("﻿"))
        rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
        header = rows[0]
        return header, [dict(zip(header, r, strict=True)) for r in rows[1:]]

    def _audit(self, user=None):
        return db.session.scalars(
            sa.select(MapIdentifierAudit).where(
                MapIdentifierAudit.event == "export_with_identifiers",
                MapIdentifierAudit.actor_user_id == (user or self.dana).user_id)
            .order_by(MapIdentifierAudit.created_at)).all()

    def _device(self, user):
        _row, code = devices.create_enrolment_code(PROJECT, actor=self.admin)
        device, _secret = devices.enrol_device(code, device_name="exp", platform="android", app_version="0.1.0")
        session = AuthDeviceSession(
            device_id=device.device_id, user_id=user.user_id,
            user_session_version=user.auth_session_version or 0, created_at=datetime.now(UTC))
        issued = devices._issue(session)
        db.session.add(session)
        db.session.commit()
        return {"Authorization": f"Bearer {issued.access_token}"}

    # -- who may export -----------------------------------------------------------

    def test_only_data_managers_and_admins_export_browsers_only(self):
        for user in (self.dana, self.admin, self.pip, self.incharge):  # PIs hold the data manager gate
            self.assertIn(str(self.one.unique_id), self._export(user).get_data(as_text=True))
        for user in (self.cody, self.ian, self.sam, self.pat, self.cole, self.rita, self.tess, self.rex):
            self._export(user, expect=403)
        self.assertEqual(self.client.get(CASES + "?limit=1").status_code, 200)  # the list itself still opens
        headers = self._device(self.dana)
        from flask import g
        g.pop("_login_user", None)
        g.pop("device_session", None)
        with self.client.session_transaction() as http_session:
            http_session.clear()
        denied = self.client.get(URL, headers=headers)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.get_json()["code"], "cookie_session_required")
        g.pop("_login_user", None)
        with self.client.session_transaction() as http_session:
            http_session.clear()
        self.assertEqual(self.client.get(URL).status_code, 401)

    def test_response_headers(self):
        response = self._export(self.dana)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertTrue(response.headers["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["X-Identifier-Columns"], "full")
        self.assertEqual(response.headers["X-Accel-Buffering"], "no")

    # -- scope and filters follow the list ----------------------------------------

    def test_same_cases_as_the_list_for_the_same_filters(self):
        queries = ["", "?preset=coding", f"?project_id={PROJECT}", "?status=reported", "?identifier=has",
                   "?identifier=missing&identifier_type=mccd", f"?dod_from={_dod(2)}", "?sex=male",
                   f"?org_unit_id={self.sca.org_unit_id}", "?sort=oldest"]
        for user in (self.dana, self.admin, self.dmx):
            for query in queries:
                self._login(str(user.user_id))
                listed = self.client.get(f"{CASES}{query}{'&' if query else '?'}limit=200").get_json()["cases"]
                _, rows = self._rows(self._export(user, query))
                self.assertEqual({r["death_id"] for r in rows}, {c["death_id"] for c in listed}, (user.email, query))
                self.assertEqual(len(rows), len(listed), (user.email, query))
        _, rows = self._rows(self._export(self.dana))
        ids = {r["death_id"] for r in rows}
        self.assertIn(str(self.one.death_id), ids)  # subject present
        self.assertIn(str(self.three.death_id), ids)
        _, only = self._rows(self._export(self.dana, "?status=reported"))
        self.assertEqual({r["death_id"] for r in only}, {str(self.three.death_id)})

    def test_a_bad_query_is_a_400_and_writes_no_audit_row(self):
        self._export(self.dana, "?identifier=has")
        before = len(self._audit())
        self.assertEqual(before, 1)
        self._export(self.dana, "?preset=nope", expect=400)
        self._export(self.dana, "?identifier_number=" + "9" * 300, expect=400)
        self.assertEqual(len(self._audit()), before)

    # -- the columns -----------------------------------------------------------------

    def test_no_names_contacts_or_coordinates(self):
        response = self._export(self.dana)
        header, rows = self._rows(response)
        self.assertTrue(any(r["unique_id"] == self.one.unique_id for r in rows))
        for forbidden in ("deceased_name", "latitude", "longitude", "informant", "phone", "address", "aadhaar",
                          "national_id", "accuracy_m"):
            self.assertFalse([h for h in header if forbidden in h.lower()], forbidden)
        text = response.get_data(as_text=True)
        self.assertNotIn("Submitted Person", text)
        self.assertNotIn("Unsubmitted Person", text)

    def test_identifier_columns_for_a_data_manager_in_type_order(self):
        header, rows = self._rows(self._export(self.dana))
        tail = header[len(export.COLUMNS):]
        self.assertEqual(tail, ["CRS number", "MCCD number"])  # active types by sort_order; no "Old number"
        by_id = {r["death_id"]: r for r in rows}
        one = by_id[str(self.one.death_id)]
        self.assertEqual((one["CRS number"], one["MCCD number"]), (self.crs_one, MCCD.upper()))
        three = by_id[str(self.three.death_id)]
        self.assertTrue(three["CRS number"])
        self.assertEqual(three["MCCD number"], "")

    def test_admin_exports_numbers_like_everyone_who_sees_values(self):
        # identifier_values_visible: admin sees values in every project.
        response = self._export(self.admin)
        header, rows = self._rows(response)
        self.assertIn("CRS number", header)
        self.assertIn("Required number", header)
        by_id = {r["death_id"]: r for r in rows}
        self.assertEqual(by_id[str(self.one.death_id)]["CRS number"], self.crs_one)
        self.assertEqual(by_id[str(self.other.death_id)]["Required number"], self.reqd_number)
        self._export(self.pip)
        self.assertEqual({a.actor_role for a in self._audit(self.pip)}, {"project_pi"})
        audit = self._audit(self.admin)
        self.assertEqual({a.project_id for a in audit}, {PROJECT, SITES_PROJECT})
        self.assertEqual({a.actor_role for a in audit}, {"admin"})

    def test_partial_multi_project_export_leaves_the_other_projects_cells_empty(self):
        response = self._export(self.dmx)
        header, rows = self._rows(response)
        self.assertEqual(response.headers["X-Identifier-Columns"], "partial")
        self.assertEqual(header[len(export.COLUMNS):], ["CRS number", "MCCD number"])
        by_id = {r["death_id"]: r for r in rows}
        self.assertEqual(by_id[str(self.one.death_id)]["CRS number"], self.crs_one)
        other = by_id[str(self.other.death_id)]  # present: a coder reaches it
        self.assertEqual((other["project_id"], other["CRS number"], other["MCCD number"]), (SITES_PROJECT, "", ""))
        self.assertNotIn(self.reqd_number, response.get_data(as_text=True))
        self.assertNotIn("Required number", header)
        audit = self._audit(self.dmx)
        self.assertEqual([a.project_id for a in audit], [PROJECT])
        self.assertEqual(audit[0].details["columns"], "partial")

    def test_only_the_other_project_gives_no_columns_and_no_audit_row(self):
        response = self._export(self.dmx, f"?project_id={SITES_PROJECT}")
        header, rows = self._rows(response)
        self.assertEqual([r["death_id"] for r in rows], [str(self.other.death_id)])
        self.assertEqual(header, list(export.COLUMNS))
        self.assertNotIn("X-Identifier-Columns", response.headers)
        self.assertEqual(self._audit(self.dmx), [])

    def test_an_exporter_without_pii_access_gets_no_columns_decrypts_nothing_and_leaves_no_row(self):
        with mock.patch.object(export, "export_roles", return_value={}), \
                mock.patch.object(pii_crypto, "decrypt_value", wraps=pii_crypto.decrypt_value) as decrypt:
            response = self._export(self.dana)
        header, rows = self._rows(response)
        self.assertTrue(any(r["death_id"] == str(self.one.death_id) for r in rows))  # present
        self.assertEqual(header, list(export.COLUMNS))
        self.assertNotIn("X-Identifier-Columns", response.headers)
        self.assertNotIn(self.crs_one, response.get_data(as_text=True))
        self.assertEqual(self._audit(), [])
        decrypt.assert_not_called()

    def test_only_data_manager_pi_and_admin_grants_export_numbers(self):
        self.assertEqual(export.export_roles(self.mix, {PROJECT, SITES_PROJECT}), {PROJECT: "data_manager"})
        response = self._export(self.mix)
        header, rows = self._rows(response)
        by_id = {r["death_id"]: r for r in rows}
        self.assertEqual(by_id[str(self.one.death_id)]["CRS number"], self.crs_one)
        other = by_id.get(str(self.other.death_id))
        self.assertIsNotNone(other)  # present: reached by the collaborator grant, still no number
        self.assertEqual((other["CRS number"], other["MCCD number"]), ("", ""))
        self.assertNotIn(self.reqd_number, response.get_data(as_text=True))
        self.assertNotIn("Required number", header)
        self.assertEqual([(a.project_id, a.actor_role) for a in self._audit(self.mix)], [(PROJECT, "data_manager")])
        self.assertEqual(response.headers["X-Identifier-Columns"], "partial")

    def test_a_number_that_fails_to_decrypt_is_a_500_before_any_row_body_or_audit(self):
        self.assertEqual(self._audit(), [])
        self.assertGreaterEqual(len(self._rows(self._export(self.dana))[1]), 2)  # healthy first: present
        before = len(self._audit())
        failing = pii_crypto.PiiCryptoError("row-id key-id")
        with self.assertLogs("app.services.case_export_service", level="ERROR") as logs, \
                mock.patch.object(pii_crypto, "decrypt_value", side_effect=failing):
            response = self._export(self.dana, expect=500)
        self.assertEqual(response.get_json()["code"], "export_unreadable")
        self.assertIn("failed to decrypt", "\n".join(logs.output))
        self.assertNotIn(self.crs_one, response.get_data(as_text=True))
        self.assertNotIn("death_id", response.get_data(as_text=True))  # no CSV header either
        self.assertEqual(len(self._audit()), before)  # no audit row
        self.assertTrue(cache.add(f"cases-export:{self.dana.user_id}", 1, timeout=60))  # lock was released
        cache.delete(f"cases-export:{self.dana.user_id}")

    def test_over_the_row_cap_is_413_before_streaming_and_writes_no_row(self):
        self.assertGreaterEqual(len(self._rows(self._export(self.dana))[1]), 2)  # present
        before = len(self._audit())
        with mock.patch.dict(current_app.config, {"EXPORT_MAX_ROWS": 1}):
            response = self._export(self.dana, expect=413)
        self.assertEqual(response.get_json()["code"], "export_too_large")
        self.assertEqual(len(self._audit()), before)

    def test_one_running_export_per_user(self):
        key = f"cases-export:{self.dana.user_id}"
        self.assertTrue(cache.add(key, 1, timeout=60))
        try:
            response = self._export(self.dana, expect=429)
            self.assertEqual(response.get_json()["code"], "export_in_progress")
            self._export(self.pip)  # another user is not blocked
        finally:
            cache.delete(key)
        self._export(self.dana)  # the finished export released its slot
        self.assertTrue(cache.add(key, 1, timeout=60))
        cache.delete(key)

    # -- audit -----------------------------------------------------------------------

    def test_one_audit_row_per_export_with_the_right_fields_and_no_value(self):
        self._export(self.dana, f"?status=submitted_awaiting_coding&identifier_number={self.crs_one}")
        rows = self._audit()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row.project_id, row.actor_role), (PROJECT, "data_manager"))
        self.assertEqual(row.details["row_count"], 1)
        self.assertEqual(row.details["type_codes"], ["crs", "mccd"])
        self.assertEqual(row.details["filters"]["identifier_number"], True)
        self.assertEqual(row.details["filters"]["statuses"], ["submitted_awaiting_coding"])
        self.assertNotIn(self.crs_one, repr(row.details))
        self.assertNotIn(MCCD, repr(row.details).lower())
        self._export(self.dana)
        self.assertEqual(len(self._audit()), 2)

    def test_the_audit_row_exists_when_the_stream_fails_midway(self):
        # The validation pass is skipped to simulate a value that broke after it.
        with mock.patch.object(export, "_first_unreadable", return_value=None), \
                mock.patch.object(pii_crypto, "decrypt_value", side_effect=pii_crypto.PiiCryptoError("row key")):
            try:
                self._export(self.dana)
            except export.ExportDecryptError:
                pass  # the failure may surface in the client or truncate the body
        self.assertEqual(len(self._audit()), 1)

    # -- injection, batching, decrypt, logs ----------------------------------------------

    def test_formula_cells_get_a_leading_apostrophe(self):
        _, rows = self._rows(self._export(self.dana))
        row = next(r for r in rows if r["death_id"] == str(self.two.death_id))  # present
        self.assertEqual(row["unit_name"], "'=cmd")
        self.assertEqual(row["MCCD number"], "'" + self.formula_number)
        self.assertEqual(export.safe_cell("+1"), "'+1")
        self.assertEqual(export.safe_cell("@x"), "'@x")
        self.assertEqual(export.safe_cell("\tx"), "'\tx")
        self.assertEqual(export.safe_cell("\n=x"), "'\n=x")
        self.assertEqual(export.safe_cell("  =x"), "'  =x")
        self.assertEqual(export.safe_cell(" \t@x"), "' \t@x")
        self.assertEqual(export.safe_cell("a=b"), "a=b")
        self.assertEqual(export.safe_cell("  plain"), "  plain")
        self.assertEqual(export.safe_cell(None), "")
        self.assertEqual(export.safe_cell(7), 7)

    def test_statements_per_batch_are_constant(self):
        def run(batch):
            with mock.patch.object(export, "BATCH", batch), _statements() as found:
                _, rows = self._rows(self._export(self.dana))
            return len(found), len(rows)

        run(100)  # warm the per-request caches
        big, n = run(100)
        self.assertGreaterEqual(n, 3)
        one_each, _ = run(1)
        two_each, _ = run(2)
        batches = {1: n, 2: -(-n // 2), 100: 1}
        per_batch_one = (one_each - big) / (batches[1] - 1)
        per_batch_two = (two_each - big) / (batches[2] - 1)
        self.assertEqual(per_batch_one, per_batch_two)
        self.assertGreater(per_batch_one, 0)
        self.assertEqual(per_batch_one, int(per_batch_one))

    def test_decrypts_only_values_of_qualifying_projects(self):
        with mock.patch.object(pii_crypto, "decrypt_value", wraps=pii_crypto.decrypt_value) as decrypt:
            _, rows = self._rows(self._export(self.dmx))
        filled = sum(bool(r[h]) for r in rows for h in ("CRS number", "MCCD number"))
        self.assertGreaterEqual(filled, 3)
        # twice (validation pass, then the stream), none for the IDV02 row
        self.assertEqual(decrypt.call_count, 2 * filled)

    def test_no_plaintext_in_the_logs(self):
        with self.assertLogs(level="DEBUG") as logs:
            logging.getLogger("test").debug("export start")
            self._export(self.dana, f"?identifier_number={self.crs_one}")
            self._export(self.admin)
        text = "\n".join(logs.output)
        for needle in (self.crs_one, MCCD, MCCD.upper(), self.reqd_number, self.formula_number):
            self.assertNotIn(needle, text)

    # -- JIT off for counts and tiles -------------------------------------------------------

    def test_counts_run_with_jit_off_and_put_it_back(self):
        def jit():
            return db.session.scalar(sa.text("SELECT current_setting('jit')"))

        before = jit()
        self._login(str(self.dana.user_id))
        with self.app.test_request_context("/"), _statements() as found:
            counts = case_list.case_list_counts(self.dana, preset="deaths", filters=case_list.CaseFilters())
        self.assertGreaterEqual(counts["counts"]["total"], 3)  # present
        off = next(i for i, s in enumerate(found) if "SET LOCAL jit = off" in s)
        scan = next(i for i, s in enumerate(found) if "count(*) FILTER" in s)
        restore = next(i for i, s in enumerate(found) if "set_config('jit'" in s)
        self.assertLess(off, scan)
        self.assertLess(scan, restore)
        self.assertEqual(jit(), before)
        # The page statement never sees the setting turned off.
        self.assertFalse([s for s in found[restore + 1:] if "SET LOCAL jit" in s])
