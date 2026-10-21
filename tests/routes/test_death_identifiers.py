"""Registration identifiers, stage 2: writes at registration and correction, reads.

Policy: docs/policy/death-registration-identifiers.md (bead digitva-kzyp).
Tree IDV01 (site IV01): DST > CH1 > PH1 > SCA, SCB and CH1 > PH2 > SCC, with
types ``crs`` (digits, project-unique), ``mccd`` (letters, digits, hyphen,
slash; not unique), an inactive ``old``; IDV02 (site IV02, sites mode) holds
``reqd``. Every "absent" assertion first asserts that the subject is present.
"""
import itertools
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from unittest import mock

import sqlalchemy as sa
from sqlalchemy import event

from app import db, limiter
from app.models import (
    MapCaseTransition,
    MapDeathIdentifier,
    MasDeathIdentifierType,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import case_transition_service as transitions
from app.services import death_identifier_service as ids
from app.services import organization_service as org
from app.services import web_intake_service as intake_svc
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from app.utils import pii_crypto
from tests.base import BaseTestCase

R = VaAccessRoles
PROJECT, SITE = "IDV01", "IV01"
SITES_PROJECT, SITES_SITE = "IDV02", "IV02"
API = "/api/v1/intake"
CASES = "/api/v1/cases"
_numbers = itertools.count(10_000_000 + uuid.uuid4().int % 50_000_000)


def _number() -> str:
    """A fresh 8-digit CRS number, so tests never collide on duplicates."""
    return str(next(_numbers))


def _dod(days=10):
    return (date.today() - timedelta(days=days)).isoformat()


@contextmanager
def _statements():
    found = []

    def record(conn, cursor, statement, *args):
        found.append(statement)

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        yield found
    finally:
        event.remove(db.engine, "before_cursor_execute", record)


class IdentifierFixture(BaseTestCase):
    """The tree, types, users and request helpers the identifier test classes
    share (this file and test_death_identifier_access.py); no test of its own."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id, site_id, mode in ((PROJECT, SITE, "organization"), (SITES_PROJECT, SITES_SITE, "sites")):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=f"Project {project_id}",
                project_nickname=project_id, project_status=VaStatuses.active, project_registered_at=now,
                project_updated_at=now, web_intake_mode="both", project_structure_mode=mode,
            ))
            db.session.add(VaSiteMaster(
                site_id=site_id, site_name=f"Site {site_id}", site_abbr=site_id, site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        for project_id, site_id in ((PROJECT, SITE), (SITES_PROJECT, SITES_SITE)):
            db.session.add(VaProjectSites(
                project_id=project_id, site_id=site_id, project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
            db.session.flush()
            _ensure_legacy_project_site_rows(project_id, site_id)
            db.session.add(VaForms(
                form_id=f"{project_id}{site_id}01", project_id=project_id, site_id=site_id,
                odk_form_id=f"ODK_{project_id}", odk_project_id="7", form_type="WHO VA 2022", form_source="odk",
                form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
            ))
        db.session.flush()

        org.seed_default_organization(PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(PROJECT)}
        cls.cadres = {c.cadre_code: c for c in org.list_cadres(PROJECT)}

        def unit(code, level, parent=None):
            return org.create_unit(
                PROJECT, org_level_id=levels[level].org_level_id, unit_code=code, unit_name=f"Unit {code}",
                parent_org_unit_id=parent.org_unit_id if parent else None,
            )

        dst = unit("DST", "district")
        ch1 = unit("CH1", "chc", dst)
        ph1, ph2 = unit("PH1", "phc", ch1), unit("PH2", "phc", ch1)
        cls.sca, cls.scb = unit("SCA", "subcentre", ph1), unit("SCB", "subcentre", ph1)
        cls.scc = unit("SCC", "subcentre", ph2)
        org.upsert_level_cadre(
            PROJECT, org_level_id=levels["phc"].org_level_id, cadre_id=cls.cadres["MO"].cadre_id,
            can_fill_va_form=False, can_code_va_form=True, can_supervise_interviews=True,
        )

        def type_row(project_id, code, label, sort, **kw):
            row = MasDeathIdentifierType(project_id=project_id, code=code, label=label, sort_order=sort, **kw)
            db.session.add(row)
            return row

        cls.crs = type_row(PROJECT, "crs", "CRS number", 1, min_length=6, max_length=12, char_type="digits")
        cls.mccd = type_row(PROJECT, "mccd", "MCCD number", 2, min_length=4, max_length=20,
                            char_type="letters_digits_hyphen_slash", uniqueness_scope="none")
        cls.old = type_row(PROJECT, "old", "Old number", 3, min_length=2, max_length=10, is_active=False)
        cls.reqd = type_row(SITES_PROJECT, "reqd", "Required number", 1, min_length=4, max_length=8,
                            char_type="digits")
        db.session.flush()

        def user(key, *grants):
            person = cls._get_or_make_user(f"idv.{key}@test.local", "Identifier123")
            for role, scope, cadre in grants:
                kind, target = scope
                row = {"scope_type": kind}
                if kind == VaAccessScopeTypes.org_unit:
                    row["org_unit_id"] = target.org_unit_id
                else:
                    row["project_id"] = target
                if cadre:
                    row["cadre_id"] = cls.cadres[cadre].cadre_id
                db.session.add(VaUserAccessGrants(
                    user_id=person.user_id, role=role, grant_status=VaStatuses.active, notes="identifiers", **row))
            return person

        whole = (VaAccessScopeTypes.project, PROJECT)
        at_ph1 = (VaAccessScopeTypes.org_unit, ph1)
        at_sca = (VaAccessScopeTypes.org_unit, cls.sca)
        elsewhere = (VaAccessScopeTypes.project, SITES_PROJECT)
        cls.ian = user("ian", (R.interviewer, at_ph1, None))
        cls.wally = user("wally", (R.interviewer, whole, None))
        cls.rita = user("rita", (R.death_reporter, at_sca, "ANM"))
        cls.sam = user("sam", (R.interview_supervisor, at_ph1, "MO"))
        cls.dana = user("dana", (R.data_manager, whole, None))
        cls.pip = user("pip", (R.project_pi, whole, None))
        cls.incharge = user("incharge", (R.site_pi, at_ph1, "MO"))
        cls.pat = user("pat", (R.collaborator_pii, whole, None))
        cls.cole = user("cole", (R.collaborator, whole, None))
        cls.cody = user("cody", (R.coder, whole, None))
        cls.tess = user("tess", (R.coding_tester, whole, None))
        cls.rex = user("rex", (R.reviewer, whole, None))
        # A coder here with a PII-lifting grant in the other project.
        cls.carl = user("carl", (R.coder, whole, None), (R.project_pi, elsewhere, None))
        cls.ivy = user("ivy", (R.interviewer, elsewhere, None))
        # Stage 3: a second interviewer and reporter in the same units, a user
        # who is both interviewer and supervisor, and a coder on a
        # self-coding project (IDV02), who is implied an interviewer grant.
        cls.ian2 = user("ian2", (R.interviewer, at_ph1, None))
        cls.rob = user("rob", (R.death_reporter, at_sca, "ANM"))
        cls.mix = user("mix", (R.interviewer, at_ph1, None), (R.interview_supervisor, at_ph1, "MO"))
        cls.scott = user("scott", (R.coder, elsewhere, None))
        db.session.get(VaProjectMaster, SITES_PROJECT).self_coding_enabled = True
        cls.admin = db.session.get(VaUsers, uuid.UUID(cls.base_admin_id))
        cls.ian.job_title = "Health Worker"
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()

    # -- helpers ---------------------------------------------------------------

    def _payload(self, unit=None, **overrides):
        body = {
            "project_id": PROJECT, "site_id": SITE, "org_unit_id": str((unit or self.sca).org_unit_id),
            "deceased_name": "Identifier Case", "deceased_sex": "female", "age_years": 70,
            "date_of_death": _dod(4),
        }
        body.update(overrides)
        return body

    def _post(self, user, unit=None, **overrides):
        self._login(str(user.user_id))
        return self.client.post(API + "/deaths", json=self._payload(unit, **overrides), headers=self._csrf_headers())

    def _register(self, user, unit=None, identifiers=None, **overrides):
        if identifiers is not None:
            overrides["identifiers"] = identifiers
        response = self._post(user, unit, **overrides)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def _patch(self, user, death_id, body):
        self._login(str(user.user_id))
        return self.client.patch(f"{API}/deaths/{death_id}", json=body, headers=self._csrf_headers())

    def _death(self, death_id):
        return db.session.get(VaDeathRegister, uuid.UUID(str(death_id)))

    def _rows(self, death_id):
        return db.session.scalars(
            sa.select(MapDeathIdentifier).where(MapDeathIdentifier.death_id == uuid.UUID(str(death_id)))
        ).all()

    def _audit(self, death_id):
        return db.session.scalars(
            sa.select(MapCaseTransition).where(
                MapCaseTransition.death_id == uuid.UUID(str(death_id)), MapCaseTransition.action == "identifiers_set")
            .order_by(MapCaseTransition.created_at)
        ).all()

    def _submitted(self, registrar, unit, identifiers, workflow_state="ready_for_coding"):
        """A register case with a submission (so coding roles reach it) and numbers."""
        death = intake_svc.register_death(
            registrar, project_id=PROJECT, site_id=SITE, org_unit_id=str(unit.org_unit_id),
            deceased_name="Submitted Case", deceased_sex="female", age_years=50, date_of_death=_dod(),
            identifiers=identifiers)
        sid = f"uuid:idv-{uuid.uuid4()}"
        now = datetime.now(UTC)
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=f"{PROJECT}{SITE}01", va_submission_date=now, va_odk_updatedat=now,
            va_data_collector="idv", va_odk_reviewstate="reviewed", va_instance_name=sid, va_uniqueid_real=sid,
            va_uniqueid_masked=sid, va_consent="yes", va_narration_language="English", va_deceased_age=50,
            va_deceased_gender="male", va_summary=[], va_catcount={}, va_category_list=[],
        ))
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(va_sid=sid, workflow_state=workflow_state))
        death.va_sid = sid
        transitions.transition(death, "in_progress", actor=registrar, action="test")
        transitions.transition(death, "submitted", actor=registrar, action="test")
        db.session.commit()
        return death

    def _list_cases(self, user):
        self._login(str(user.user_id))
        response = self.client.get(CASES + "?preset=deaths&limit=200")
        self.assertEqual(response.status_code, 200, response.get_json())
        return {c["death_id"]: c for c in response.get_json()["cases"]}



class DeathIdentifierTests(IdentifierFixture):
    # -- normalisation, storage, no plaintext ----------------------------------

    def test_a_lower_case_number_is_stored_and_returned_in_capitals(self):
        body = self._register(self.ian, identifiers={"mccd": " mccd/ab12 "})
        entry = [e for e in body["case"]["identifiers"] if e["code"] == "mccd"][0]
        self.assertEqual(entry, {"code": "mccd", "label": "MCCD number", "value": "MCCD/AB12"})
        rows = self._rows(body["case"]["death_id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(ids.decrypt_row(rows[0]), "MCCD/AB12")

    def test_the_database_holds_no_plaintext_in_the_row_the_audit_or_the_logs(self):
        value = _number()
        with self.assertLogs(level="DEBUG") as logs:
            body = self._register(self.ian, identifiers={"crs": value, "mccd": "abc/9999"})
            # A refusal and a duplicate warning are logged paths too.
            self._post(self.ian, identifiers={"crs": value + "x"})
            self._register(self.ian, identifiers={"crs": value})
        death_id = body["case"]["death_id"]
        rows = self._rows(death_id)
        self.assertEqual(len(rows), 2)  # subject present first
        needles = (value, "ABC/9999", "abc/9999")
        for row in rows:
            for column in sa.inspect(MapDeathIdentifier).columns:
                text = str(getattr(row, column.key))
                for needle in needles:
                    self.assertNotIn(needle, text, column.key)
        audit = self._audit(death_id)
        self.assertEqual(len(audit), 1)
        for row in db.session.scalars(sa.select(MapCaseTransition).where(
                MapCaseTransition.death_id == uuid.UUID(death_id))):
            for needle in needles:
                self.assertNotIn(needle, repr((row.changes, row.reason)))
        self.assertTrue(logs.output)
        for needle in needles:
            self.assertNotIn(needle, "\n".join(logs.output))

    def test_the_audit_row_names_the_codes_and_masked_traces_and_a_supervisor_grant(self):
        case = self._register(self.ian, unit=self.scb)["case"]
        value = "12345678"
        response = self._patch(self.sam, case["death_id"], {"identifiers": {"crs": value}})
        self.assertEqual(response.status_code, 200, response.get_json())
        row = self._audit(case["death_id"])[-1]
        grant = db.session.scalar(sa.select(VaUserAccessGrants).filter_by(
            user_id=self.sam.user_id, role=R.interview_supervisor))
        self.assertEqual((row.authorizing_grant_id, row.authorizing_cadre_id), (grant.grant_id, self.cadres["MO"].cadre_id))
        self.assertEqual((row.from_state, row.to_state, row.reason), ("registered", "registered", "crs"))
        change = row.changes["identifier:crs"]
        self.assertIsNone(change["old"])
        self.assertEqual(list(change["new"]), ["bidx"])  # no digits in the trace
        self.assertEqual(len(change["new"]["bidx"]), 16)
        first_bidx = change["new"]["bidx"]
        self._patch(self.sam, case["death_id"], {"identifiers": {"crs": "123456"}})
        newest = self._audit(case["death_id"])[-1]
        self.assertEqual(list(newest.changes["identifier:crs"]["new"]), ["bidx"])
        self.assertEqual(newest.changes["identifier:crs"]["old"], {"bidx": first_bidx})
        self.assertNotIn("5678", repr(newest.changes))
        # The registrant's own write names no grant.
        registered = self._audit(self._register(self.ian, identifiers={"crs": _number()})["case"]["death_id"])[0]
        self.assertIsNone(registered.authorizing_grant_id)

    def test_a_ciphertext_moved_to_another_row_fails_to_decrypt(self):
        first = self._register(self.ian, identifiers={"crs": _number()})["case"]["death_id"]
        second = self._register(self.ian, identifiers={"crs": _number()})["case"]["death_id"]
        a, b = self._rows(first)[0], self._rows(second)[0]
        self.assertTrue(ids.decrypt_row(a) and ids.decrypt_row(b))  # present and readable first
        a.value_ciphertext, b.value_ciphertext = b.value_ciphertext, a.value_ciphertext
        a.dek_wrapped, b.dek_wrapped = b.dek_wrapped, a.dek_wrapped
        for row in (a, b):
            with self.assertRaises(pii_crypto.PiiCryptoError):
                ids.decrypt_row(row)
        # Same death, other type: the AAD names the type as well.
        c = self._register(self.ian, identifiers={"crs": _number(), "mccd": "abcd1234"})["case"]["death_id"]
        crs_row, mccd_row = sorted(self._rows(c), key=lambda r: r.identifier_type_id != self.crs.identifier_type_id)
        crs_row.value_ciphertext, mccd_row.value_ciphertext = mccd_row.value_ciphertext, crs_row.value_ciphertext
        crs_row.dek_wrapped, mccd_row.dek_wrapped = mccd_row.dek_wrapped, crs_row.dek_wrapped
        with self.assertRaises(pii_crypto.PiiCryptoError):
            ids.decrypt_row(crs_row)
        db.session.rollback()

    # -- registration refusals -------------------------------------------------

    def test_a_bad_number_is_a_422_naming_the_field_and_never_echoing_the_value(self):
        before = db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister))
        bad = "12ab34"
        response = self._post(self.ian, identifiers={"crs": bad, "mccd": "ok-1234"})
        body = response.get_json()
        self.assertEqual((response.status_code, body["code"]), (422, "invalid_registration"))
        self.assertEqual(body["fields"], ["identifiers.crs"])
        self.assertIn("CRS number", body["error"])
        self.assertNotIn(bad, response.get_data(as_text=True))
        self.assertNotIn("12AB34", response.get_data(as_text=True))
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister)), before)
        # Too short, an unknown code and an inactive code are refused alike.
        for identifiers, field in (({"crs": "123"}, "identifiers.crs"), ({"nope": "1234"}, "identifiers.nope"),
                                   ({"old": "1234"}, "identifiers.old")):
            refused = self._post(self.ian, identifiers=identifiers)
            self.assertEqual((refused.status_code, refused.get_json()["fields"]), (422, [field]), identifiers)
        # An object where text belongs, and text where the object belongs.
        for identifiers in ({"crs": 123456}, {"crs": ["123456"]}, {"crs": {"a": 1}}, "123456", ["crs"]):
            refused = self._post(self.ian, identifiers=identifiers)
            self.assertEqual(refused.status_code, 422, identifiers)
            self.assertIn("identifiers", refused.get_json()["fields"][0])

    def test_a_required_type_refuses_a_registration_and_a_later_correction_accepts_it(self):
        def payload(**kw):
            return {"project_id": SITES_PROJECT, "site_id": SITES_SITE, "deceased_name": "Req Case",
                    "deceased_sex": "male", "age_years": 40, "date_of_death": _dod(), **kw}

        self._login(str(self.ivy.user_id))
        first = self.client.post(API + "/deaths", json=payload(), headers=self._csrf_headers())
        self.assertEqual(first.status_code, 201, first.get_json())  # not required yet
        self.reqd.required_at_report = True
        db.session.commit()
        try:
            refused = self.client.post(API + "/deaths", json=payload(), headers=self._csrf_headers())
            self.assertEqual((refused.status_code, refused.get_json()["code"]), (422, "invalid_registration"))
            self.assertEqual(refused.get_json()["fields"], ["identifiers.reqd"])
            ok = self.client.post(API + "/deaths", json=payload(identifiers={"reqd": "12345"}),
                                  headers=self._csrf_headers())
            self.assertEqual(ok.status_code, 201, ok.get_json())
            # A correction need not carry it, and may add it later.
            death_id = first.get_json()["case"]["death_id"]
            self.assertEqual(self._patch(self.ivy, death_id, {"remarks": "ok"}).status_code, 200)
            added = self._patch(self.ivy, death_id, {"identifiers": {"reqd": "6789"}})
            self.assertEqual(added.status_code, 200, added.get_json())
            self.assertEqual(len(self._rows(death_id)), 1)
        finally:
            self.reqd.required_at_report = False
            db.session.commit()

    # -- idempotency -----------------------------------------------------------

    def test_a_resent_registration_stores_one_set_and_warns_nothing_again(self):
        value, client_id = _number(), str(uuid.uuid4())
        other = self._register(self.ian, unit=self.scb, identifiers={"crs": value})["case"]
        first = self._post(self.ian, identifiers={"crs": value}, client_death_id=client_id)
        self.assertEqual(first.status_code, 201, first.get_json())
        self.assertEqual([w["code"] for w in first.get_json()["warnings"]], ["identifier_in_use"])
        again = self._post(self.ian, identifiers={"crs": value}, client_death_id=client_id)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.get_json()["case"]["death_id"], first.get_json()["case"]["death_id"])
        self.assertNotIn("warnings", again.get_json())
        death_id = first.get_json()["case"]["death_id"]
        self.assertEqual(len(self._rows(death_id)), 1)
        self.assertEqual(len(self._audit(death_id)), 1)
        self.assertTrue(other["death_id"])

    # -- correction ------------------------------------------------------------

    def test_a_correction_changes_only_the_listed_codes_and_null_clears(self):
        case = self._register(self.ian, identifiers={"crs": _number(), "mccd": "abcd-1"})["case"]
        death_id = case["death_id"]
        self.assertEqual(len(self._rows(death_id)), 2)  # subject present first
        replaced = _number()
        response = self._patch(self.ian, death_id, {"identifiers": {"crs": replaced}})
        self.assertEqual(response.status_code, 200, response.get_json())
        shown = {e["code"]: e["value"] for e in response.get_json()["case"]["identifiers"]}
        self.assertEqual(shown, {"crs": replaced, "mccd": "ABCD-1"})
        rows = {r.identifier_type_id: r for r in self._rows(death_id)}
        self.assertIsNotNone(rows[self.crs.identifier_type_id].updated_by)
        self.assertIsNone(rows[self.mccd.identifier_type_id].updated_by)
        # An unchanged value writes nothing: no audit row, no new warning.
        audits = len(self._audit(death_id))
        same = self._patch(self.ian, death_id, {"identifiers": {"crs": f" {replaced} "}})
        self.assertEqual(same.status_code, 200)
        self.assertEqual(len(self._audit(death_id)), audits)
        # null (or empty text) deletes the row and the audit keeps a blind-index trace.
        cleared = self._patch(self.ian, death_id, {"identifiers": {"crs": None, "mccd": ""}})
        self.assertEqual(cleared.status_code, 200, cleared.get_json())
        self.assertEqual(self._rows(death_id), [])
        last = self._audit(death_id)[-1]
        self.assertEqual(sorted(last.changes), ["identifier:crs", "identifier:mccd"])
        self.assertIsNone(last.changes["identifier:crs"]["new"])
        self.assertEqual(list(last.changes["identifier:crs"]["old"]), ["bidx"])
        self.assertNotIn(replaced[-4:], repr(last.changes))
        # A values viewer sees every active type; a cleared one is an empty slot (value null).
        self.assertEqual(cleared.get_json()["case"]["identifiers"], [{"code": "crs", "label": "CRS number", "value": None}, {"code": "mccd", "label": "MCCD number", "value": None}])

    def test_a_bad_correction_is_refused_with_fields_and_the_gates_still_apply(self):
        case = self._register(self.ian, identifiers={"crs": _number()})["case"]
        death_id = case["death_id"]
        bad = self._patch(self.ian, death_id, {"identifiers": {"crs": "12ab34"}})
        self.assertEqual((bad.status_code, bad.get_json()["code"]), (422, "invalid_death"))
        self.assertEqual(bad.get_json()["fields"], ["identifiers.crs"])
        self.assertNotIn("12ab34", bad.get_data(as_text=True).lower())
        nothing = self._patch(self.ian, death_id, {"identifiers": {}})
        self.assertEqual(nothing.status_code, 422)
        with mock.patch.object(intake_svc, "_interview_completed", return_value=True):
            done = self._patch(self.ian, death_id, {"identifiers": {"crs": _number()}})
        self.assertEqual((done.status_code, done.get_json()["code"]), (409, "case_completed"))
        stale = self._patch(self.ian, death_id, {"identifiers": {"crs": _number()}, "if_updated_at": "2001-01-01T00:00:00+00:00"})
        self.assertEqual((stale.status_code, stale.get_json()["code"]), (409, "death_stale"))
        outside = self._patch(self.rita, death_id, {"identifiers": {"crs": _number()}})  # not hers: 404
        self.assertEqual(outside.status_code, 404)

    def test_a_change_moves_the_case_activity_stamp(self):
        case = self._register(self.ian)["case"]
        stamp = case["updated_at"]
        response = self._patch(self.ian, case["death_id"], {"identifiers": {"crs": _number()}})
        self.assertGreater(response.get_json()["case"]["updated_at"], stamp)

    # -- duplicate warnings ----------------------------------------------------

    def test_a_duplicate_warns_with_detail_in_supervision_reach_and_generically_outside_it(self):
        value = _number()
        in_reach = self._register(self.ian, unit=self.scb, identifiers={"crs": value})["case"]
        elsewhere = self._register(self.wally, unit=self.scc, identifiers={"crs": _number()})["case"]
        by_rita = self._register(self.rita, unit=self.sca, identifiers={"crs": _number()})["case"]
        # Sam supervises PH1's subtree: detail for the SCB case (and its reporter's job title).
        mine = self._register(self.ian, unit=self.sca)["case"]
        warned = self._patch(self.sam, mine["death_id"], {"identifiers": {"crs": value}})
        self.assertEqual(warned.status_code, 200, warned.get_json())
        [warning] = warned.get_json()["warnings"]
        self.assertEqual((warning["code"], warning["field"]), ("identifier_in_use", "identifiers.crs"))
        self.assertEqual(
            warning["message"],
            f"This number is already on case {in_reach['unique_id']} (unit Unit SCB), "
            f"reported by idv.ian@test.local - Health Worker.")
        # The reporter's cadre is the designation when the grant carries one.
        again = self._patch(self.sam, mine["death_id"], {"identifiers": {"crs": _number()}})
        self.assertNotIn("warnings", again.get_json())
        by_cadre = self._patch(self.sam, mine["death_id"], {"identifiers": {"crs": self._crs_of(by_rita)}})
        self.assertIn(f"reported by idv.rita@test.local - {self.cadres['ANM'].cadre_name}",
                      by_cadre.get_json()["warnings"][0]["message"])
        # An interviewer is not a supervisor: generic text, no id, unit or name.
        theirs = self._register(self.ian, unit=self.sca)["case"]
        generic = self._patch(self.ian, theirs["death_id"], {"identifiers": {"crs": value}})
        [warning] = generic.get_json()["warnings"]
        self.assertEqual(warning["message"], ids.GENERIC_IN_USE)
        for secret in (in_reach["unique_id"], "Unit SCB", "idv.ian@test.local", "Health Worker"):
            self.assertNotIn(secret, warning["message"])
        # Supervision reach, not the project: a PH2 case is generic even for Sam.
        far = self._register(self.wally, unit=self.scc, identifiers={"crs": _number()})["case"]
        far_value = self._crs_of(far)
        sam_case = self._register(self.ian, unit=self.sca)["case"]
        generic_for_sam = self._patch(self.sam, sam_case["death_id"], {"identifiers": {"crs": far_value}})
        self.assertEqual(generic_for_sam.get_json()["warnings"][0]["message"], ids.GENERIC_IN_USE)
        self.assertTrue(elsewhere["death_id"])
        # An admin sees the detail for any case of the project.
        other_case = self._death(self._register(self.ian, unit=self.sca)["case"]["death_id"])
        _, warnings = ids.set_identifiers(other_case, self.admin, {"crs": far_value}, reason_context="test",
                                          enforce_required=False)
        db.session.rollback()
        self.assertIn(f"case {far['unique_id']} (unit Unit SCC)", warnings[0]["message"])

    def _crs_of(self, case):
        row = [r for r in self._rows(case["death_id"]) if r.identifier_type_id == self.crs.identifier_type_id][0]
        return ids.decrypt_row(row)

    def test_a_type_without_project_uniqueness_never_warns(self):
        self._register(self.ian, identifiers={"mccd": "same-9999"})
        second = self._post(self.ian, identifiers={"mccd": "same-9999"})
        self.assertEqual(second.status_code, 201)
        self.assertNotIn("warnings", second.get_json())

    def test_cancelled_and_confirmed_duplicate_cases_do_not_count(self):
        value = _number()
        open_case = self._register(self.ian, unit=self.scb, identifiers={"crs": value})["case"]
        warned = self._post(self.ian, identifiers={"crs": value})
        self.assertEqual(len(warned.get_json()["warnings"]), 1)  # present while open
        both = [open_case["death_id"], warned.get_json()["case"]["death_id"]]  # that new case is open too
        for state in ("cancelled", "duplicate"):
            for death_id in both:
                self._death(death_id).status = state
            db.session.commit()
            quiet = self._post(self.ian, identifiers={"crs": value})
            self.assertEqual(quiet.status_code, 201)
            self.assertNotIn("warnings", quiet.get_json(), state)
            both.append(quiet.get_json()["case"]["death_id"])  # open again: close it with the rest
        for death_id in both:
            self._death(death_id).status = "registered"
        db.session.commit()

    def test_a_shared_number_is_a_strong_possible_duplicate_inside_the_callers_reach_only(self):
        value = _number()
        a = self._register(self.ian, unit=self.sca, deceased_name="Zed Alpha", identifiers={"crs": value})["case"]
        b = self._register(self.ian, unit=self.scb, deceased_name="Quentin Bravo", identifiers={"crs": value},
                           date_of_death=_dod(40), deceased_sex="male")["case"]
        c = self._register(self.wally, unit=self.scc, deceased_name="Walter Charlie", identifiers={"crs": value})["case"]
        found = intake_svc.possible_duplicates(self.ian, self._death(a["death_id"]))
        self.assertEqual([row["death_id"] for row in found], [b["death_id"]])  # present, in reach
        self.assertEqual(found[0]["score"], 1.0)
        self.assertNotIn(c["death_id"], [row["death_id"] for row in found])  # SCC is outside Ian's reach
        # The supervisor's endpoint returns the supervisor keys only.
        self._login(str(self.sam.user_id))
        response = self.client.get(f"{API}/supervision/cases/{a['death_id']}/possible-duplicates")
        self.assertEqual(response.status_code, 200)
        rows = response.get_json()["possible_duplicates"]
        self.assertIn(b["death_id"], [r["death_id"] for r in rows])
        self.assertNotIn("informant_name", rows[0])
        # A different number is no candidate.
        d = self._register(self.ian, unit=self.sca, deceased_name="Lone Delta", identifiers={"crs": _number()})["case"]
        self.assertEqual(intake_svc.possible_duplicates(self.ian, self._death(d["death_id"])), [])

    # -- visibility ------------------------------------------------------------

    def test_value_visibility_follows_the_project_role_not_the_pii_redaction(self):
        seeing = {"admin": self.admin, "project_pi": self.pip, "site_pi": self.incharge, "supervisor": self.sam,
                  "data_manager": self.dana, "interviewer": self.ian, "death_reporter": self.rita,
                  "collaborator_pii": self.pat}
        for name, user in seeing.items():
            self.assertEqual(ids.identifier_values_visible(user, {PROJECT}), {PROJECT}, name)
        badge_only = {"coder": self.cody, "coding_tester": self.tess, "reviewer": self.rex, "collaborator": self.cole}
        for name, user in badge_only.items():
            self.assertEqual(ids.identifier_values_visible(user, {PROJECT}), set(), name)
        # A coder here who holds a PII-lifting grant in another project.
        self.assertEqual(ids.identifier_values_visible(self.carl, {PROJECT, SITES_PROJECT}), {SITES_PROJECT})
        self.assertEqual(ids.identifier_values_visible(self.ivy, {PROJECT, SITES_PROJECT}), {SITES_PROJECT})
        self.assertEqual(ids.identifier_values_visible(self.admin, set()), set())

    def test_the_shared_case_list_shows_values_to_value_roles_and_a_badge_to_the_rest(self):
        value = _number()
        case = self._submitted(self.ian, self.sca, {"crs": value})
        key = str(case.death_id)
        for user in (self.ian, self.sam, self.dana, self.pat, self.pip):
            row = self._list_cases(user)[key]
            self.assertEqual(
                row["identifiers"], [{"code": "crs", "label": "CRS number", "value": value},
                                     {"code": "mccd", "label": "MCCD number", "value": None}], user.email)
        for user in (self.cody, self.carl, self.cole):
            row = self._list_cases(user)[key]  # reached through the submission
            self.assertEqual(row["identifiers"], [
                {"code": "crs", "label": "CRS number", "present": True},
                {"code": "mccd", "label": "MCCD number", "present": False},
            ], user.email)
            self.assertNotIn("value", str(row["identifiers"]))
        # The same user reaching the case as an interviewer sees the value.
        self.assertEqual(self._list_cases(self.ian)[key]["identifiers"][0]["value"], value)

    def test_the_other_lists_and_details_carry_identifiers(self):
        value = _number()
        case = self._register(self.rita, unit=self.sca, identifiers={"crs": value, "mccd": "abc-1234"})["case"]
        death_id = case["death_id"]
        expected = [{"code": "crs", "label": "CRS number", "value": value},
                    {"code": "mccd", "label": "MCCD number", "value": "ABC-1234"}]
        self._login(str(self.rita.user_id))
        reported = self.client.get(API + "/deaths").get_json()["deaths"]
        self.assertEqual({d["death_id"]: d["identifiers"] for d in reported}[death_id], expected)
        self._login(str(self.ian.user_id))
        self.assertEqual(
            self.client.get(f"{API}/deaths?project_id={PROJECT}&site_id={SITE}").get_json()["deaths"][0]["identifiers"][0]["code"],
            "crs")
        worklist = {c["death_id"]: c for c in self.client.get(API + "/cases?limit=200").get_json()["cases"]}
        self.assertEqual(worklist[death_id]["identifiers"], expected)
        self.assertEqual(self.client.get(f"{API}/cases/{death_id}").get_json()["case"]["identifiers"], expected)
        self._login(str(self.sam.user_id))
        listed = {c["death_id"]: c for c in self.client.get(API + "/supervision/cases?limit=200").get_json()["cases"]}
        self.assertEqual(listed[death_id]["identifiers"], expected)
        detail = self.client.get(f"{API}/supervision/cases/{death_id}").get_json()["case"]
        self.assertEqual(detail["identifiers"], expected)
        # A supervisor action's reply carries them too.
        flagged = self.client.post(f"{API}/supervision/cases/{death_id}/cancel", json={"reason": "test"},
                                   headers=self._csrf_headers())
        self.assertEqual(flagged.get_json()["case"]["identifiers"], expected)
        self.client.post(f"{API}/supervision/cases/{death_id}/reopen", json={"reason": "test"},
                         headers=self._csrf_headers())

    def test_types_without_a_row_and_inactive_types_follow_the_viewer(self):
        case = self._submitted(self.ian, self.sca, {"crs": _number()})
        ciphertext, wrapped, key_id = pii_crypto.encrypt_value(
            "OLD-1", ids.aad(case.death_id, self.old.identifier_type_id))
        db.session.add(MapDeathIdentifier(
            death_id=case.death_id, identifier_type_id=self.old.identifier_type_id, value_ciphertext=ciphertext,
            dek_wrapped=wrapped, key_id=key_id, entered_by=self.ian.user_id,
            value_blind_index=pii_crypto.blind_index(self.old.identifier_type_id.bytes, "OLD-1")))
        db.session.commit()
        values = ids.identifier_payloads(self.ian, [case])[case.death_id]
        # A values viewer gets every active type (value null without a row), and an inactive type shows its stored value.
        self.assertEqual([e["code"] for e in values], ["crs", "mccd", "old"])
        self.assertEqual(values[1], {"code": "mccd", "label": "MCCD number", "value": None})
        self.assertEqual(values[2]["value"], "OLD-1")
        badges = ids.identifier_payloads(self.cody, [case])[case.death_id]
        self.assertEqual([(e["code"], e["present"]) for e in badges], [("crs", True), ("mccd", False), ("old", True)])
        self.assertTrue(all("value" not in e for e in badges))

    # -- reads: query count, no decryption for badge viewers -------------------

    def test_identifier_reads_use_a_constant_number_of_statements(self):
        cases = [self._death(self._register(self.ian, identifiers={"crs": _number()})["case"]["death_id"])
                 for _ in range(12)]
        counts = []
        self.assertEqual(len({c.project_id for c in cases}), 1)  # load them all before counting
        for size in (2, 12):
            with _statements() as found:
                payloads = ids.identifier_payloads(self.ian, cases[:size])
            self.assertEqual(len(payloads), size)
            self.assertEqual(len(payloads[cases[0].death_id]), 2)  # crs, and mccd as an empty slot
            counts.append(len(found))
        self.assertEqual(counts[0], counts[1])
        # And through the worklist API: the page size changes no statement count.
        self._login(str(self.ian.user_id))
        page_counts = []
        for limit in (3, 12):
            with _statements() as found:
                response = self.client.get(f"{API}/cases?limit={limit}")
            self.assertEqual(len(response.get_json()["cases"]), limit)
            page_counts.append(len(found))
        self.assertEqual(page_counts[0], page_counts[1])

    def test_a_badge_only_page_decrypts_nothing(self):
        case = self._submitted(self.ian, self.sca, {"crs": _number()})
        with mock.patch.object(pii_crypto, "decrypt_value", wraps=pii_crypto.decrypt_value) as spy:
            values = ids.identifier_payloads(self.ian, [case])
            self.assertEqual(spy.call_count, 1)  # the viewer who may see it: subject present
            self.assertIn("value", values[case.death_id][0])
            spy.reset_mock()
            badges = ids.identifier_payloads(self.cody, [case])
            self.assertEqual(spy.call_count, 0)
            row = self._list_cases(self.cody)[str(case.death_id)]
            self.assertEqual(spy.call_count, 0)
        self.assertIs(badges[case.death_id][0]["present"], True)
        self.assertIs(row["identifiers"][0]["present"], True)

    def test_an_unreadable_value_degrades_to_the_badge_and_logs_no_value(self):
        case = self._death(self._register(self.ian, identifiers={"crs": "55667788"})["case"]["death_id"])
        with mock.patch.object(pii_crypto, "decrypt_value", side_effect=pii_crypto.PiiCryptoError("PII value could not be decrypted (row r, key k).")):
            with self.assertLogs(level="ERROR") as logs:
                entries = ids.identifier_payloads(self.ian, [case])[case.death_id]
        self.assertEqual(entries, [{"code": "crs", "label": "CRS number", "present": True},
                                   {"code": "mccd", "label": "MCCD number", "value": None}])
        self.assertNotIn("55667788", "\n".join(logs.output))

    # -- the roles and the log ---------------------------------------------------

    def test_registration_without_identifiers_still_works_and_audits_nothing(self):
        body = self._register(self.ian)
        self.assertEqual(body["case"]["identifiers"], [{"code": "crs", "label": "CRS number", "value": None}, {"code": "mccd", "label": "MCCD number", "value": None}])
        self.assertNotIn("warnings", body)
        self.assertEqual(self._audit(body["case"]["death_id"]), [])  # nothing set, nothing audited

    def test_a_reporter_registers_with_numbers_and_edits_them(self):
        case = self._register(self.rita, unit=self.sca, identifiers={"crs": _number()})["case"]
        self.assertEqual(case["links"], {"update": f"{API}/deaths/{case['death_id']}"})  # reporter-shaped body
        self.assertEqual(case["identifiers"][0]["code"], "crs")
        replaced = _number()
        response = self._patch(self.rita, case["death_id"], {"identifiers": {"crs": replaced}})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["case"]["identifiers"][0]["value"], replaced)
