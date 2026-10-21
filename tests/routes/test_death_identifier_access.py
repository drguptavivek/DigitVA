"""Registration identifiers, stage 3 backend: the any-time write, who may write,
``can_edit_identifiers``, the self-coding fix, limits, headers, list filters.

Policy: docs/policy/death-registration-identifiers.md (bead digitva-kzyp),
decisions 10-14, "Authorization", "API outline". Fixture (tree IDV01, types
``crs`` digits project-unique and ``mccd`` not unique, IDV02 self-coding sites
project) is ``IdentifierFixture``. Every "absent" assertion first asserts that
its subject is present.
"""
import logging
import uuid
from datetime import UTC, datetime
from unittest import mock

from flask import g

from app import db, limiter
from app.models import (
    AuthDeviceSession,
    MapDeathIdentifier,
    MasDeathIdentifierType,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import case_list_service
from app.services import death_identifier_service as ids
from app.services import device_auth_service as devices
from app.services import web_intake_service as intake_svc
from app.services.authz import invalidate_all
from app.utils import pii_crypto
from tests.routes.test_death_identifiers import (
    API,
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


class IdentifierAccessTests(IdentifierFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # An interviewer of SCA only who also codes the whole project: with
        # self-coding on she is implied an interviewer grant everywhere.
        cls.mia = cls._get_or_make_user("idv.mia@test.local", "Identifier123")
        for role, scope_type, unit in ((R.interviewer, VaAccessScopeTypes.org_unit, cls.sca),
                                       (R.coder, VaAccessScopeTypes.project, None)):
            db.session.add(VaUserAccessGrants(
                user_id=cls.mia.user_id, role=role, grant_status=VaStatuses.active, notes="identifiers",
                scope_type=scope_type, org_unit_id=unit.org_unit_id if unit else None,
                project_id=None if unit else PROJECT))
        db.session.commit()
    # -- helpers ---------------------------------------------------------------

    def _put(self, user, death_id, body, *, headers=None):
        self._login(str(user.user_id))
        return self.client.put(f"{API}/cases/{death_id}/identifiers", json=body,
                               headers=headers or self._csrf_headers())

    def _write(self, user, death_id, **identifiers):
        return self._put(user, death_id, {"identifiers": identifiers})

    def _device(self, user):
        """A bearer header for *user*, a device session opened directly."""
        _row, code = devices.create_enrolment_code(PROJECT, actor=self.admin)
        device, _secret = devices.enrol_device(code, device_name="ids", platform="android", app_version="0.1.0")
        session = AuthDeviceSession(
            device_id=device.device_id, user_id=user.user_id,
            user_session_version=user.auth_session_version or 0, created_at=datetime.now(UTC),
        )
        issued = devices._issue(session)
        db.session.add(session)
        db.session.commit()
        return {"Authorization": f"Bearer {issued.access_token}"}

    def _as_device(self, user, method, url, **kwargs):
        headers = self._device(user)
        g.pop("_login_user", None)
        g.pop("device_session", None)
        with self.client.session_transaction() as http_session:
            http_session.clear()
        return getattr(self.client, method)(url, headers={**headers, **kwargs.pop("headers", {})}, **kwargs)

    def _submitted_case(self, registrar=None, unit=None, identifiers=None):
        return self._submitted(registrar or self.wally, unit or self.sca, identifiers or {})

    def _interviewed_by(self, death, user):
        self._death(death.death_id).started_by_user_id = user.user_id
        db.session.commit()

    def _close(self, death, state):
        self._death(death.death_id).status = state
        db.session.commit()

    def _crs_value(self, death_id):
        rows = [r for r in self._rows(death_id) if r.identifier_type_id == self.crs.identifier_type_id]
        return ids.decrypt_row(rows[0]) if rows else None

    # -- who may write ---------------------------------------------------------

    def test_every_allowed_role_writes_after_completion_without_changing_the_state(self):
        writers = {
            "admin": (self.admin, self.wally), "supervisor": (self.sam, self.wally),
            "in_charge": (self.incharge, self.wally), "project_pi": (self.pip, self.wally),
            "data_manager": (self.dana, self.wally), "reporter": (self.rita, self.rita),
            "interviewer": (self.ian, self.wally),
        }
        for name, (writer, registrar) in writers.items():
            case = self._submitted_case(registrar)
            if name == "interviewer":
                self._interviewed_by(case, writer)
            self.assertEqual(self._death(case.death_id).status, "submitted", name)  # complete: update_death refuses
            number = _number()
            response = self._write(writer, case.death_id, crs=number)
            self.assertEqual(response.status_code, 200, (name, response.get_json()))
            self.assertEqual(self._crs_value(case.death_id), number, name)
            self.assertEqual(self._death(case.death_id).status, "submitted", name)
            audit = self._audit(case.death_id)
            self.assertEqual(len(audit), 1, name)
            self.assertEqual((audit[0].from_state, audit[0].to_state, audit[0].actor_user_id),
                             ("submitted", "submitted", writer.user_id), name)
            if name in ("supervisor", "in_charge", "project_pi", "data_manager"):
                self.assertIsNotNone(audit[0].authorizing_grant_id, name)
            else:
                self.assertIsNone(audit[0].authorizing_grant_id, name)
        # update_death refuses the same case, so the new route is not a rename of it.
        self.assertEqual(self._patch(self.ian, case.death_id, {"identifiers": {"crs": _number()}}).status_code, 409)

    def test_the_reply_is_the_case_with_the_numbers_and_the_flag_and_warnings_only_on_a_duplicate(self):
        other = self._submitted_case(identifiers={"crs": "40404040"})
        case = self._submitted_case()
        response = self._write(self.sam, case.death_id, crs="40404040", mccd="abc-12")
        body = response.get_json()
        self.assertEqual(response.status_code, 200, body)
        self.assertEqual(body["case"]["death_id"], str(case.death_id))
        self.assertEqual({e["code"]: e["value"] for e in body["case"]["identifiers"]},
                         {"crs": "40404040", "mccd": "ABC-12"})
        self.assertIs(body["case"]["can_edit_identifiers"], True)
        [warning] = body["warnings"]
        self.assertEqual((warning["code"], warning["field"]), ("identifier_in_use", "identifiers.crs"))
        self.assertIn(other.unique_id, warning["message"])  # a supervisor in reach: the detail
        quiet = self._write(self.sam, case.death_id, mccd="abc-13")
        self.assertEqual(quiet.status_code, 200)
        self.assertNotIn("warnings", quiet.get_json())

    def test_a_null_or_empty_value_clears_and_an_unchanged_one_writes_nothing(self):
        case = self._submitted_case(identifiers={"crs": _number(), "mccd": "keep-1"})
        self.assertEqual(len(self._rows(case.death_id)), 2)
        before = len(self._audit(case.death_id))
        same = self._write(self.sam, case.death_id, mccd=" keep-1 ")
        self.assertEqual(same.status_code, 200)
        self.assertEqual(len(self._audit(case.death_id)), before)
        cleared = self._put(self.sam, case.death_id, {"identifiers": {"crs": None, "mccd": ""}})
        self.assertEqual(cleared.status_code, 200, cleared.get_json())
        self.assertEqual(self._rows(case.death_id), [])
        self.assertEqual(len(self._audit(case.death_id)), before + 1)

    def test_who_may_not_write_is_refused_and_nothing_changes(self):
        case = self._submitted_case(self.rita, identifiers={"crs": "50505050"})
        rows_before = len(self._rows(case.death_id))
        audits_before = len(self._audit(case.death_id))
        # Role gate: no writing role at all (coder, reviewer, tester, collaborators).
        for name, user in (("coder", self.cody), ("tester", self.tess), ("reviewer", self.rex),
                           ("collaborator", self.cole), ("collaborator_pii", self.pat)):
            refused = self._write(user, case.death_id, crs=_number())
            self.assertEqual((refused.status_code, refused.get_json()["code"]), (403, "forbidden"), name)
        # An interviewer of the unit who did not interview the case, in scope: 403.
        other = self._write(self.ian2, case.death_id, crs=_number())
        self.assertEqual((other.status_code, other.get_json()["code"]), (403, "forbidden"))
        # Another reporter does not reach it; an interviewer of another project neither: 404.
        for name, user in (("other reporter", self.rob), ("other project", self.ivy)):
            gone = self._write(user, case.death_id, crs=_number())
            self.assertEqual((gone.status_code, gone.get_json()["code"]), (404, "not_found"), name)
        self.assertEqual(self._write(self.ian2, str(uuid.uuid4()), crs=_number()).status_code, 404)
        self.assertEqual(self._write(self.ian2, "not-a-uuid", crs=_number()).status_code, 404)
        self.assertEqual(self._crs_value(case.death_id), "50505050")
        self.assertEqual((len(self._rows(case.death_id)), len(self._audit(case.death_id))),
                         (rows_before, audits_before))
        # The same case is written by the people who may (subject present).
        self.assertEqual(self._write(self.rita, case.death_id, crs=_number()).status_code, 200)

    def test_an_interviewer_writes_only_cases_they_started_or_interviewed(self):
        case = self._submitted_case()
        self.assertEqual(self._write(self.ian, case.death_id, crs=_number()).status_code, 403)
        self._interviewed_by(case, self.ian)
        self.assertEqual(self._write(self.ian, case.death_id, crs=_number()).status_code, 200)
        self.assertEqual(self._write(self.ian2, case.death_id, crs=_number()).status_code, 403)
        # A draft of theirs (an interview begun) counts, a discarded one does not.
        second = self._death(self._register(self.wally, unit=self.sca)["case"]["death_id"])
        draft = intake_svc.start_draft(
            self.ian2, project_id=PROJECT, site_id=SITE, org_unit_id=str(self.sca.org_unit_id), death_id=second.death_id)
        db.session.commit()
        self.assertEqual(self._write(self.ian2, second.death_id, crs=_number()).status_code, 200)
        draft.status = "discarded"
        self._death(second.death_id).started_by_user_id = None
        db.session.commit()
        self.assertEqual(self._write(self.ian2, second.death_id, crs=_number()).status_code, 403)

    def test_a_reporter_writes_only_the_deaths_they_reported(self):
        theirs = self._submitted_case(self.rita)
        others = self._submitted_case(self.wally)
        self.assertEqual(self._write(self.rita, theirs.death_id, crs=_number()).status_code, 200)
        self.assertEqual(self._write(self.rita, others.death_id, crs=_number()).status_code, 404)

    # -- closed cases ----------------------------------------------------------

    def test_a_closed_case_is_written_by_supervisors_only_and_the_rest_get_case_closed(self):
        for state in ("cancelled", "duplicate"):
            case = self._submitted_case(self.rita)
            self._interviewed_by(case, self.ian)
            self.assertEqual(self._write(self.rita, case.death_id, crs=_number()).status_code, 200, state)  # open
            self._close(case, state)
            for name, user in (("reporter", self.rita), ("interviewer", self.ian), ("data_manager", self.dana)):
                refused = self._write(user, case.death_id, crs=_number())
                body = refused.get_json()
                self.assertEqual((refused.status_code, body["code"]), (409, "case_closed"), (state, name))
            for name, user in (("supervisor", self.sam), ("in_charge", self.incharge),
                               ("project_pi", self.pip), ("admin", self.admin)):
                number = _number()
                done = self._write(user, case.death_id, crs=number)
                self.assertEqual(done.status_code, 200, (state, name, done.get_json()))
                self.assertEqual(self._crs_value(case.death_id), number, (state, name))
                self.assertEqual(self._death(case.death_id).status, state)
            # A user who is not in reach at all still reads as not found.
            self.assertEqual(self._write(self.rob, case.death_id, crs=_number()).status_code, 404)

    def test_the_closed_case_refusal_names_no_value(self):
        case = self._submitted_case(self.rita)
        self._close(case, "cancelled")
        secret = _number()
        refused = self._write(self.rita, case.death_id, crs=secret)
        self.assertEqual(refused.status_code, 409)
        self.assertNotIn(secret, refused.get_data(as_text=True))
        self.assertEqual(self._rows(case.death_id), [])

    def test_a_patch_with_identifiers_on_a_closed_case_is_case_closed_but_register_edits_are_unchanged(self):
        case = self._register(self.ian, unit=self.sca, identifiers={"crs": "60606060"})["case"]
        death_id = case["death_id"]
        self.assertEqual(self._patch(self.ian, death_id, {"identifiers": {"crs": _number()}}).status_code, 200)  # open
        self._close(self._death(death_id), "cancelled")
        value = self._crs_value(death_id)
        refused = self._patch(self.ian, death_id, {"identifiers": {"crs": _number()}})
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (409, "case_closed"))
        mixed = self._patch(self.ian, death_id, {"remarks": "edited", "identifiers": {"crs": _number()}})
        self.assertEqual(mixed.status_code, 409)
        self.assertNotEqual(self._death(death_id).remarks, "edited")  # refused whole
        self.assertEqual(self._crs_value(death_id), value)
        # The register fields of a closed case: unchanged behaviour.
        self.assertEqual(self._patch(self.ian, death_id, {"remarks": "edited"}).status_code, 200)
        self.assertEqual(self._death(death_id).remarks, "edited")
        # A supervisor may still change its numbers.
        number = _number()
        self.assertEqual(self._patch(self.sam, death_id, {"identifiers": {"crs": number}}).status_code, 200)
        self.assertEqual(self._crs_value(death_id), number)

    # -- device credentials ----------------------------------------------------

    def test_a_device_may_write_as_reporter_or_interviewer_but_not_as_a_supervisor(self):
        mine = self._submitted_case(self.rita)
        allowed = self._as_device(self.rita, "put", f"{API}/cases/{mine.death_id}/identifiers",
                                  json={"identifiers": {"crs": "70707070"}})
        self.assertEqual(allowed.status_code, 200, allowed.get_json())
        self.assertEqual(self._crs_value(mine.death_id), "70707070")
        started = self._submitted_case()
        self._interviewed_by(started, self.ian)
        allowed = self._as_device(self.ian, "put", f"{API}/cases/{started.death_id}/identifiers",
                                  json={"identifiers": {"crs": "70707071"}})
        self.assertEqual(allowed.status_code, 200, allowed.get_json())
        # Supervisor and data manager roles are not device roles.
        other = self._submitted_case()
        for name, user in (("supervisor", self.sam), ("data_manager", self.dana), ("in_charge", self.incharge)):
            refused = self._as_device(user, "put", f"{API}/cases/{other.death_id}/identifiers",
                                      json={"identifiers": {"crs": _number()}})
            self.assertEqual(refused.status_code, 403, name)
        # An account that is an interviewer AND a supervisor writes a case it
        # did not interview from the browser, not from a device.
        self.assertEqual(self._write(self.mix, other.death_id, crs=_number()).status_code, 200)
        again = self._as_device(self.mix, "put", f"{API}/cases/{other.death_id}/identifiers",
                                json={"identifiers": {"crs": _number()}})
        self.assertEqual(again.status_code, 403)

    # -- CSRF, shape, concurrency ----------------------------------------------

    def test_the_browser_write_needs_a_csrf_token(self):
        case = self._submitted_case()
        self._login(str(self.sam.user_id))
        refused = self.client.put(f"{API}/cases/{case.death_id}/identifiers", json={"identifiers": {"crs": _number()}})
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(self._rows(case.death_id), [])
        self.assertEqual(self.client.get(f"{API}/cases/{case.death_id}/identifiers").status_code, 405)

    def test_a_bad_body_or_value_is_a_400_naming_the_field_and_never_the_value(self):
        case = self._submitted_case()
        for body in ({}, {"identifiers": {}}, {"identifiers": None}, {"identifiers": ["crs"]},
                     {"identifiers": "123456"}, {"identifiers": {"crs": "123456"}, "other": 1}):
            refused = self._put(self.sam, case.death_id, body)
            self.assertEqual((refused.status_code, refused.get_json()["code"]), (400, "invalid_request"), body)
        bad = "12ab34"
        for identifiers, field in (({"crs": bad}, "identifiers.crs"), ({"crs": "123"}, "identifiers.crs"),
                                   ({"nope": "1234"}, "identifiers.nope"), ({"old": "1234"}, "identifiers.old"),
                                   ({"crs": 123456}, "identifiers.crs")):
            refused = self._put(self.sam, case.death_id, {"identifiers": identifiers})
            self.assertEqual((refused.status_code, refused.get_json()["fields"]), (400, [field]), identifiers)
            self.assertNotIn(bad, refused.get_data(as_text=True))
        self.assertEqual(self._rows(case.death_id), [])
        malformed = self._put(self.sam, case.death_id, {"identifiers": {"crs": _number()}, "if_updated_at": "yesterday"})
        self.assertEqual(malformed.status_code, 400)

    def test_a_stale_write_is_refused_with_a_real_updated_at_after_a_write_moved_it(self):
        case = self._submitted_case()
        first = self._write(self.sam, case.death_id, crs=_number())
        seen = first.get_json()["case"]["updated_at"]
        second_value = _number()
        second = self._put(self.sam, case.death_id, {"identifiers": {"crs": second_value}, "if_updated_at": seen})
        self.assertEqual(second.status_code, 200, second.get_json())
        newest = second.get_json()["case"]["updated_at"]
        self.assertGreater(newest, seen)  # the write moved the activity stamp
        stale = self._put(self.sam, case.death_id, {"identifiers": {"crs": _number()}, "if_updated_at": seen})
        self.assertEqual((stale.status_code, stale.get_json()["code"]), (409, "death_stale"))
        self.assertEqual(self._crs_value(case.death_id), second_value)
        fresh = self._put(self.sam, case.death_id, {"identifiers": {"crs": _number()}, "if_updated_at": newest})
        self.assertEqual(fresh.status_code, 200)
        # Without if_updated_at the last write wins.
        self.assertEqual(self._write(self.sam, case.death_id, crs=_number()).status_code, 200)

    def test_the_audit_row_names_the_grant_the_cadre_and_only_masked_traces(self):
        case = self._submitted_case()
        number = "81818181"
        self.assertEqual(self._write(self.sam, case.death_id, crs=number).status_code, 200)
        [row] = self._audit(case.death_id)
        self.assertIsNotNone(row.authorizing_grant_id)
        self.assertEqual(row.authorizing_cadre_id, self.cadres["MO"].cadre_id)
        trace = row.changes["identifier:crs"]["new"]
        self.assertEqual((row.reason, sorted(trace)), ("crs", ["bidx"]))
        self.assertNotIn(number, repr((row.reason, row.changes)))

    # -- can_edit_identifiers ----------------------------------------------------

    def _flags(self, case, *, state=None):
        """``{name: can_edit_identifiers}`` of *case* as each role's case list shows it."""
        flags = {}
        suffix = f"&status={state}" if state else ""
        for name, user in (("admin", self.admin), ("supervisor", self.sam), ("in_charge", self.incharge),
                           ("project_pi", self.pip), ("data_manager", self.dana), ("reporter", self.rita),
                           ("interviewer", self.ian), ("other_interviewer", self.ian2), ("coder", self.cody),
                           ("collaborator", self.cole), ("collaborator_pii", self.pat), ("reviewer", self.rex)):
            self._login(str(user.user_id))
            response = self.client.get(f"{CASES}?preset=deaths&limit=200{suffix}")
            self.assertEqual(response.status_code, 200, name)
            row = {c["death_id"]: c for c in response.get_json()["cases"]}.get(str(case.death_id))
            if row is not None:
                flags[name] = row["can_edit_identifiers"]
        return flags

    def test_the_shared_case_list_says_who_can_edit(self):
        case = self._submitted_case(self.rita)
        self._interviewed_by(case, self.ian)
        flags = self._flags(case)
        self.assertEqual(flags["supervisor"], True)  # present first
        self.assertEqual(
            {name: flags[name] for name in ("admin", "supervisor", "in_charge", "project_pi", "data_manager",
                                            "reporter", "interviewer")},
            dict.fromkeys(("admin", "supervisor", "in_charge", "project_pi", "data_manager", "reporter",
                           "interviewer"), True))
        self.assertEqual(
            {name: flags[name] for name in ("other_interviewer", "coder", "collaborator", "collaborator_pii",
                                            "reviewer") if name in flags},
            {name: False for name in ("other_interviewer", "coder", "collaborator", "collaborator_pii", "reviewer")
             if name in flags})
        self.assertIn("coder", flags)  # reached through the submission, still false
        self._close(case, "cancelled")
        closed = self._flags(case, state="cancelled")
        self.assertEqual({name: closed[name] for name in ("admin", "supervisor", "in_charge", "project_pi")},
                         dict.fromkeys(("admin", "supervisor", "in_charge", "project_pi"), True))
        self.assertEqual({name: closed[name] for name in ("data_manager", "reporter", "interviewer", "coder")},
                         dict.fromkeys(("data_manager", "reporter", "interviewer", "coder"), False))

    def test_every_other_list_and_the_detail_carry_the_flag(self):
        case = self._register(self.rita, unit=self.sca, identifiers={"crs": _number()})["case"]
        death_id = case["death_id"]
        self.assertIs(case["can_edit_identifiers"], True)  # the registrant's own reply
        # The reporter's registered deaths.
        self._login(str(self.rita.user_id))
        listed = {d["death_id"]: d for d in self.client.get(API + "/deaths").get_json()["deaths"]}
        self.assertIs(listed[death_id]["can_edit_identifiers"], True)
        # Ian reaches it in the worklist and the detail but did not interview it.
        self._login(str(self.ian.user_id))
        worklist = {c["death_id"]: c for c in self.client.get(API + "/cases?limit=200").get_json()["cases"]}
        self.assertIs(worklist[death_id]["can_edit_identifiers"], False)
        self.assertIs(self.client.get(f"{API}/cases/{death_id}").get_json()["case"]["can_edit_identifiers"], False)
        register = self.client.get(f"{API}/deaths?project_id={PROJECT}&site_id={SITE}").get_json()["deaths"]
        self.assertIs({d["death_id"]: d for d in register}[death_id]["can_edit_identifiers"], False)
        self._interviewed_by(self._death(death_id), self.ian)
        worklist = {c["death_id"]: c for c in self.client.get(API + "/cases?limit=200").get_json()["cases"]}
        self.assertIs(worklist[death_id]["can_edit_identifiers"], True)
        self.assertIs(self.client.get(f"{API}/cases/{death_id}").get_json()["case"]["can_edit_identifiers"], True)
        # Supervision rows and detail: a supervisor and a data manager.
        for user in (self.sam, self.dana):
            self._login(str(user.user_id))
            rows = {c["death_id"]: c for c in self.client.get(API + "/supervision/cases?limit=200").get_json()["cases"]}
            self.assertIs(rows[death_id]["can_edit_identifiers"], True, user.email)
            detail = self.client.get(f"{API}/supervision/cases/{death_id}").get_json()["case"]
            self.assertIs(detail["can_edit_identifiers"], True, user.email)
        # Closed: the data manager and the interviewer lose it, the supervisor keeps it.
        self._close(self._death(death_id), "duplicate")
        self._login(str(self.dana.user_id))
        self.assertIs(self.client.get(f"{API}/supervision/cases/{death_id}").get_json()["case"]["can_edit_identifiers"], False)
        self._login(str(self.sam.user_id))
        self.assertIs(self.client.get(f"{API}/supervision/cases/{death_id}").get_json()["case"]["can_edit_identifiers"], True)
        self._login(str(self.ian.user_id))
        self.assertIs(self.client.get(f"{API}/cases/{death_id}").get_json()["case"]["can_edit_identifiers"], False)

    def test_the_flag_costs_a_constant_number_of_statements(self):
        for _ in range(12):
            self._register(self.ian, identifiers={"crs": _number()})
        for name, user, url in (("worklist", self.ian, API + "/cases"), ("cases", self.sam, CASES + "?preset=deaths"),
                                ("supervision", self.sam, API + "/supervision/cases")):
            self._login(str(user.user_id))
            counts = []
            for limit in (2, 12):
                with _statements() as found:
                    response = self.client.get(f"{url}{'&' if '?' in url else '?'}limit={limit}")
                body = response.get_json()
                self.assertEqual(len(body["cases"]), limit, name)
                self.assertTrue(all("can_edit_identifiers" in c for c in body["cases"]), name)
                counts.append(len(found))
            self.assertEqual(counts[0], counts[1], name)

    # -- self-coding: a coder's implied interviewer grant confers nothing here -----

    def test_a_self_coding_coder_sees_a_badge_everywhere_and_cannot_write(self):
        self._login(str(self.ivy.user_id))
        created = self.client.post(API + "/deaths", headers=self._csrf_headers(), json={
            "project_id": SITES_PROJECT, "site_id": SITES_SITE, "deceased_name": "Coder Case", "deceased_sex": "male",
            "age_years": 40, "date_of_death": _dod(), "identifiers": {"reqd": "123456"}})
        self.assertEqual(created.status_code, 201, created.get_json())
        death_id = created.get_json()["case"]["death_id"]
        # The assigned interviewer sees the value and, once they have started
        # the interview, may edit it (subject present).
        self._interviewed_by(self._death(death_id), self.ivy)
        self._login(str(self.ivy.user_id))
        mine = self.client.get(f"{API}/cases/{death_id}").get_json()["case"]
        self.assertEqual(mine["identifiers"][0]["value"], "123456")
        self.assertIs(mine["can_edit_identifiers"], True)
        badge = [{"code": "reqd", "label": "Required number", "present": True}]
        self.assertEqual(ids.identifier_values_visible(self.scott, {SITES_PROJECT}), set())
        self._login(str(self.scott.user_id))
        # The coder reaches the case as an implied interviewer (subject present).
        detail = self.client.get(f"{API}/cases/{death_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json()["case"]["identifiers"], badge)
        self.assertIs(detail.get_json()["case"]["can_edit_identifiers"], False)
        worklist = {c["death_id"]: c for c in self.client.get(API + "/cases?limit=200").get_json()["cases"]}
        self.assertEqual(worklist[death_id]["identifiers"], badge)
        self.assertIs(worklist[death_id]["can_edit_identifiers"], False)
        register = self.client.get(f"{API}/deaths?project_id={SITES_PROJECT}&site_id={SITES_SITE}").get_json()["deaths"]
        row = {d["death_id"]: d for d in register}[death_id]
        self.assertEqual((row["identifiers"], row["can_edit_identifiers"]), (badge, False))
        listed = {c["death_id"]: c for c in self.client.get(CASES + "?preset=deaths&limit=200").get_json()["cases"]}
        self.assertEqual(listed[death_id]["identifiers"], badge)
        self.assertIs(listed[death_id]["can_edit_identifiers"], False)
        self.assertNotIn("123456", self.client.get(CASES + "?preset=deaths&limit=200").get_data(as_text=True))
        # No write, and no number search or number filter reveals the value.
        refused = self._write(self.scott, death_id, reqd="654321")
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(self._rows(death_id)[0].updated_by, None)
        found = self.client.get(f"{CASES}?preset=deaths&identifier_number=123456").get_json()["cases"]
        self.assertEqual(found, [])
        self._login(str(self.ivy.user_id))
        found = self.client.get(f"{CASES}?preset=deaths&identifier_number=123456").get_json()["cases"]
        self.assertEqual([c["death_id"] for c in found], [death_id])

    # -- hardening: rate limit, caps, header -------------------------------------

    def test_requests_that_carry_numbers_share_a_per_user_hourly_budget(self):
        self.app.config["IDENTIFIER_RATE_LIMIT"] = "3 per hour"
        try:
            limiter.reset()
            case = self._submitted_case()
            for _ in range(3):
                self.assertEqual(self._write(self.sam, case.death_id, crs=_number()).status_code, 200)
            # Sam's budget is spent; the fourth is refused before anything is read or written.
            before = self._crs_value(case.death_id)
            limited = self._write(self.sam, case.death_id, crs=_number())
            self.assertEqual((limited.status_code, limited.get_json()["code"]), (429, "rate_limited"))
            self.assertEqual(self._crs_value(case.death_id), before)
            # Sam's requests without numbers are not counted.
            self.assertEqual(self._patch(self.sam, case.death_id, {"remarks": "x"}).status_code, 409)  # not 429
            # Per user, one bucket for register, correct and write: Wally's own budget is whole.
            self.assertEqual(self._post(self.wally, identifiers={"crs": _number()}).status_code, 201)
            self.assertEqual(self._post(self.wally).status_code, 201)  # no numbers: not counted
            second = self._register(self.wally, unit=self.sca)["case"]  # nor this
            for _ in range(2):
                self.assertEqual(self._patch(self.wally, second["death_id"], {"identifiers": {"crs": _number()}}).status_code, 200)
            over = self._patch(self.wally, second["death_id"], {"identifiers": {"crs": _number()}})
            self.assertEqual((over.status_code, over.get_json()["code"]), (429, "rate_limited"))
            self.assertEqual(self._post(self.wally, identifiers={"crs": _number()}).status_code, 429)
            self.assertEqual(self._post(self.wally).status_code, 201)
        finally:
            self.app.config["IDENTIFIER_RATE_LIMIT"] = "30 per hour"
            limiter.reset()

    def test_the_default_budget_is_thirty_an_hour(self):
        self.assertEqual(self.app.config["IDENTIFIER_RATE_LIMIT"], "30 per hour")

    def test_a_value_over_256_characters_or_more_than_50_codes_is_refused_before_normalising(self):
        case = self._submitted_case()
        long_value = "x" * 257
        refused = self._write(self.sam, case.death_id, crs=long_value)
        body = refused.get_json()
        self.assertEqual((refused.status_code, body["fields"]), (400, ["identifiers.crs"]))
        self.assertIn("256", body["error"])
        self.assertNotIn("xxxx", refused.get_data(as_text=True))
        # At the cap the type's own rule decides (length 6..12): a different message.
        at_cap = self._write(self.sam, case.death_id, crs="1" * 256)
        self.assertEqual(at_cap.status_code, 400)
        self.assertNotIn("256", at_cap.get_json()["error"])
        too_many = self._put(self.sam, case.death_id, {"identifiers": {f"c{n:02d}": "1" for n in range(51)}})
        self.assertEqual((too_many.status_code, too_many.get_json()["fields"]), (400, ["identifiers"]))
        self.assertIn("50", too_many.get_json()["error"])
        # Registration and correction: a 422 / 422, the same words.
        for response in (self._post(self.ian, identifiers={"crs": long_value}),
                         self._patch(self.ian, self._register(self.ian)["case"]["death_id"],
                                     {"identifiers": {"crs": long_value}})):
            self.assertEqual(response.status_code, 422)
            self.assertIn("256", response.get_json()["error"])
            self.assertNotIn("xxxx", response.get_data(as_text=True))
        self.assertEqual(self._rows(case.death_id), [])
        # A body past the route's cap is a 413 whatever it holds.
        huge = self._put(self.sam, case.death_id, {"identifiers": {"crs": "1"}, "if_updated_at": "z" * 20_000})
        self.assertEqual((huge.status_code, huge.get_json()["code"]), (413, "payload_too_large"))

    def test_intake_and_case_list_responses_are_never_stored(self):
        case = self._submitted_case(self.rita)
        self._login(str(self.sam.user_id))
        responses = [
            self.client.get(CASES + "?preset=deaths"),
            self.client.get(CASES + "/filter-options"),
            self.client.get(API + "/supervision/cases"),
            self.client.get(f"{API}/supervision/cases/{case.death_id}"),
            self.client.put(f"{API}/cases/{case.death_id}/identifiers", json={"identifiers": {"crs": _number()}},
                            headers=self._csrf_headers()),
            self.client.put(f"{API}/cases/{case.death_id}/identifiers", json={"identifiers": {"crs": "1"}},
                            headers=self._csrf_headers()),   # a refusal
            self.client.put(f"{API}/cases/{uuid.uuid4()}/identifiers", json={"identifiers": {"crs": "1"}},
                            headers=self._csrf_headers()),   # a 404
            self.client.put(f"{API}/cases/{case.death_id}/identifiers", json={"identifiers": {"crs": "1"}}),  # no CSRF
        ]
        self.assertEqual([r.status_code for r in responses], [200, 200, 200, 200, 200, 400, 404, 400])
        for response in responses:
            self.assertIn("no-store", response.headers.get("Cache-Control", ""), response.status_code)
        self._login(str(self.ian.user_id))
        for response in (self.client.get(API + "/cases"), self.client.get(f"{API}/cases/{uuid.uuid4()}"),
                         self.client.get(API + "/deaths")):
            self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        g.pop("_login_user", None)
        anonymous = self.app.test_client().get(CASES + "?preset=deaths")
        self.assertEqual(anonymous.status_code, 401)
        self.assertIn("no-store", anonymous.headers.get("Cache-Control", ""))

    # -- case list filters -------------------------------------------------------

    def _listed(self, user, query, preset="deaths"):
        self._login(str(user.user_id))
        response = self.client.get(f"{CASES}?preset={preset}&limit=200&{query}")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_has_and_missing_filter_by_any_active_type_or_one_type(self):
        both = self._register(self.ian, unit=self.sca, identifiers={"crs": _number(), "mccd": "both-1"})["case"]
        crs_only = self._register(self.ian, unit=self.sca, identifiers={"crs": _number()})["case"]
        mccd_only = self._register(self.ian, unit=self.sca, identifiers={"mccd": "mccd-9"})["case"]
        none = self._register(self.ian, unit=self.sca)["case"]
        retired = self._register(self.ian, unit=self.sca)["case"]
        death = self._death(retired["death_id"])
        ciphertext, wrapped, key_id = pii_crypto.encrypt_value("OLD-1", ids.aad(death.death_id, self.old.identifier_type_id))
        db.session.add(MapDeathIdentifier(
            death_id=death.death_id, identifier_type_id=self.old.identifier_type_id, value_ciphertext=ciphertext,
            dek_wrapped=wrapped, key_id=key_id, entered_by=self.ian.user_id,
            value_blind_index=pii_crypto.blind_index(self.old.identifier_type_id.bytes, "OLD-1")))
        db.session.commit()
        everyone = {both["death_id"], crs_only["death_id"], mccd_only["death_id"], none["death_id"], retired["death_id"]}

        def ids_of(query, user=None):
            page = self._listed(user or self.sam, query)
            return {c["death_id"] for c in page["cases"]}, page

        self.assertEqual(ids_of("")[0] & everyone, everyone)  # all present without the filter
        has, page = ids_of("identifier=has")
        self.assertEqual(has & everyone, {both["death_id"], crs_only["death_id"], mccd_only["death_id"]})
        self.assertEqual(page["counts"]["total"], len(has))
        missing, page = ids_of("identifier=missing")
        # An inactive type's value does not count: the retired-only case is missing.
        self.assertEqual(missing & everyone, {none["death_id"], retired["death_id"]})
        self.assertEqual(page["counts"]["total"], len(missing))
        self.assertEqual(ids_of("identifier=has&identifier_type=crs")[0] & everyone, {both["death_id"], crs_only["death_id"]})
        self.assertEqual(ids_of("identifier=missing&identifier_type=crs")[0] & everyone,
                         {mccd_only["death_id"], none["death_id"], retired["death_id"]})
        self.assertEqual(ids_of("identifier=has&identifier_type=mccd")[0] & everyone, {both["death_id"], mccd_only["death_id"]})
        self.assertEqual(ids_of("identifier=has&identifier_type=old")[0] & everyone, set())  # inactive: no type, no match
        # The filter combines with the scope and the other filters, never widens.
        wally_case = self._register(self.wally, unit=self.scc, identifiers={"crs": _number()})["case"]
        self.assertIn(wally_case["death_id"], ids_of("identifier=has", self.dana)[0])
        self.assertNotIn(wally_case["death_id"], ids_of("identifier=has", self.ian)[0])
        self.assertIn(both["death_id"], ids_of("identifier=has", self.ian)[0])
        self.assertEqual(ids_of(f"identifier=has&project_id={SITES_PROJECT}")[0], set())

    def test_the_has_filter_is_open_to_a_badge_only_viewer_and_reveals_no_value(self):
        case = self._submitted_case(identifiers={"crs": _number()})
        key = str(case.death_id)
        for user in (self.cody, self.cole, self.rex):
            page = self._listed(user, "identifier=has")
            row = {c["death_id"]: c for c in page["cases"]}[key]
            self.assertTrue(row["identifiers"][0]["present"], user.email)
            self.assertNotIn("value", row["identifiers"][0], user.email)
            self.assertNotIn(key, {c["death_id"] for c in self._listed(user, "identifier=missing")["cases"]})

    def test_the_filter_parameters_are_validated_without_echoing_them(self):
        self._login(str(self.sam.user_id))
        for query in ("identifier=maybe", "identifier_type=crs", "identifier=has&identifier_type=Bad%20Code",
                      "identifier=has&identifier=missing", "identifier_number=" + "9" * 257,
                      "identifier_number=1&identifier_number=2"):
            response = self.client.get(f"{CASES}?{query}")
            self.assertEqual((response.status_code, response.get_json()["code"]), (400, "invalid_request"), query)
            for echo in ("maybe", "Bad", "9999"):
                self.assertNotIn(echo, response.get_data(as_text=True))

    def test_an_exact_number_search_finds_the_case_through_the_blind_index_for_value_viewers_only(self):
        number = _number()
        case = self._submitted_case(self.wally, identifiers={"crs": number, "mccd": "mccd/12"})
        key = str(case.death_id)
        decoy = self._submitted_case(self.wally, identifiers={"crs": _number()})
        for user in (self.sam, self.dana, self.incharge, self.pip, self.admin, self.pat):
            page = self._listed(user, f"identifier_number={number}")
            self.assertEqual([c["death_id"] for c in page["cases"]], [key], user.email)
            self.assertEqual(page["counts"]["total"], 1, user.email)
            self.assertEqual(page["cases"][0]["identifiers"][0]["value"], number)
        # The same number, spelled differently, is the same number.
        for text in ("mccd/12", " MCCD/12 ", "Mccd/12"):
            self.assertEqual([c["death_id"] for c in self._listed(self.sam, f"identifier_number={text}")["cases"]], [key], text)
        # A type narrows it; a wrong type matches nothing; a near miss matches nothing.
        self.assertEqual(len(self._listed(self.sam, f"identifier_number={number}&identifier=has&identifier_type=crs")["cases"]), 1)
        self.assertEqual(self._listed(self.sam, f"identifier_number={number}&identifier=has&identifier_type=mccd")["cases"], [])
        self.assertEqual(self._listed(self.sam, f"identifier_number={number}0")["cases"], [])
        self.assertNotIn(str(decoy.death_id), {c["death_id"] for c in self._listed(self.sam, f"identifier_number={number}")["cases"]})
        # Badge-only viewers reach the case (subject present) and get nothing, no error.
        for user in (self.cody, self.cole, self.carl, self.rex, self.tess):
            self.assertIn(key, {c["death_id"] for c in self._listed(user, "")["cases"]}, user.email)
            page = self._listed(user, f"identifier_number={number}")
            self.assertEqual((page["cases"], page["counts"]["total"]), ([], 0), user.email)
        # Scope never widens: Ian does not reach a case of SCC, whoever holds the number.
        far = self._submitted_case(self.wally, unit=self.scc, identifiers={"crs": number})
        self.assertIn(str(far.death_id), {c["death_id"] for c in self._listed(self.dana, f"identifier_number={number}")["cases"]})
        self.assertNotIn(str(far.death_id), {c["death_id"] for c in self._listed(self.sam, f"identifier_number={number}")["cases"]})

    def test_the_number_search_is_rate_limited_and_logs_no_number(self):
        number = _number()
        self._submitted_case(identifiers={"crs": number})
        records: list[str] = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler = Capture(level=logging.DEBUG)
        root = logging.getLogger()
        previous = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        self.app.config["IDENTIFIER_SEARCH_RATE_LIMIT"] = "2 per hour"
        try:
            limiter.reset()
            self.assertEqual(len(self._listed(self.sam, f"identifier_number={number}")["cases"]), 1)
            self._listed(self.sam, f"identifier_number={number}")
            self._login(str(self.sam.user_id))
            limited = self.client.get(f"{CASES}?identifier_number={number}")
            self.assertEqual((limited.status_code, limited.get_json()["code"]), (429, "rate_limited"))
            # A list without a number is not counted.
            self.assertEqual(self.client.get(CASES).status_code, 200)
            self.assertEqual(self.client.get(f"{CASES}?identifier=has").status_code, 200)
        finally:
            root.removeHandler(handler)
            root.setLevel(previous)
            self.app.config["IDENTIFIER_SEARCH_RATE_LIMIT"] = "120 per hour"
            limiter.reset()
        self.assertNotIn(number, "\n".join(records))

    # -- possible duplicates: the gaps the review named ---------------------------

    def _pair(self, **kwargs):
        value = _number()
        a = self._register(self.ian, unit=self.sca, deceased_name="Zed Alpha", identifiers={"crs": value})["case"]
        b = self._register(self.ian, unit=self.scb, deceased_name="Quentin Bravo", identifiers={"crs": value},
                           date_of_death=_dod(40), deceased_sex="male")["case"]
        return self._death(a["death_id"]), self._death(b["death_id"])

    def test_a_shared_number_candidate_is_dropped_when_the_candidate_or_subject_is_closed_or_flagged(self):
        subject, candidate = self._pair()
        found = intake_svc.possible_duplicates(self.ian, subject)
        self.assertEqual([r["death_id"] for r in found], [str(candidate.death_id)])  # present first
        for state in ("cancelled", "duplicate"):
            candidate.status = state
            db.session.commit()
            self.assertEqual(intake_svc.possible_duplicates(self.ian, subject), [], f"candidate {state}")
            candidate.status = "registered"
            subject.status = state
            db.session.commit()
            self.assertEqual(intake_svc.possible_duplicates(self.ian, subject), [], f"subject {state}")
            subject.status = "registered"
            db.session.commit()
        self.assertEqual(len(intake_svc.possible_duplicates(self.ian, subject)), 1)  # restored
        subject.pending_flag = "cancel"
        db.session.commit()
        self.assertEqual(intake_svc.possible_duplicates(self.ian, subject), [])
        subject.pending_flag = None
        db.session.commit()
        self.assertEqual(len(intake_svc.possible_duplicates(self.ian, subject)), 1)

    def test_a_type_without_project_uniqueness_is_no_possible_duplicate(self):
        a = self._register(self.ian, unit=self.sca, deceased_name="Zed Alpha", identifiers={"mccd": "same-4242"})["case"]
        b = self._register(self.ian, unit=self.scb, deceased_name="Quentin Bravo", identifiers={"mccd": "same-4242"},
                           date_of_death=_dod(40), deceased_sex="male")["case"]
        self.assertEqual(len(self._rows(a["death_id"])), 1)
        self.assertEqual(len(self._rows(b["death_id"])), 1)
        self.assertEqual(intake_svc.possible_duplicates(self.ian, self._death(a["death_id"])), [])
        # The project-unique type on the same two cases is a candidate (subject present).
        for case in (a, b):
            self.assertEqual(self._patch(self.ian, case["death_id"], {"identifiers": {"crs": "33445566"}}).status_code, 200)
        self.assertEqual(len(intake_svc.possible_duplicates(self.ian, self._death(a["death_id"]))), 1)

    # -- review fixes: the correction path's write gate, per-case value
    # visibility, one entry per active type, the supervisor-shaped reply, the
    # unbounded number search and the search budget ------------------------------

    # -- 1: PATCH identifiers has the write's own gate ------------------------

    def test_a_patch_with_numbers_needs_the_write_permission_not_just_reach(self):
        case = self._register(self.wally, unit=self.sca, identifiers={"crs": "70707070"})["case"]
        death_id = case["death_id"]
        # ian2 reaches the case (his unit) and may correct its details ...
        self.assertEqual(self._patch(self.ian2, death_id, {"remarks": "ok"}).status_code, 200)
        # ... but not its numbers: not the registrant, never interviewed.
        refused = self._patch(self.ian2, death_id, {"identifiers": {"crs": _number()}})
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (403, "forbidden"))
        mixed = self._patch(self.ian2, death_id, {"remarks": "no", "identifiers": {"crs": _number()}})
        self.assertEqual(mixed.status_code, 403)
        self.assertNotEqual(self._death(death_id).remarks, "no")  # refused whole
        self.assertEqual(self._crs_value(death_id), "70707070")
        self.assertEqual(len(self._audit(death_id)), 1)  # only the registration's own
        self.assertIs(self._get_case(self.ian2, death_id)["can_edit_identifiers"], False)
        # The registrant, who never interviewed, may correct their own.
        number = _number()
        self.assertIs(self._get_case(self.wally, death_id)["can_edit_identifiers"], True)
        self.assertEqual(self._patch(self.wally, death_id, {"identifiers": {"crs": number}}).status_code, 200)
        self.assertEqual(self._crs_value(death_id), number)
        # A duplicate warning is not a probe for a teammate either.
        probe = self._patch(self.ian2, death_id, {"identifiers": {"crs": "40404040"}})
        self.assertEqual((probe.status_code, "warnings" in probe.get_json()), (403, False))

    def test_a_self_coding_coder_cannot_patch_numbers(self):
        self._login(str(self.ivy.user_id))
        created = self.client.post(API + "/deaths", headers=self._csrf_headers(), json={
            "project_id": SITES_PROJECT, "site_id": SITES_SITE, "deceased_name": "Coder Case", "deceased_sex": "male",
            "age_years": 40, "date_of_death": _dod(), "identifiers": {"reqd": "123456"}})
        death_id = created.get_json()["case"]["death_id"]
        self.assertEqual(self._patch(self.ivy, death_id, {"remarks": "mine"}).status_code, 200)  # subject reaches
        self.assertEqual(self._patch(self.scott, death_id, {"remarks": "theirs"}).status_code, 200)  # reaches too
        refused = self._patch(self.scott, death_id, {"identifiers": {"reqd": "654321"}})
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(ids.decrypt_row(self._rows(death_id)[0]), "123456")

    def test_the_flag_and_both_writes_agree_for_every_role_and_state(self):
        for state in ("registered", "cancelled", "duplicate"):
            case = self._submitted_case(self.wally)
            self._interviewed_by(case, self.ian)
            if state != "registered":
                self._close(case, state)
            death_id = str(case.death_id)
            for name in ("admin", "sam", "incharge", "pip", "dana", "wally", "ian", "ian2", "rita", "cody", "pat", "mia"):
                user = self.admin if name == "admin" else getattr(self, name)
                flag = self._flag_of(user, death_id, state)
                if flag is None:
                    continue  # the case is outside the caller's reach
                before = self._crs_value(death_id)
                put = self._write(user, death_id, crs=_number())
                self.assertEqual(put.status_code == 200, flag, (state, name, "put"))
                if put.status_code == 200:
                    continue
                after = self._patch(user, death_id, {"identifiers": {"crs": _number()}})
                self.assertEqual(after.status_code == 200, flag, (state, name, "patch"))
                self.assertEqual(self._crs_value(death_id), before, (state, name))

    def _flag_of(self, user, death_id, state):
        """The case list's ``can_edit_identifiers`` for the case, None outside the caller's reach."""
        self._login(str(user.user_id))
        status = "" if state == "registered" else f"&status={state}"
        rows = self.client.get(f"{CASES}?preset=deaths&limit=200{status}").get_json()["cases"]
        return next((r["can_edit_identifiers"] for r in rows if r["death_id"] == death_id), None)

    def _get_case(self, user, death_id):
        self._login(str(user.user_id))
        response = self.client.get(f"{API}/cases/{death_id}")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["case"]

    def test_a_register_replay_writes_no_numbers_and_needs_no_gate(self):
        client_id = str(uuid.uuid4())
        first = self._post(self.wally, client_death_id=client_id, identifiers={"crs": "80808080"})
        self.assertEqual(first.status_code, 201, first.get_json())
        death_id = first.get_json()["case"]["death_id"]
        audits = len(self._audit(death_id))
        replay = self._post(self.wally, client_death_id=client_id, identifiers={"crs": _number()})
        self.assertEqual(replay.status_code, 200)
        self.assertNotIn("warnings", replay.get_json())
        self.assertEqual(self._crs_value(death_id), "80808080")
        self.assertEqual(len(self._audit(death_id)), audits)

    # -- 2: values are per case ------------------------------------------------

    def _self_coding_on(self, on):
        db.session.get(VaProjectMaster, PROJECT).self_coding_enabled = on
        db.session.commit()
        invalidate_all()

    def test_values_follow_the_case_not_the_project_for_a_user_with_an_implied_interviewer_reach(self):
        near = self._submitted_case(self.wally, unit=self.sca, identifiers={"crs": _number()})
        far = self._submitted_case(self.wally, unit=self.scc, identifiers={"crs": _number()})
        near_id, far_id = str(near.death_id), str(far.death_id)
        self._self_coding_on(True)
        try:
            # Mia's assigned interviewer grant is SCA's; the implied grant reaches SCC too.
            self.assertEqual(ids.identifier_values_visible(self.mia, {PROJECT}), {PROJECT})
            expected_near = self._crs_entry(near_id, value=True)
            expected_far = self._crs_entry(far_id, value=False)
            self._login(str(self.mia.user_id))
            # GET /intake/cases (the worklist)
            worklist = {c["death_id"]: c for c in self.client.get(f"{API}/cases?limit=200").get_json()["cases"]}
            self.assertEqual(worklist[near_id]["identifiers"][0], expected_near)  # subject present first
            self.assertEqual(worklist[far_id]["identifiers"][0], expected_far)
            # GET /intake/cases/<id>
            self.assertEqual(self.client.get(f"{API}/cases/{near_id}").get_json()["case"]["identifiers"][0], expected_near)
            self.assertEqual(self.client.get(f"{API}/cases/{far_id}").get_json()["case"]["identifiers"][0], expected_far)
            # GET /intake/deaths (the register of one project-site)
            register = {d["death_id"]: d for d in self.client.get(
                f"{API}/deaths?project_id={PROJECT}&site_id={SITE}").get_json()["deaths"]}
            self.assertEqual(register[near_id]["identifiers"][0], expected_near)
            self.assertEqual(register[far_id]["identifiers"][0], expected_far)
            # GET /cases (the shared list)
            shared = self._list_cases(self.mia)
            self.assertEqual(shared[near_id]["identifiers"][0], expected_near)
            self.assertEqual(shared[far_id]["identifiers"][0], expected_far)
            self.assertNotIn("value", shared[far_id]["identifiers"][0])
            # The service default is per case too.
            direct = ids.identifier_payloads(self.mia, [near, far])
            self.assertEqual((direct[near.death_id][0], direct[far.death_id][0]), (expected_near, expected_far))
        finally:
            self._self_coding_on(False)

    def _crs_entry(self, death_id, *, value):
        if not value:
            return {"code": "crs", "label": "CRS number", "present": True}
        return {"code": "crs", "label": "CRS number", "value": self._crs_value(death_id)}

    def test_supervision_rows_and_detail_show_values_only_in_the_supervised_reach(self):
        # Mix is interviewer and supervisor at PH1: SCA is both; SCC (PH2) is neither.
        case = self._submitted_case(self.wally, unit=self.sca, identifiers={"crs": _number()})
        self._login(str(self.mix.user_id))
        listed = {c["death_id"]: c for c in self.client.get(f"{API}/supervision/cases?limit=200").get_json()["cases"]}
        self.assertEqual(listed[str(case.death_id)]["identifiers"][0], self._crs_entry(str(case.death_id), value=True))
        detail = self.client.get(f"{API}/supervision/cases/{case.death_id}").get_json()["case"]
        self.assertEqual(detail["identifiers"][0], self._crs_entry(str(case.death_id), value=True))

    # -- 3: one entry per active type for a values viewer ---------------------

    def test_a_values_viewer_gets_every_active_type_and_a_badge_viewer_a_present_flag(self):
        case = self._submitted_case(self.wally, identifiers={"mccd": "abc-1234"})
        key = case.death_id
        seen = ids.identifier_payloads(self.sam, [case])[key]
        self.assertEqual(seen, [{"code": "crs", "label": "CRS number", "value": None},
                                {"code": "mccd", "label": "MCCD number", "value": "ABC-1234"}])
        badge = ids.identifier_payloads(self.cody, [case])[key]
        self.assertEqual(badge, [{"code": "crs", "label": "CRS number", "present": False},
                                 {"code": "mccd", "label": "MCCD number", "present": True}])
        self.assertTrue(all("value" not in e for e in badge))

    # -- 4: the intake type list for admin ------------------------------------

    def test_admin_reads_the_intake_types_of_any_project_and_a_stranger_does_not(self):
        for project in (PROJECT, SITES_PROJECT, "NOSUCH1"):
            self._login(str(self.admin.user_id))
            response = self.client.get(f"{API}/identifier-types?project_id={project}")
            self.assertEqual(response.status_code, 200, project)
        self._login(str(self.admin.user_id))
        listed = self.client.get(f"{API}/identifier-types?project_id={PROJECT}").get_json()["identifier_types"]
        self.assertEqual([t["code"] for t in listed], ["crs", "mccd"])
        self._login(str(self.ivy.user_id))  # an interviewer of the other project
        refused = self.client.get(f"{API}/identifier-types?project_id={PROJECT}")
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (403, "project_forbidden"))

    # -- 5: the write's reply is trimmed for a supervisor ----------------------

    def test_a_supervising_caller_gets_the_trimmed_row_and_a_field_caller_the_detail(self):
        case = self._submitted_case(self.wally, identifiers={"crs": _number()})
        contact = ("informant", "household_address", "links", "my_draft_id", "prefill", "deceased")
        for who in (self.sam, self.incharge, self.pip, self.admin):
            response = self._write(who, case.death_id, crs=_number())
            self.assertEqual(response.status_code, 200, who.email)
            body = response.get_json()["case"]
            self.assertTrue(body["identifiers"][0]["value"])  # a values viewer, subject present
            self.assertIn("can_edit_identifiers", body)
            self.assertIn("updated_at", body)
            for key in contact:
                self.assertNotIn(key, body, (who.email, key))
            self.assertNotIn("phone", str(body))
        # An interviewer who interviewed it keeps the interviewer detail.
        self._interviewed_by(case, self.ian)
        own = self._write(self.ian, case.death_id, crs=_number()).get_json()["case"]
        self.assertIn("informant", own)
        self.assertIn("links", own)
        # PATCH keeps its previous full detail for a supervisor (only the PUT is trimmed).
        patched = self._patch(self.sam, self._register(self.wally, unit=self.sca)["case"]["death_id"],
                              {"identifiers": {"crs": _number()}}).get_json()["case"]
        self.assertIn("deceased", patched)
        self.assertIn("identifiers", patched)

    # -- 6: the number search reads every type ---------------------------------

    def test_the_number_search_pages_the_types_and_misses_none(self):
        extra = [MasDeathIdentifierType(project_id=PROJECT, code=f"ex{i}", label=f"Extra {i}", sort_order=10 + i,
                                        min_length=4, max_length=12, char_type="digits", uniqueness_scope="none")
                 for i in range(4)]
        db.session.add_all(extra)
        db.session.commit()
        number = _number()
        try:
            # The type found last by id, so a capped read would skip it.
            last = max(extra, key=lambda t: t.identifier_type_id)
            case = self._submitted_case(self.wally, identifiers={last.code: number})
            for chunk in (1, 2, 1000):
                with mock.patch.object(case_list_service, "_NUMBER_TYPES_CHUNK", chunk):
                    found = self._listed(self.sam, f"identifier_number={number}")["cases"]
                self.assertEqual([c["death_id"] for c in found], [str(case.death_id)], chunk)
        finally:
            for t in extra:
                t.is_active = False
            db.session.commit()

    # -- 7: search has its own budget ------------------------------------------

    def test_the_search_budget_is_separate_from_the_write_budget(self):
        self.assertEqual(self.app.config["IDENTIFIER_SEARCH_RATE_LIMIT"], "120 per hour")
        number = _number()
        case = self._submitted_case(identifiers={"crs": number})
        self.app.config["IDENTIFIER_RATE_LIMIT"] = "1 per hour"
        try:
            limiter.reset()
            for _ in range(3):  # more searches than the write budget allows
                self.assertEqual(len(self._listed(self.sam, f"identifier_number={number}")["cases"]), 1)
            self.assertEqual(self._write(self.sam, case.death_id, crs=_number()).status_code, 200)
            self.assertEqual(self._write(self.sam, case.death_id, crs=_number()).status_code, 429)  # writes still limited
            self._listed(self.sam, f"identifier_number={number}")  # a search is still answered (200), not 429
        finally:
            self.app.config["IDENTIFIER_RATE_LIMIT"] = "30 per hour"
            limiter.reset()
