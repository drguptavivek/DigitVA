"""The case state machine and the worklist (digitva-vzk.4, phases 2 and 3).

Policy: docs/policy/web-intake.md, "Case worklist and interview states".
Covers:
  - the transition table: allowed moves write one audit row each, refused
    moves change nothing
  - supervisor-only moves are refused while ``is_interview_supervisor_for``
    fails closed (digitva-vzk.5 adds the role)
  - a direct start creates its case; draft saves fill the identity and edits
    flow back; submission moves the case to ``submitted``
  - the worklist: team cases in scope only, "details pending" for its starter
    only, the mine and state filters, keyset paging
"""
import json
import uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    MapCaseTransition,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaWebIntakeDraft,
)
from app.models.mas_organization import MasOrgLevel, MasOrgUnit
from app.services import case_transition_service as cases
from app.services import web_intake_service as intake_svc
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase


def _dod(days=10):
    return (date.today() - timedelta(days=days)).isoformat()


class CaseWorklistTests(BaseTestCase):
    PROJECT_ID = "WLC01"
    SITE_ID = "WL01"
    OTHER_PROJECT_ID = "WLC02"
    OTHER_SITE_ID = "WL02"

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

        level = MasOrgLevel(project_id=cls.PROJECT_ID, level_code="district",
                            level_name="District", depth=1)
        db.session.add(level)
        db.session.flush()
        cls.units = []
        for code in ("WLU1", "WLU2"):
            unit = MasOrgUnit(org_unit_id=uuid.uuid4(), project_id=cls.PROJECT_ID,
                              org_level_id=level.org_level_id, unit_code=code,
                              unit_name=f"Unit {code}", path=code, is_active=True)
            db.session.add(unit)
            cls.units.append(unit)
        db.session.flush()

        def grant(user, **scope):
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.interviewer, notes="worklist test",
                grant_status=VaStatuses.active, **scope,
            ))

        cls.alice = cls._get_or_make_user("wl.alice@test.local", "Worklist123")
        cls.bob = cls._get_or_make_user("wl.bob@test.local", "Worklist123")
        cls.carol = cls._get_or_make_user("wl.carol@test.local", "Worklist123")
        cls.dave = cls._get_or_make_user("wl.dave@test.local", "Worklist123")
        for user in (cls.alice, cls.bob):
            grant(user, scope_type=VaAccessScopeTypes.project, project_id=cls.PROJECT_ID)
        # Carol is held to unit 1's subtree; Dave works another project.
        grant(cls.carol, scope_type=VaAccessScopeTypes.org_unit, org_unit_id=cls.units[0].org_unit_id)
        grant(cls.dave, scope_type=VaAccessScopeTypes.project, project_id=cls.OTHER_PROJECT_ID)
        db.session.commit()

    # ── helpers ────────────────────────────────────────────────────────────

    def _register(self, user=None, unit=0, **overrides):
        fields = {"deceased_name": "Asha Devi", "deceased_sex": "female", "date_of_death": _dod()}
        fields.update(overrides)
        return intake_svc.register_death(
            user or self.alice, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            org_unit_id=str(self.units[unit].org_unit_id), **fields,
        )

    def _direct(self, user=None, unit=0):
        return intake_svc.start_draft(
            user or self.alice, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            org_unit_id=str(self.units[unit].org_unit_id),
        )

    def _audit(self, case):
        return db.session.scalars(
            sa.select(MapCaseTransition)
            .where(MapCaseTransition.death_id == case.death_id)
            .order_by(MapCaseTransition.created_at)
        ).all()

    def _completion(self, **data):
        base = {
            "Id10013": "yes", "Id10017": "Ravi", "Id10018": "Kumar", "Id10019": "male",
            "Id10023": _dod(), "finalAgeInYears": "40", "narr_language": "english",
        }
        base.update(data)
        return {"valid": True, "issues": [], "data": base}

    def _worklist_ids(self, user, **kwargs):
        return [row[0].death_id for row in intake_svc.list_worklist(user, **kwargs)["cases"]]

    # ── transition table and audit ─────────────────────────────────────────

    def test_allowed_transitions_each_write_one_audit_row(self):
        case = self._register()
        self.assertEqual(case.status, "registered")
        path = ["scheduled", "registered", "in_progress", "paused", "in_progress",
                "not_reachable", "in_progress", "refused", "in_progress", "submitted"]
        for to_state in path:
            cases.transition(case, to_state, actor=self.bob, action="test", reason="step")

        rows = self._audit(case)
        self.assertEqual(len(rows), 1 + len(path))
        self.assertEqual((rows[0].action, rows[0].from_state, rows[0].to_state),
                         ("created", None, "registered"))
        self.assertEqual(rows[0].actor_user_id, self.alice.user_id)
        self.assertEqual([r.to_state for r in rows[1:]], path)
        self.assertEqual((rows[-1].from_state, rows[-1].actor_user_id, rows[-1].reason),
                         ("in_progress", self.bob.user_id, "step"))
        self.assertEqual(case.status, "submitted")

    def test_a_move_outside_the_table_is_refused_and_leaves_no_trace(self):
        case = self._register()
        before = len(self._audit(case))
        for to_state in ("submitted", "paused", "draft_identity"):
            with self.assertRaises(cases.WebIntakeError) as ctx:
                cases.transition(case, to_state, actor=self.alice, action="test")
            self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(case.status, "registered")
        self.assertEqual(len(self._audit(case)), before)

    def test_supervisor_moves_are_refused_while_the_predicate_fails_closed(self):
        case = self._register()
        self.assertFalse(cases.is_interview_supervisor_for(self.alice, case))
        with self.assertRaises(cases.WebIntakeError) as ctx:
            cases.transition(case, "duplicate", actor=self.alice, action="confirm_duplicate")
        self.assertEqual(ctx.exception.status_code, 403)

        cases.transition(case, "in_progress", actor=self.alice, action="test")
        with self.assertRaises(cases.WebIntakeError) as ctx:
            cases.transition(case, "cancelled", actor=self.alice, action="confirm_cancel")
        self.assertEqual(ctx.exception.status_code, 403)

        cases.flag_case(case, actor=self.alice, kind="cancel", reason="registered in error")
        for call in (
            lambda: cases.resolve_flag(case, actor=self.alice, confirm=True),
            lambda: cases.resolve_flag(case, actor=self.alice, confirm=False),
        ):
            with self.assertRaises(cases.WebIntakeError) as ctx:
                call()
            self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(case.pending_flag, "cancel")

        cases.transition(case, "submitted", actor=self.alice, action="test")
        with self.assertRaises(cases.WebIntakeError) as ctx:
            cases.reopen(case, actor=self.alice, reason="coded twice")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(case.status, "submitted")

    def test_only_the_registrant_cancels_a_registration(self):
        case = self._register(user=self.alice)
        with self.assertRaises(cases.WebIntakeError) as ctx:
            cases.transition(case, "cancelled", actor=self.bob, action="cancel_registration")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(case.status, "registered")

        cases.transition(case, "cancelled", actor=self.alice, action="cancel_registration",
                         reason="registered twice")
        self.assertEqual(case.status, "cancelled")
        self.assertEqual(self._audit(case)[-1].reason, "registered twice")

    def test_an_interviewer_flags_a_possible_duplicate_and_it_waits(self):
        kept = self._register()
        other = self._register(deceased_name="Asha D")
        intake_svc.flag_death(self.bob, other.death_id, kind="duplicate",
                              duplicate_of=kept.death_id, reason="same family")

        self.assertEqual(other.pending_flag, "duplicate")
        self.assertEqual(other.duplicate_of_death_id, kept.death_id)
        self.assertEqual(other.status, "registered")
        last = self._audit(other)[-1]
        self.assertEqual((last.action, last.from_state, last.to_state, last.actor_user_id),
                         ("flag_duplicate", "registered", "registered", self.bob.user_id))

        with self.assertRaises(cases.WebIntakeError):
            intake_svc.flag_death(self.bob, kept.death_id, kind="duplicate", duplicate_of=kept.death_id)
        with self.assertRaises(cases.WebIntakeError):
            intake_svc.flag_death(self.bob, kept.death_id, kind="cancel")

    def test_a_cancel_flag_clears_a_stale_duplicate_link(self):
        kept = self._register()
        other = self._register(deceased_name="Asha D")
        intake_svc.flag_death(self.bob, other.death_id, kind="duplicate", duplicate_of=kept.death_id)
        self.assertEqual(other.duplicate_of_death_id, kept.death_id)

        intake_svc.flag_death(self.bob, other.death_id, kind="cancel", reason="entered twice")
        self.assertEqual(other.pending_flag, "cancel")
        self.assertIsNone(other.duplicate_of_death_id)

    def test_a_duplicate_flag_needs_a_live_original_and_no_cycle(self):
        closed = self._register()
        cases.transition(closed, "cancelled", actor=self.alice, action="test", reason="error")
        first = self._register()
        second = self._register()

        with self.assertRaises(cases.WebIntakeError) as ctx:
            intake_svc.flag_death(self.bob, first.death_id, kind="duplicate", duplicate_of=closed.death_id)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIsNone(first.pending_flag)

        intake_svc.flag_death(self.bob, first.death_id, kind="duplicate", duplicate_of=second.death_id)
        self.assertEqual(first.duplicate_of_death_id, second.death_id)
        with self.assertRaises(cases.WebIntakeError) as ctx:
            intake_svc.flag_death(self.bob, second.death_id, kind="duplicate", duplicate_of=first.death_id)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIsNone(second.pending_flag)

    def test_flagging_a_case_outside_scope_reads_as_not_found(self):
        in_unit1 = self._register(unit=0)
        in_unit2 = self._register(unit=1)
        intake_svc.flag_death(self.carol, in_unit1.death_id, kind="cancel", reason="entered twice")
        self.assertEqual(in_unit1.pending_flag, "cancel")

        for user, case in ((self.carol, in_unit2), (self.dave, in_unit1)):
            with self.assertRaises(cases.WebIntakeError) as ctx:
                intake_svc.flag_death(user, case.death_id, kind="cancel", reason="entered twice")
            self.assertEqual(ctx.exception.status_code, 404)
        self.assertIsNone(in_unit2.pending_flag)

    def test_state_changes_and_starts_take_the_case_row_lock(self):
        case = self._register()
        statements = []

        def record(conn, cursor, statement, *args):
            statements.append(statement)

        def locked():
            return [s for s in statements if "FROM va_death_register" in s and "FOR UPDATE" in s]

        sa.event.listen(db.engine, "before_cursor_execute", record)
        try:
            cases.transition(case, "scheduled", actor=self.alice, action="test")
            self.assertEqual(len(locked()), 1)
            intake_svc.start_draft(self.bob, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                                   death_id=case.death_id)
            # One lock before the active-draft check, one in the transition.
            self.assertEqual(len(locked()), 3)
            intake_svc.flag_death(self.bob, case.death_id, kind="cancel", reason="entered twice")
            self.assertEqual(len(locked()), 4)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", record)
        self.assertEqual(case.status, "in_progress")

    # ── parallel interviews (digitva-xz83) ─────────────────────────────────

    def _start(self, user, case):
        return intake_svc.start_draft(user, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                                      death_id=case.death_id)

    def _row(self, user, case):
        return intake_svc.serialize_worklist_row(user, *intake_svc.get_case_detail(user, case.death_id))

    def test_two_interviewers_each_hold_a_draft_and_see_the_warning_only(self):
        case = self._register()
        mine = self._start(self.alice, case)
        theirs = self._start(self.bob, case)
        self.assertNotEqual(mine.draft_id, theirs.draft_id)
        self.assertEqual(case.status, "in_progress")
        for me, other, my_draft in ((self.alice, self.bob, mine), (self.bob, self.alice, theirs)):
            row = self._row(me, case)
            self.assertEqual(row["my_draft_id"], str(my_draft.draft_id))
            self.assertIs(row["other_draft_active"], True)
            self.assertIsNotNone(row["other_draft_started_at"])
            self.assertNotIn(str(other.user_id), json.dumps(row))
            self.assertNotIn(other.name, json.dumps(row))
            # Both are prefilled: the other's draft does not withhold it.
            detail = intake_svc.get_case_detail(me, case.death_id)
            self.assertIsNotNone(intake_svc.case_prefill(me, detail[0], None))
            self.assertIsNotNone(intake_svc.case_prefill(me, detail[0], detail[2]))
        # The same signal through the list query, and the lone draft's own case.
        listed = {r["death_id"]: r for r in intake_svc.worklist_page(self.alice, {})["cases"]}
        self.assertIs(listed[str(case.death_id)]["other_draft_active"], True)
        alone = self._register()
        self._start(self.alice, alone)
        self.assertIs(self._row(self.alice, alone)["other_draft_active"], False)
        self.assertIsNone(self._row(self.alice, alone)["other_draft_started_at"])
        self.assertIs(self._row(self.bob, alone)["other_draft_active"], True)

    def test_the_same_interviewer_starting_twice_gets_the_same_draft(self):
        case = self._register()
        first = self._start(self.alice, case)
        self.assertEqual(self._start(self.alice, case).draft_id, first.draft_id)
        self.assertEqual(
            db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraft)
                              .where(VaWebIntakeDraft.death_id == case.death_id)), 1)

    def test_a_second_open_draft_for_one_interviewer_and_case_is_refused_by_the_database(self):
        case = self._register()
        first = self._start(self.alice, case)
        clone = VaWebIntakeDraft(
            project_id=first.project_id, site_id=first.site_id, death_id=first.death_id,
            form_id=first.form_id, user_id=first.user_id, unique_id=first.unique_id,
        )
        with self.assertRaises(sa.exc.IntegrityError), db.session.begin_nested():
            db.session.add(clone)
            db.session.flush()

    def test_a_browser_submit_after_a_teammate_won_is_kept_as_a_superseded_copy(self):
        case = self._register(deceased_name="Asha Devi")
        mine = self._start(self.alice, case)
        theirs = self._start(self.bob, case)
        won = intake_svc.submit_draft(theirs, self.bob, completion=self._completion())
        self.assertEqual(case.status, "submitted")
        before = (case.deceased_name, case.deceased_sex, case.va_sid, case.updated_at)
        late = self._completion(Id10017="Other", Id10018="Name")
        self.assertIsNone(intake_svc.submit_draft(mine, self.alice, completion=late))
        self.assertEqual(mine.status, "superseded")
        self.assertIsNotNone(mine.submitted_at)
        self.assertIsNone(mine.va_sid)
        self.assertEqual(
            {row.section_name: row.data for row in mine.sections}[intake_svc.FINAL_SECTION]["Id10017"], "Other")
        self.assertEqual(before, (case.deceased_name, case.deceased_sex, case.va_sid, case.updated_at))
        self.assertEqual(case.va_sid, won.va_sid)
        # Only the interviewer whose draft became the submission sees its id,
        # not the one who first started the case.
        self.assertEqual(self._row(self.bob, case)["va_sid"], won.va_sid)
        self.assertIsNone(self._row(self.alice, case)["va_sid"])
        self.assertIs(self._row(self.alice, case)["started_by_me"], True)

    def test_a_retried_submit_of_the_winning_draft_does_not_turn_it_into_a_copy(self):
        case = self._register()
        mine = self._start(self.alice, case)
        won = intake_svc.submit_draft(mine, self.alice, completion=self._completion())
        db.session.flush()
        # A second request loaded the draft before the first committed.
        sa.orm.attributes.set_committed_value(mine, "status", "draft")
        with self.assertRaises(cases.WebIntakeError) as refused:
            intake_svc.submit_draft(mine, self.alice, completion=self._completion())
        self.assertEqual(refused.exception.status_code, 409)
        db.session.refresh(mine)
        self.assertEqual((mine.status, mine.va_sid), ("submitted", won.va_sid))

    def test_a_refused_or_partial_submit_on_a_shared_case_leaves_its_identity(self):
        case = self._register(deceased_name="Asha Devi")
        self._start(self.alice, case)
        theirs = self._start(self.bob, case)
        partial = {**self._completion(Id10017="Other", Id10018="Name", interview_outcome="partially_completed"),
                   "valid": False}
        intake_svc.submit_draft(theirs, self.bob, completion=partial)
        self.assertEqual(case.status, "paused")
        self.assertEqual(case.deceased_name, "Asha Devi")

    def test_a_closed_case_shows_no_other_draft_warning(self):
        case = self._register()
        self._start(self.alice, case)
        theirs = self._start(self.bob, case)
        self.assertIs(self._row(self.bob, case)["other_draft_active"], True)
        intake_svc.submit_draft(theirs, self.bob, completion=self._completion())
        self.assertEqual(case.status, "submitted")
        # Alice's draft is still open on the closed case; Bob is not warned.
        self.assertIs(self._row(self.bob, case)["other_draft_active"], False)

    def test_discarding_keeps_the_case_in_progress_while_another_draft_is_open(self):
        case = self._register()
        mine = self._start(self.alice, case)
        theirs = self._start(self.bob, case)
        intake_svc.discard_draft(mine, self.alice)
        self.assertEqual(case.status, "in_progress")
        intake_svc.discard_draft(theirs, self.bob)
        self.assertEqual(case.status, "registered")

    def test_a_reason_longer_than_the_audit_column_is_refused(self):
        case = self._register()
        with self.assertRaises(cases.WebIntakeError):
            cases.transition(case, "scheduled", actor=self.alice, action="test", reason="x" * 201)
        self.assertEqual(case.status, "registered")

    # ── direct start, identity, submission ─────────────────────────────────

    def test_direct_start_creates_the_case_and_saves_fill_its_identity(self):
        draft = self._direct()
        case = db.session.get(VaDeathRegister, draft.death_id)
        self.assertEqual((case.source, case.status), ("direct", "draft_identity"))
        self.assertEqual(case.started_by_user_id, self.alice.user_id)
        self.assertIsNone(case.deceased_name)
        with self.assertRaises(cases.WebIntakeError) as ctx:
            cases.transition(case, "in_progress", actor=self.alice, action="test")
        self.assertEqual(ctx.exception.status_code, 409)

        intake_svc.save_draft_sections(draft, sections={"info": {"Id10017": "Ravi"}}, actor=self.alice)
        self.assertEqual((case.deceased_name, case.status), ("Ravi", "draft_identity"))

        # A later save sends only its own section; identity is read across all.
        intake_svc.save_draft_sections(
            draft,
            sections={"dates": {"Id10019": "male", "Id10022": "yes", "Id10020": "no",
                                "Id10023_b": _dod(3)}},
            actor=self.alice,
        )
        self.assertEqual(case.status, "in_progress")
        self.assertEqual((case.deceased_name, case.deceased_sex, case.date_of_death.isoformat()),
                         ("Ravi", "male", _dod(3)))
        last = self._audit(case)[-1]
        self.assertEqual((last.action, last.from_state, last.to_state),
                         ("identity_captured", "draft_identity", "in_progress"))

    def test_form_edits_reach_a_registered_case_only_at_submit(self):
        case = self._register(deceased_name="Asha Devi")
        draft = intake_svc.start_draft(self.alice, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                                       death_id=case.death_id)
        self.assertEqual(case.status, "in_progress")
        intake_svc.save_draft_sections(
            draft, sections={"info": {"Id10017": "Asha", "Id10018": "Kumari", "Id10019": "bogus"}},
            actor=self.alice,
        )
        # A save by one draft holder never rewrites a shared case's identity.
        self.assertEqual(case.deceased_name, "Asha Devi")
        intake_svc.submit_draft(draft, self.alice, completion=self._completion(
            Id10017="Asha", Id10018="Kumari", Id10019="bogus"))
        self.assertEqual(case.deceased_name, "Asha Kumari")
        # An invalid answer never blanks what the case holds.
        self.assertEqual(case.deceased_sex, "female")

    def test_submitting_a_direct_start_moves_its_case_to_submitted(self):
        draft = self._direct()
        submission = intake_svc.submit_draft(draft, self.alice, completion=self._completion())
        case = db.session.get(VaDeathRegister, draft.death_id)
        self.assertEqual(case.status, "submitted")
        self.assertEqual(case.va_sid, submission.va_sid)
        self.assertEqual(case.deceased_name, "Ravi Kumar")
        actions = [r.action for r in self._audit(case)]
        self.assertEqual(actions, ["created", "identity_captured", "submitted"])

    def test_a_direct_start_without_identity_cannot_submit(self):
        draft = self._direct()
        with self.assertRaises(cases.WebIntakeError) as ctx:
            intake_svc.submit_draft(draft, self.alice,
                                    completion=self._completion(Id10017="", Id10018="", Id10023=""))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(draft.status, "draft")

    def test_discarding_a_direct_start_cancels_or_keeps_its_case(self):
        empty = self._direct()
        intake_svc.discard_draft(empty, self.alice)
        self.assertEqual(db.session.get(VaDeathRegister, empty.death_id).status, "cancelled")

        filled = self._direct()
        intake_svc.save_draft_sections(
            filled, sections={"info": {"Id10017": "Ravi", "Id10019": "male", "Id10023": _dod()}},
            actor=self.alice,
        )
        intake_svc.discard_draft(filled, self.alice)
        # Its identity is known, so it stays a team case waiting for a visit.
        self.assertEqual(db.session.get(VaDeathRegister, filled.death_id).status, "registered")

    def test_a_refused_case_restarts_for_any_team_member(self):
        case = self._register()
        cases.transition(case, "refused", actor=self.alice, action="test")
        intake_svc.start_draft(self.bob, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                               death_id=case.death_id)
        self.assertEqual(case.status, "in_progress")
        last = self._audit(case)[-1]
        self.assertEqual((last.action, last.from_state, last.actor_user_id),
                         ("interview_restarted", "refused", self.bob.user_id))

    # ── worklist ───────────────────────────────────────────────────────────

    def test_worklist_shows_team_cases_in_scope_only(self):
        in_unit1 = self._register(unit=0)
        in_unit2 = self._register(unit=1)

        team = self._worklist_ids(self.bob)
        self.assertIn(in_unit1.death_id, team)
        self.assertIn(in_unit2.death_id, team)

        unit_scoped = self._worklist_ids(self.carol)
        self.assertIn(in_unit1.death_id, unit_scoped)
        self.assertNotIn(in_unit2.death_id, unit_scoped)

        self.assertEqual(self._worklist_ids(self.dave), [])

    def test_details_pending_is_visible_to_its_starter_only(self):
        draft = self._direct(user=self.alice)
        self.assertIn(draft.death_id, self._worklist_ids(self.alice))
        self.assertNotIn(draft.death_id, self._worklist_ids(self.bob))
        with self.assertRaises(cases.WebIntakeError) as ctx:
            intake_svc.get_death(self.bob, draft.death_id)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_worklist_mine_and_state_filters_and_counts(self):
        by_alice = self._register(user=self.alice)
        by_bob = self._register(user=self.bob)
        worked_by_alice = self._register(user=self.bob)
        cases.transition(worked_by_alice, "scheduled", actor=self.alice, action="test")

        mine = self._worklist_ids(self.alice, mine=True)
        self.assertIn(by_alice.death_id, mine)
        self.assertIn(worked_by_alice.death_id, mine)
        self.assertNotIn(by_bob.death_id, mine)

        scheduled = self._worklist_ids(self.alice, states=["scheduled"])
        self.assertIn(worked_by_alice.death_id, scheduled)
        self.assertNotIn(by_alice.death_id, scheduled)

        counts = intake_svc.list_worklist(self.alice)["counts"]
        self.assertGreaterEqual(counts["registered"], 2)
        self.assertGreaterEqual(counts["scheduled"], 1)

        with self.assertRaises(cases.WebIntakeError):
            intake_svc.list_worklist(self.alice, states=["va_submitted"])

    def test_worklist_pages_by_keyset_without_overlap(self):
        created = {self._register().death_id for _ in range(3)}
        seen, cursor = [], None
        while True:
            page = intake_svc.list_worklist(self.alice, cursor=cursor, limit=1)
            seen.extend(row[0].death_id for row in page["cases"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        self.assertTrue(created <= set(seen))
        self.assertEqual(len(seen), len(set(seen)))
        with self.assertRaises(cases.WebIntakeError):
            intake_svc.list_worklist(self.alice, cursor="not-a-cursor")
