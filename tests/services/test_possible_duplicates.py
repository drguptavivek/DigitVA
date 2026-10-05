"""The automatic possible-duplicate check (phase 6, digitva-vzk.11).

Policy: docs/policy/web-intake.md, "Built in phase 6". Covers the matching
rules (date window edges, unknown sex, name normalisation and variants, unit
neighbourhood, project, cancelled, confirmed duplicate, self, a pending flag,
caller scope), the details an in-scope hint carries, the worklist's batched check
(one statement), the case API (scope 404) and that a possible duplicate never blocks submit.
"""
import uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.models.mas_organization import MasOrgLevel, MasOrgUnit
from app.services import web_intake_service as intake_svc
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase

DOD = date.today() - timedelta(days=20)


class PossibleDuplicateTests(BaseTestCase):
    PROJECT_ID = "PDC01"
    SITE_ID = "PD01"
    OTHER_PROJECT_ID = "PDC02"
    OTHER_SITE_ID = "PD02"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        pairs = ((cls.PROJECT_ID, cls.SITE_ID), (cls.OTHER_PROJECT_ID, cls.OTHER_SITE_ID))
        for project_id, site_id in pairs:
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=project_id,
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, web_intake_mode="both",
            ))
            db.session.add(VaSiteMaster(
                site_id=site_id, site_name=site_id, site_abbr=site_id,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        for project_id, site_id in pairs:
            db.session.add(VaProjectSites(
                project_id=project_id, site_id=site_id, project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
        db.session.flush()
        for project_id, site_id in pairs:
            _ensure_legacy_project_site_rows(project_id, site_id)
            db.session.add(VaForms(
                form_id=f"{project_id}{site_id}01", project_id=project_id, site_id=site_id,
                odk_form_id=f"ODK_{project_id}", odk_project_id="7", form_type="WHO VA 2022",
                form_source="odk", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        db.session.flush()

        levels = []
        for depth, code in enumerate(("district", "block", "village"), start=1):
            level = MasOrgLevel(project_id=cls.PROJECT_ID, level_code=code, level_name=code, depth=depth)
            db.session.add(level)
            levels.append(level)
        db.session.flush()
        cls.unit = {}

        def unit(code, depth, parent=None):
            path = f"{parent.path}.{code}" if parent else code
            row = MasOrgUnit(
                org_unit_id=uuid.uuid4(), project_id=cls.PROJECT_ID,
                org_level_id=levels[depth - 1].org_level_id, unit_code=code, unit_name=f"Unit {code}",
                path=path, is_active=True, parent_org_unit_id=parent.org_unit_id if parent else None,
            )
            db.session.add(row)
            db.session.flush()
            cls.unit[code] = row
            return row

        # D1 -> (B1 -> G1), B2 ; D2 -> B3
        d1, d2 = unit("PDD1", 1), unit("PDD2", 1)
        b1 = unit("PDB1", 2, d1)
        unit("PDB2", 2, d1)
        unit("PDB3", 2, d2)
        unit("PDG1", 3, b1)

        def grant(user, **scope):
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.interviewer, notes="dup check test",
                grant_status=VaStatuses.active, **scope,
            ))

        cls.alice = cls._get_or_make_user("pd.alice@test.local", "DupCheck123")
        cls.carol = cls._get_or_make_user("pd.carol@test.local", "DupCheck123")
        grant(cls.alice, scope_type=VaAccessScopeTypes.project, project_id=cls.PROJECT_ID)
        grant(cls.alice, scope_type=VaAccessScopeTypes.project, project_id=cls.OTHER_PROJECT_ID)
        # Carol reaches block B3 only, not its parent D2.
        grant(cls.carol, scope_type=VaAccessScopeTypes.org_unit, org_unit_id=cls.unit["PDB3"].org_unit_id)
        db.session.commit()
        cls.carol_id = str(cls.carol.user_id)
        cls.alice_id = str(cls.alice.user_id)

    # ── helpers ────────────────────────────────────────────────────────────

    def _case(self, unit="PDB1", name="Kamla Devi", sex="female", dod=DOD, user=None, project=None):
        project_id, site_id = project or (self.PROJECT_ID, self.SITE_ID)
        return intake_svc.register_death(
            user or self.alice, project_id=project_id, site_id=site_id,
            org_unit_id=str(self.unit[unit].org_unit_id) if unit else None,
            deceased_name=name, deceased_sex=sex, date_of_death=dod.isoformat(),
        )

    def _matches(self, case, user=None):
        return [row["death_id"] for row in intake_svc.possible_duplicates(user or self.alice, case)]

    # ── matching rules ─────────────────────────────────────────────────────

    def test_date_of_death_within_three_days_matches_and_four_does_not(self):
        subject = self._case()
        edges = {days: self._case(dod=DOD + timedelta(days=days)) for days in (-4, -3, 3, 4)}
        found = self._matches(subject)
        self.assertIn(str(edges[-3].death_id), found)
        self.assertIn(str(edges[3].death_id), found)
        self.assertNotIn(str(edges[-4].death_id), found)
        self.assertNotIn(str(edges[4].death_id), found)

    def test_sex_must_agree_unless_either_is_unknown(self):
        subject = self._case()
        unknown = self._case(sex="unknown")
        undetermined = self._case(sex="undetermined")
        # Sex is only ever missing on a "details pending" direct start.
        missing = self._case()
        missing.status, missing.deceased_sex, missing.started_by_user_id = "draft_identity", None, self.alice.user_id
        male = self._case(sex="male")
        found = self._matches(subject)
        for case in (unknown, undetermined, missing):
            self.assertIn(str(case.death_id), found)
        self.assertNotIn(str(male.death_id), found)
        # An unknown subject matches either sex.
        self.assertIn(str(male.death_id), self._matches(unknown))

    def test_names_match_across_titles_punctuation_spaces_and_case(self):
        subject = self._case(name="Kamla Devi")
        variants = [self._case(name=n) for n in ("Smt. KAMLA   devi", "Late Kamla-Devi", "Kamala Devi")]
        other = self._case(name="Ramesh Singh")
        found = self._matches(subject)
        for case in variants:
            self.assertIn(str(case.death_id), found, case.deceased_name)
        self.assertNotIn(str(other.death_id), found)

    def test_unit_neighbourhood_is_same_parent_child_or_sibling(self):
        subject = self._case(unit="PDB1")
        near = {code: self._case(unit=code) for code in ("PDB1", "PDD1", "PDG1", "PDB2")}
        far = {code: self._case(unit=code) for code in ("PDB3", "PDD2")}
        found = self._matches(subject)
        for code, case in near.items():
            self.assertIn(str(case.death_id), found, code)
        for code, case in far.items():
            self.assertNotIn(str(case.death_id), found, code)
        # A grandchild is two levels away, and two top-level units are not siblings.
        self.assertNotIn(str(near["PDG1"].death_id), self._matches(near["PDD1"]))
        self.assertNotIn(str(far["PDD2"].death_id), self._matches(near["PDD1"]))

    def test_other_project_cancelled_confirmed_duplicate_and_self_are_excluded(self):
        subject = self._case()
        kept = self._case()
        other_project = self._case(unit=None, project=(self.OTHER_PROJECT_ID, self.OTHER_SITE_ID))
        cancelled = self._case()
        cancelled.status = "cancelled"
        confirmed = self._case()
        confirmed.status = "duplicate"
        db.session.flush()
        found = self._matches(subject)
        self.assertIn(str(kept.death_id), found)
        for case in (other_project, cancelled, confirmed, subject):
            self.assertNotIn(str(case.death_id), found)
        # The other project's case has no unit, so only the project rule stops it.
        self.assertEqual(self._matches(other_project), [])

    def test_names_are_normalised_before_comparing(self):
        normalised = db.session.scalar(
            sa.select(intake_svc._normalised_name(sa.literal("Late Smt. Kamla-Devi  ")))
        )
        self.assertEqual(normalised, "kamla devi")
        # A title inside a word stays: only whole words are dropped.
        self.assertEqual(db.session.scalar(sa.select(intake_svc._normalised_name(sa.literal("Srinivas")))),
                         "srinivas")

    def test_a_flagged_case_gets_no_hint(self):
        subject = self._case()
        twin = self._case()
        self.assertIn(str(twin.death_id), self._matches(subject))
        subject.pending_flag = "duplicate"
        subject.duplicate_of_death_id = twin.death_id
        db.session.flush()
        self.assertEqual(self._matches(subject), [])

    def test_a_case_without_name_or_date_of_death_gets_none(self):
        self._case()
        draft = intake_svc.start_draft(self.alice, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                                       org_unit_id=str(self.unit["PDB1"].org_unit_id))
        pending = db.session.get(VaDeathRegister, draft.death_id)
        self.assertEqual(intake_svc.possible_duplicates(self.alice, pending), [])

    def test_candidates_stay_inside_the_callers_scope(self):
        subject = self._case(unit="PDB3")
        parent = self._case(unit="PDD2")
        self.assertIn(str(parent.death_id), self._matches(subject))
        self.assertNotIn(str(parent.death_id), self._matches(subject, user=self.carol))

    def test_an_in_scope_candidate_carries_its_details_and_an_out_of_scope_one_leaves_no_trace(self):
        subject = self._case(unit="PDB3", name="Sita Rani")
        near = self._case(unit="PDB3", name="Sita Rani", user=self.alice)
        near.age_years, near.informant_name, near.started_by_user_id = 61, "Mohan Rani", self.carol.user_id
        near.address_village_ward = "Kandaghat"
        far = self._case(unit="PDD2", name="Sita Rani", sex="female")
        far.informant_name = "Hidden Informant"
        db.session.flush()

        hints = intake_svc.possible_duplicates(self.carol, subject)
        # The in-scope one is present first, so its absence-check below is meaningful.
        self.assertEqual([h["death_id"] for h in hints], [str(near.death_id)])
        self.assertEqual(hints[0], {
            "death_id": str(near.death_id), "unique_id": near.unique_id, "unit_name": "Unit PDB3",
            "state": near.status, "score": 1.0, "deceased_name": "Sita Rani",
            "date_of_death": DOD.isoformat(), "village": "Kandaghat", "age_years": 61, "sex": "female",
            "informant_name": "Mohan Rani", "previous_interviewer_name": self.carol.name,
        })
        # Alice reaches both: with nobody having started it, no interviewer is named
        # (the registrant is not assumed to be one).
        by_id = {h["death_id"]: h for h in intake_svc.possible_duplicates(self.alice, subject)}
        self.assertIsNone(by_id[str(far.death_id)]["previous_interviewer_name"])
        self.assertEqual(by_id[str(far.death_id)]["informant_name"], "Hidden Informant")
        # No recorded village is null, never the unit name.
        self.assertIsNone(by_id[str(far.death_id)]["village"])
        self.assertEqual(by_id[str(far.death_id)]["unit_name"], "Unit PDD2")
        # Carol never sees the other one: no id, no detail.
        self.assertNotIn(far.unique_id, repr(hints))
        self.assertNotIn("Hidden Informant", repr(hints))

    def test_pending_cancelled_and_duplicate_candidates_leave_no_id_or_name(self):
        subject = self._case(unit="PDB3", name="Gita Bai")
        active = self._case(unit="PDB3", name="Gita Bai")
        # Another interviewer's "details pending" start is theirs alone.
        pending = self._case(unit="PDB3", name="Gita Baai", user=self.alice)
        pending.status, pending.started_by_user_id = "draft_identity", self.alice.user_id
        cancelled = self._case(unit="PDB3", name="Gita Bai")
        cancelled.status = "cancelled"
        confirmed = self._case(unit="PDB3", name="Gita Bai")
        confirmed.status = "duplicate"
        db.session.flush()

        for viewer in (self.carol, self.alice):
            hints = intake_svc.possible_duplicates(viewer, subject)
            ids = [h["death_id"] for h in hints]
            self.assertIn(str(active.death_id), ids)  # present, so the absences below mean something
            if viewer is self.carol:
                self.assertNotIn(str(pending.death_id), ids)
                self.assertNotIn(pending.unique_id, repr(hints))
                self.assertNotIn("Gita Baai", repr(hints))
            for closed in (cancelled, confirmed):
                self.assertNotIn(str(closed.death_id), ids)
                self.assertNotIn(closed.unique_id, repr(hints))

    def test_candidate_details_cost_no_extra_statements_per_candidate(self):
        subject = self._case(unit="PDB1")
        counts = []
        for extra in (1, 4):
            for _ in range(extra):
                self._case(unit="PDB2")
            statements = []

            def record(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)

            sa.event.listen(db.engine, "before_cursor_execute", record)
            try:
                hints = intake_svc.possible_duplicates(self.alice, subject)
            finally:
                sa.event.remove(db.engine, "before_cursor_execute", record)
            counts.append((len(hints), len(statements)))
        self.assertGreater(counts[1][0], counts[0][0])
        self.assertEqual(counts[0][1], counts[1][1], counts)

    # ── worklist batch ─────────────────────────────────────────────────────

    def test_the_worklist_page_check_is_one_statement(self):
        subject = self._case()
        twin = self._case(name="Kamla Devii")
        lone = self._case(name="Ramesh Singh", sex="male")
        db.session.commit()
        ids = [subject.death_id, twin.death_id, lone.death_id]
        scope = intake_svc._worklist_scope(self.alice)

        statements = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", record)
        try:
            rows = intake_svc._possible_duplicate_rows(ids, scope, per_case=3)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", record)
        self.assertEqual(len(statements), 1, statements)
        pairs = {(r.subject_id, r.death_id) for r in rows}
        self.assertIn((subject.death_id, twin.death_id), pairs)
        self.assertIn((twin.death_id, subject.death_id), pairs)
        self.assertNotIn(lone.death_id, {r.subject_id for r in rows})

        result = intake_svc.list_worklist(self.alice)
        self.assertEqual(
            [d["death_id"] for d in result["possible_duplicates"][subject.death_id]], [str(twin.death_id)]
        )
        self.assertNotIn(lone.death_id, result["possible_duplicates"])

    # ── API and submit ─────────────────────────────────────────────────────

    def test_api_lists_candidates_without_contact_details_and_404s_out_of_scope(self):
        subject = self._case(unit="PDB1")
        twin = self._case(unit="PDB2")
        db.session.commit()
        url = f"/api/v1/intake/cases/{subject.death_id}/possible-duplicates"

        self._login(self.alice_id)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.get_json())
        rows = response.get_json()["possible_duplicates"]
        self.assertEqual([r["death_id"] for r in rows], [str(twin.death_id)])
        self.assertEqual(rows[0]["unique_id"], twin.unique_id)
        # Identity of an in-scope case, never phone or address.
        self.assertEqual(set(rows[0]), {
            "death_id", "unique_id", "unit_name", "state", "score", "deceased_name", "date_of_death",
            "village", "age_years", "sex", "informant_name", "previous_interviewer_name",
        })
        self.assertEqual((rows[0]["deceased_name"], rows[0]["sex"]), ("Kamla Devi", "female"))

        worklist = self.client.get("/api/v1/intake/cases").get_json()["cases"]
        row = {r["death_id"]: r for r in worklist}[str(subject.death_id)]
        self.assertEqual([d["unique_id"] for d in row["possible_duplicates"]], [twin.unique_id])

        self._login(self.carol_id)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/intake/cases/not-a-uuid/possible-duplicates").status_code, 404)

    def test_a_possible_duplicate_never_blocks_submit(self):
        self._case(name="Ravi Kumar", sex="male")
        draft = intake_svc.start_draft(self.alice, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                                       org_unit_id=str(self.unit["PDB1"].org_unit_id))
        completion = {"valid": True, "issues": [], "data": {
            "Id10013": "yes", "Id10017": "Ravi", "Id10018": "Kumar", "Id10019": "male",
            "Id10023": DOD.isoformat(), "finalAgeInYears": "40", "narr_language": "english",
        }}
        intake_svc.save_draft_sections(draft, sections={"info": completion["data"]}, actor=self.alice)
        case = db.session.get(VaDeathRegister, draft.death_id)
        self.assertEqual(len(intake_svc.possible_duplicates(self.alice, case)), 1)

        intake_svc.submit_draft(draft, self.alice, completion=completion)
        self.assertEqual(case.status, "submitted")
        self.assertIsNone(case.pending_flag)
