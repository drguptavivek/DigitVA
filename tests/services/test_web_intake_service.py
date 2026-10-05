"""Tests for app.services.web_intake_service.

Covers the rules the web intake path owns (docs/policy/web-intake.md):
  - project ``web_intake_mode`` gates the death register and direct entry
  - interviewer scope is enforced on every entry point
  - a registered death gets a unique id from the death-number sequence
  - drafts save section-wise and reassemble into the package's envelope
  - submitting a draft creates a ``va_submissions`` row with an active payload
    version and lands in ``smartva_pending`` when consent is valid
  - ``interview_outcome`` sets the case state; only ``completed`` enters coding
  - the web ``va_forms`` row is never enumerated by ODK runtime form sync
"""
import uuid
from datetime import UTC, date, datetime, timedelta, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    MapCaseTransition,
    MapProjectSiteOdk,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaUserAccessGrants,
    VaWebIntakeDraft,
    VaWebIntakeDraftSection,
)
from app.models.va_submission_payload_versions import PAYLOAD_VERSION_STATUS_ACTIVE
from app.services import web_intake_service as intake_svc
from app.services.runtime_form_sync_service import (
    _ensure_legacy_project_site_rows,
    ensure_web_runtime_form,
    sync_runtime_forms_from_site_mappings,
)
from app.services.workflow.definition import WORKFLOW_CONSENT_REFUSED, WORKFLOW_SMARTVA_PENDING
from app.services.workflow.state_store import get_submission_workflow_state
from tests.base import BaseTestCase


class WebIntakeServiceTests(BaseTestCase):
    """Project WIT01/WI01 runs web intake in ``both`` mode."""

    PROJECT_ID = "WIT01"
    SITE_ID = "WI01"
    ODK_FORM_ID = "WIT01WI0101"

    # Another project-site the interviewer has no grant on.
    OTHER_PROJECT_ID = "WIT02"
    OTHER_SITE_ID = "WI02"
    OTHER_FORM_ID = "WIT02WI0201"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)

        for project_id, name in ((cls.PROJECT_ID, "Web Intake Test"), (cls.OTHER_PROJECT_ID, "Web Intake Other")):
            db.session.add(VaProjectMaster(
                project_id=project_id,
                project_code=project_id,
                project_name=name,
                project_nickname=name,
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
                web_intake_mode="both",
            ))
        for site_id, name in ((cls.SITE_ID, "Web Intake Site"), (cls.OTHER_SITE_ID, "Web Intake Other Site")):
            db.session.add(VaSiteMaster(
                site_id=site_id,
                site_name=name,
                site_abbr=site_id,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
        db.session.flush()

        for project_id, site_id in ((cls.PROJECT_ID, cls.SITE_ID), (cls.OTHER_PROJECT_ID, cls.OTHER_SITE_ID)):
            db.session.add(VaProjectSites(
                project_id=project_id,
                site_id=site_id,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            ))
        db.session.flush()

        for project_id, site_id in ((cls.PROJECT_ID, cls.SITE_ID), (cls.OTHER_PROJECT_ID, cls.OTHER_SITE_ID)):
            _ensure_legacy_project_site_rows(project_id, site_id)
        db.session.flush()

        # An ODK form exists alongside the web form, as it does for a project
        # that collects both ways. Interviewer grants resolve through va_forms.
        for form_id, project_id, site_id in (
            (cls.ODK_FORM_ID, cls.PROJECT_ID, cls.SITE_ID),
            (cls.OTHER_FORM_ID, cls.OTHER_PROJECT_ID, cls.OTHER_SITE_ID),
        ):
            db.session.add(VaForms(
                form_id=form_id,
                project_id=project_id,
                site_id=site_id,
                odk_form_id=f"ODK_{form_id}",
                odk_project_id="7",
                form_type="WHO VA 2022",
                form_source="odk",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            ))
        db.session.flush()

        cls.interviewer = cls._get_or_make_user("web.interviewer@test.local", "WebIntake123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.interviewer.user_id,
            role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project,
            project_id=cls.PROJECT_ID,
            notes="web intake test grant",
            grant_status=VaStatuses.active,
        ))
        db.session.commit()

    # ── helpers ────────────────────────────────────────────────────────────

    def _set_mode(self, mode, project_id=None):
        project = db.session.get(VaProjectMaster, project_id or self.PROJECT_ID)
        project.web_intake_mode = mode
        db.session.flush()

    def _register_death(self, **overrides):
        fields = {
            "deceased_name": "Asha Devi",
            "deceased_sex": "female",
            "date_of_death": (date.today() - timedelta(days=10)).isoformat(),
            "age_years": 62,
        }
        fields.update(overrides)
        return intake_svc.register_death(
            self.interviewer,
            project_id=self.PROJECT_ID,
            site_id=self.SITE_ID,
            **fields,
        )

    def _completion(self, **extra):
        data = {
            "Id10013": "yes",
            # The minimum identity a direct start needs before it may submit.
            "Id10017": "Asha",
            "Id10018": "Devi",
            "Id10019": "female",
            "Id10023": (date.today() - timedelta(days=10)).isoformat(),
            "finalAgeInYears": "62",
            "narr_language": "english",
        }
        data.update(extra.pop("data", {}))
        completion = {"valid": True, "issues": [], "data": data}
        completion.update(extra)
        return completion

    # ── mode and scope ─────────────────────────────────────────────────────

    def test_get_web_intake_mode_off_for_unknown_or_inactive_project(self):
        self.assertEqual(intake_svc.get_web_intake_mode("NOPE01"), "off")
        self.assertEqual(intake_svc.get_web_intake_mode(self.PROJECT_ID), "both")

    def test_interviewer_context_lists_only_granted_enabled_project_sites(self):
        context = intake_svc.interviewer_context(self.interviewer)
        self.assertEqual(
            [(e["project_id"], e["site_id"]) for e in context],
            [(self.PROJECT_ID, self.SITE_ID)],
        )
        self.assertEqual(context[0]["web_intake_mode"], "both")
        self.assertEqual(context[0]["org_units"], [])

    def test_a_wide_grant_keeps_the_whole_tree_when_a_unit_grant_overlaps(self):
        """A unit grant on a pair a wide grant reaches narrows nothing:
        ``org_units: []`` stays the whole tree, as ``reachable_unit_ids``."""
        from app.services.authz import invalidate

        unit = self._org_unit()
        unit_only = self._get_or_make_user("web.unit.only.overlap@test.local", "WebIntake123")
        for user in (unit_only, self.interviewer):
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.interviewer,
                scope_type=VaAccessScopeTypes.org_unit, org_unit_id=unit.org_unit_id,
                notes="overlap test grant", grant_status=VaStatuses.active,
            ))
        db.session.flush()
        for user in (unit_only, self.interviewer):
            invalidate(user.user_id)
        # Present: a unit grant alone lists its unit.
        alone = intake_svc.interviewer_context(unit_only)
        self.assertEqual([u["org_unit_id"] for u in alone[0]["org_units"]], [str(unit.org_unit_id)])
        # Absent: with the wide grant on the same pair, the whole tree.
        overlap = intake_svc.interviewer_context(self.interviewer)
        self.assertEqual(
            [(e["project_id"], e["site_id"], e["org_units"]) for e in overlap],
            [(self.PROJECT_ID, self.SITE_ID, [])],
        )
        self.assertIsNone(intake_svc.reachable_unit_ids(self.interviewer, self.PROJECT_ID, self.SITE_ID))

    def test_interviewer_context_drops_project_when_intake_is_off(self):
        self._set_mode("off")
        self.assertEqual(intake_svc.interviewer_context(self.interviewer), [])

    def test_register_death_rejects_ungranted_project_site(self):
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.register_death(
                self.interviewer,
                project_id=self.OTHER_PROJECT_ID,
                site_id=self.OTHER_SITE_ID,
                deceased_name="X",
                deceased_sex="male",
                date_of_death=date.today().isoformat(),
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_register_death_rejected_when_mode_is_direct_only(self):
        self._set_mode("direct")
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            self._register_death()
        self.assertEqual(ctx.exception.status_code, 403)

    def test_start_draft_without_death_rejected_when_mode_is_death_register(self):
        self._set_mode("death_register")
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.start_draft(
                self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
            )
        self.assertEqual(ctx.exception.status_code, 403)

    # ── death register ─────────────────────────────────────────────────────

    def test_register_death_allocates_unique_id_from_sequence(self):
        first = self._register_death()
        second = self._register_death(deceased_name="Ram Kumar", deceased_sex="male")

        self.assertTrue(first.unique_id.startswith(f"{self.SITE_ID}-"))
        self.assertEqual(first.unique_id, f"{self.SITE_ID}-{first.death_number:06d}")
        self.assertNotEqual(first.unique_id, second.unique_id)
        self.assertGreater(second.death_number, first.death_number)
        self.assertEqual(first.status, "registered")
        self.assertEqual(first.registered_by, self.interviewer.user_id)

    def test_register_death_validates_dates_sex_and_age(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(date_of_death=tomorrow)
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(deceased_sex="other")
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(age_years=500)
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(
                date_of_birth=date.today().isoformat(),
                date_of_death=(date.today() - timedelta(days=10)).isoformat(),
            )
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(deceased_name="   ")

    def test_register_death_validates_abha_identifiers(self):
        death = self._register_death(abha_number="12-3456-7890-1234", abha_address="asha.devi@abdm")
        self.assertEqual(death.abha_number, "12-3456-7890-1234")
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(abha_number="1234")
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(abha_address="asha@example.com")

    def test_list_deaths_is_scoped_and_filtered_by_status(self):
        death = self._register_death()
        rows = intake_svc.list_deaths(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        self.assertIn(death.death_id, [r.death_id for r in rows])
        self.assertEqual(
            intake_svc.list_deaths(
                self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                status="va_submitted",
            ),
            [],
        )
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.list_deaths(
                self.interviewer, project_id=self.OTHER_PROJECT_ID, site_id=self.OTHER_SITE_ID
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_list_deaths_for_project_scoped_interviewer_in_tree_project(self):
        """digitva-nrq regression guard. Before the fix, list_deaths fell
        back to _require_scope(..., None) whenever the interviewer held no
        *unit*-scoped grant (bool(entry["org_units"]) is False for a project-
        or site-scoped grant, which never lists units) -- and in a project
        with an organization tree that raised 400 "Choose the organization
        unit", even though a project-scoped grant reaches every unit and
        listing names no new entry to attribute."""
        unit = self._org_unit()  # gives WIT01 an organization tree
        death = self._register_death(org_unit_id=str(unit.org_unit_id))

        rows = intake_svc.list_deaths(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )

        self.assertIn(death.death_id, [r.death_id for r in rows])

    def test_list_deaths_for_unit_scoped_interviewer_is_limited_to_their_subtree(self):
        """A unit-scoped grant only ever sees its own subtree's deaths -- a
        death with no unit at all would also be outside that subtree, so it
        stays excluded (docs/policy/web-intake.md, "Role" bullet)."""
        granted_unit = self._org_unit()
        other_unit = self._org_unit()
        unit_interviewer = self._get_or_make_user(
            "web.unit.interviewer.list@test.local", "WebIntake123"
        )
        db.session.add(VaUserAccessGrants(
            user_id=unit_interviewer.user_id,
            role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=granted_unit.org_unit_id,
            notes="unit-scoped web intake test grant",
            grant_status=VaStatuses.active,
        ))
        db.session.flush()
        death_in = self._register_death(org_unit_id=str(granted_unit.org_unit_id))
        death_out = self._register_death(org_unit_id=str(other_unit.org_unit_id))

        ids = [r.death_id for r in intake_svc.list_deaths(
            unit_interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )]

        self.assertIn(death_in.death_id, ids)
        self.assertNotIn(death_out.death_id, ids)

    def test_get_death_404_for_unknown_id(self):
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.get_death(self.interviewer, uuid.uuid4())
        self.assertEqual(ctx.exception.status_code, 404)

    # ── drafts ─────────────────────────────────────────────────────────────

    def test_start_draft_direct_creates_web_form_and_own_unique_id(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        form = db.session.get(VaForms, draft.form_id)
        self.assertEqual(form.form_source, "web")
        self.assertEqual((form.project_id, form.site_id), (self.PROJECT_ID, self.SITE_ID))
        self.assertNotEqual(form.form_id, self.ODK_FORM_ID)
        # A direct start creates its case at once, identity still pending.
        case = db.session.get(VaDeathRegister, draft.death_id)
        self.assertEqual((case.source, case.status), ("direct", "draft_identity"))
        self.assertEqual(case.unique_id, draft.unique_id)
        self.assertEqual(draft.status, "draft")
        self.assertTrue(draft.unique_id.startswith(f"{self.SITE_ID}-"))

        # A second draft reuses the same web form row.
        again = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        self.assertEqual(again.form_id, draft.form_id)
        self.assertNotEqual(again.unique_id, draft.unique_id)

    def test_start_draft_from_death_prefills_and_marks_in_progress(self):
        death = self._register_death(
            date_of_birth=(date.today() - timedelta(days=365 * 62)).isoformat(),
            abha_number="12345678901234",
        )
        draft = intake_svc.start_draft(
            self.interviewer,
            project_id=self.PROJECT_ID,
            site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        self.assertEqual(draft.unique_id, death.unique_id)
        self.assertEqual(draft.death_id, death.death_id)
        self.assertEqual(death.status, "in_progress")
        self.assertEqual(draft.prefill["deceased"]["givenNames"], "Asha")
        self.assertEqual(draft.prefill["deceased"]["surname"], "Devi")
        self.assertEqual(draft.prefill["deceased"]["sex"], "female")
        self.assertEqual(draft.prefill["answers"]["abha_number"], "12345678901234")
        # Besides the interviewer's own questions (digitva-vzk.3) and the
        # registered age (digitva-q219), only ABHA.
        self.assertEqual(
            set(draft.prefill["lockedQuestionNames"]) - {"Id10010", "Id10010b", "Id10010c", "age_group", "age_adult"},
            {"abha_number"},
        )

    def test_prefill_never_sends_both_date_and_year_of_death(self):
        """digitva-dyk: vendor/who-va-2022/src/prefill.ts throws when both
        deceased.dateOfDeath and deceased.yearOfDeath are present (they are
        the same evidence, exact vs. year-only). date_of_death is required
        on every death-register row today, so only dateOfDeath is ever sent;
        yearOfDeath is reserved for a death whose exact date is unknown."""
        death = self._register_death()
        prefill = intake_svc._prefill_from_death(death, self.interviewer)
        deceased = prefill["deceased"]
        self.assertEqual(deceased["dateOfDeath"], death.date_of_death.isoformat())
        self.assertNotIn("yearOfDeath", deceased)

    def test_prefill_never_sends_both_birth_date_and_age_in_years(self):
        """Same contract, the other pair prefill.ts rejects together."""
        with_dob = self._register_death(date_of_birth=(date.today() - timedelta(days=365 * 62)).isoformat())
        deceased = intake_svc._prefill_from_death(with_dob, self.interviewer)["deceased"]
        self.assertIn("dateOfBirth", deceased)
        self.assertNotIn("ageInYears", deceased)

        with_age = self._register_death(age_years=62)
        deceased = intake_svc._prefill_from_death(with_age, self.interviewer)["deceased"]
        self.assertIn("ageInYears", deceased)
        self.assertNotIn("dateOfBirth", deceased)

    def test_start_draft_prefills_and_locks_area_va_presets_from_org_unit(self):
        from app.services import org_grant_service as og
        from app.services import organization_service as org

        unit = self._org_unit()
        org.set_unit_va_presets(self.PROJECT_ID, unit.org_unit_id, hiv_mortality="high", malaria_mortality="low")
        db.session.commit()
        death = self._register_death(org_unit_id=str(unit.org_unit_id))

        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=death.death_id,
        )

        self.assertEqual(draft.prefill["answers"]["Id10002"], "high")
        self.assertEqual(draft.prefill["answers"]["Id10003"], "low")
        self.assertIn("Id10002", draft.prefill["lockedQuestionNames"])
        self.assertIn("Id10003", draft.prefill["lockedQuestionNames"])

    def test_start_draft_direct_also_prefills_area_va_presets(self):
        from app.services import organization_service as org

        unit = self._org_unit()
        org.set_unit_va_presets(self.PROJECT_ID, unit.org_unit_id, hiv_mortality="veryl", malaria_mortality=None)
        db.session.commit()

        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, org_unit_id=str(unit.org_unit_id),
        )

        self.assertEqual(draft.prefill["answers"]["Id10002"], "veryl")
        self.assertNotIn("Id10003", draft.prefill["answers"])

    def test_start_draft_without_a_preset_leaves_the_question_asked(self):
        unit = self._org_unit()
        death = self._register_death(org_unit_id=str(unit.org_unit_id))

        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=death.death_id,
        )

        self.assertNotIn("Id10002", draft.prefill["answers"])
        self.assertNotIn("Id10003", draft.prefill["answers"])

    def test_death_register_answer_wins_over_a_colliding_area_preset(self):
        """Design guarantee: a death-register answer is never overwritten by
        an area preset. No real question name collides today, so this drives
        _prefill_from_death directly with a mocked resolver to prove the
        merge order, rather than asserting on a scenario that cannot occur
        through the public API yet."""
        from unittest.mock import patch

        unit = self._org_unit()
        death = self._register_death(org_unit_id=str(unit.org_unit_id), abha_number="12345678901234")
        with patch(
            "app.services.web_intake_service.org_grant_service.resolve_va_presets",
            return_value={"abha_number": "should-not-win"},
        ):
            prefill = intake_svc._prefill_from_death(death, self.interviewer, death.org_unit_id)

        self.assertEqual(prefill["answers"]["abha_number"], "12345678901234")

    def test_resolve_draft_display_names_for_a_no_tree_project(self):
        """digitva-wdj: the intake form header shows names, not codes."""
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
        )
        names = intake_svc.resolve_draft_display_names(draft)
        self.assertEqual(names["project_name"], "Web Intake Test")
        self.assertEqual(names["site_name"], "Web Intake Site")
        self.assertIsNone(names["org_unit_name"])
        self.assertIsNone(names["org_level_name"])

    def test_resolve_draft_display_names_includes_the_org_unit_and_its_level(self):
        unit = self._org_unit()  # a "district"-level unit, see _org_unit()
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            org_unit_id=str(unit.org_unit_id),
        )
        names = intake_svc.resolve_draft_display_names(draft)
        self.assertEqual(names["org_unit_name"], "Test District")
        self.assertEqual(names["org_level_name"], "District")

    def test_start_draft_from_death_returns_the_existing_draft(self):
        death = self._register_death()
        first = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        second = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        self.assertEqual(first.draft_id, second.draft_id)

    def test_start_draft_gives_a_second_interviewer_their_own_draft_for_the_same_death(self):
        other = self._get_or_make_user("web.interviewer2@test.local", "WebIntake123")
        db.session.add(VaUserAccessGrants(
            user_id=other.user_id,
            role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT_ID,
            notes="second interviewer",
            grant_status=VaStatuses.active,
        ))
        db.session.flush()
        death = self._register_death()
        first = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        second = intake_svc.start_draft(
            other, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        self.assertNotEqual(first.draft_id, second.draft_id)
        self.assertEqual(second.user_id, other.user_id)
        self.assertEqual(first.death_id, second.death_id)
        # Each keeps their own copy on a repeat start.
        again = intake_svc.start_draft(
            other, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        self.assertEqual(again.draft_id, second.draft_id)

    def test_get_draft_is_owner_only(self):
        other = self._get_or_make_user("web.interviewer3@test.local", "WebIntake123")
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.get_draft(other, draft.draft_id)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_save_draft_sections_merges_per_section_and_envelope_reassembles(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        written = intake_svc.save_draft_sections(
            draft,
            sections={"consent": {"Id10013": "yes"}, "background": {"Id10019": "female"}},
            meta={"schemaVersion": 1, "formVersion": "2022", "instrumentVersion": "1.2.3"},
            current_section="background",
        )
        self.assertEqual(written, 2)

        # Re-saving one section replaces only that section's answers.
        intake_svc.save_draft_sections(
            draft, sections={"background": {"Id10019": "male", "Id10020": "2024"}}
        )
        rows = {s.section_name: s.data for s in draft.sections}
        self.assertEqual(rows["consent"], {"Id10013": "yes"})
        self.assertEqual(rows["background"], {"Id10019": "male", "Id10020": "2024"})

        envelope = intake_svc.load_draft_envelope(draft)
        self.assertEqual(envelope["id"], str(draft.draft_id))
        self.assertEqual(envelope["currentSection"], "background")
        self.assertEqual(envelope["instrumentId"], intake_svc.INSTRUMENT_ID)
        self.assertEqual(envelope["instrumentVersion"], "1.2.3")
        self.assertEqual(
            envelope["data"], {"Id10013": "yes", "Id10019": "male", "Id10020": "2024"}
        )

    def test_save_draft_sections_rejects_bad_shapes(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        with self.assertRaises(intake_svc.WebIntakeError):
            intake_svc.save_draft_sections(draft, sections=["consent"])
        with self.assertRaises(intake_svc.WebIntakeError):
            intake_svc.save_draft_sections(draft, sections={"bad name!": {}})
        with self.assertRaises(intake_svc.WebIntakeError):
            intake_svc.save_draft_sections(draft, sections={"consent": "yes"})
        with self.assertRaises(intake_svc.WebIntakeError):
            intake_svc.save_draft_sections(
                draft, sections={}, current_section="not a section"
            )

    def test_discard_draft_releases_the_death_back_to_registered(self):
        death = self._register_death()
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        intake_svc.discard_draft(draft)
        self.assertEqual(draft.status, "discarded")
        self.assertEqual(death.status, "registered")
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.get_draft(self.interviewer, draft.draft_id, for_update=True)
        self.assertEqual(ctx.exception.status_code, 409)

    # ── submission ─────────────────────────────────────────────────────────

    def test_submit_draft_creates_submission_payload_version_and_workflow_state(self):
        death = self._register_death()
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        submission = intake_svc.submit_draft(
            draft, self.interviewer, completion=self._completion()
        )

        self.assertEqual(submission.va_form_id, draft.form_id)
        self.assertEqual(submission.va_uniqueid_real, draft.unique_id)
        self.assertEqual(submission.va_consent, "yes")
        self.assertEqual(submission.va_data_collector, self.interviewer.name)

        self.assertEqual(draft.status, "submitted")
        self.assertEqual(draft.va_sid, submission.va_sid)
        self.assertTrue(draft.client_valid)
        self.assertIsNotNone(draft.submitted_at)
        self.assertEqual(death.status, "submitted")
        self.assertEqual(death.va_sid, submission.va_sid)

        version = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == submission.va_sid,
                VaSubmissionPayloadVersion.version_status == PAYLOAD_VERSION_STATUS_ACTIVE,
            )
        )
        self.assertIsNotNone(version)
        self.assertEqual(version.payload_data["intake_source"], "web")
        self.assertEqual(version.payload_data["unique_id"], draft.unique_id)
        self.assertEqual(version.payload_data["death_register_id"], str(death.death_id))
        # Nothing in the client's answers disagrees with the server's own
        # relevant/constraint re-derivation (beads digitva-cal.2).
        self.assertEqual(version.validation_err, [])

        # No attachments -> the attachment step is skipped straight to SmartVA.
        self.assertEqual(
            get_submission_workflow_state(submission.va_sid), WORKFLOW_SMARTVA_PENDING
        )

    def test_submit_draft_stores_a_constraint_disagreement_instead_of_refusing(self):
        """beads digitva-cal.2, PART 1: the server re-derives ``constraint``
        itself and records the disagreement, but never refuses a submission
        the client itself marked valid."""
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        # Id10021 (date of birth) is relevant once Id10020='yes', and its
        # constraint (". <= today()") rejects a future date -- yet the
        # client still claims valid=True.
        submission = intake_svc.submit_draft(
            draft,
            self.interviewer,
            completion=self._completion(data={"Id10020": "yes", "Id10021": "2099-01-01"}),
        )

        version = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == submission.va_sid,
                VaSubmissionPayloadVersion.version_status == PAYLOAD_VERSION_STATUS_ACTIVE,
            )
        )
        self.assertIn({"question": "Id10021", "rule": "constraint"}, version.validation_err)
        # The submission is still stored, not refused.
        self.assertIsNotNone(db.session.get(VaSubmissions, submission.va_sid))
        # No answer value anywhere in the stored entries.
        self.assertNotIn("2099-01-01", str(version.validation_err))

    def test_a_non_doris_project_keeps_the_doris_support_answers(self):
        """digitva-hln: every web form asks the doris_support_whova_2022
        questions, so a project coding in simple mode submits them cleanly:
        kept by the server's relevance strip, no validation disagreement."""
        project = db.session.get(VaProjectMaster, self.PROJECT_ID)
        self.assertNotEqual(project.cod_entry_mode, "doris")
        answers = {
            "Id10020": "no",
            "dob_precision": "month_year",
            "dob_month_year": "1962-03-01",
            "Id10077": "yes",
            "doris_injury_date_known": "unknown",
            "doris_injury_place": "4",
            "doris_injury_legal_war": "neither",
            "doris_surgery_performed": "yes",
            "doris_surgery_when": 3,
            "doris_surgery_when_unit": "days",
            "doris_surgery_type": "Laparotomy",
            "doris_surgery_reason": "Abdominal injury",
            "doris_autopsy_requested": "yes",
            "doris_autopsy_findings": "no",
        }
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        submission = intake_svc.submit_draft(
            draft, self.interviewer, completion=self._completion(data=answers)
        )

        version = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == submission.va_sid,
                VaSubmissionPayloadVersion.version_status == PAYLOAD_VERSION_STATUS_ACTIVE,
            )
        )
        for name, value in answers.items():
            self.assertEqual(version.payload_data.get(name), value, name)
        self.assertEqual(version.validation_err, [])

    def test_submit_draft_strips_irrelevant_image_answers_but_keeps_them_in_the_draft(self):
        """beads digitva-aiy.1: a gate answered "no" after images were
        captured must not carry those images into the submission, and the
        cascade (md_available -> md_count -> md_im*) must resolve
        transitively, not one level."""
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        captured = {
            "md_available": "yes",
            "md_count": "4",
            "md_im1": "who-va-attachment:slot1",
            "md_im2": "who-va-attachment:slot2",
            "md_im3": "who-va-attachment:slot3",
            "md_im4": "who-va-attachment:slot4",
        }
        # The draft itself keeps the images the interviewer captured while
        # md_available was still "yes" -- submit_draft never touches
        # draft.sections.
        intake_svc.save_draft_sections(draft, sections={"documents": dict(captured)})

        # At final submit the interviewer has since flipped the gate to
        # "no" without deleting the images already photographed.
        submitted_data = dict(captured)
        submitted_data["md_available"] = "no"
        submission = intake_svc.submit_draft(
            draft, self.interviewer, completion=self._completion(data=submitted_data)
        )

        version = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == submission.va_sid,
                VaSubmissionPayloadVersion.version_status == PAYLOAD_VERSION_STATUS_ACTIVE,
            )
        )
        for name in ("md_count", "md_im1", "md_im2", "md_im3", "md_im4"):
            self.assertIsNone(
                version.payload_data.get(name), f"{name} should have been stripped"
            )
        self.assertEqual(draft.meta.get("attachmentReferences"), {})

        # The draft's own saved section still holds every captured answer.
        draft_section = next(s for s in draft.sections if s.section_name == "documents")
        self.assertEqual(draft_section.data, captured)

    def test_submit_draft_requires_valid_completion_and_consent(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.submit_draft(draft, self.interviewer, completion={})
        self.assertEqual(ctx.exception.status_code, 400)

        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.submit_draft(
                draft, self.interviewer, completion=self._completion(valid=False)
            )
        self.assertEqual(ctx.exception.status_code, 422)

        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.submit_draft(
                draft, self.interviewer, completion=self._completion(data={"Id10013": ""})
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_submit_draft_is_rejected_twice(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        intake_svc.submit_draft(draft, self.interviewer, completion=self._completion())
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.submit_draft(draft, self.interviewer, completion=self._completion())
        self.assertEqual(ctx.exception.status_code, 409)

    # -- interview_outcome (decision 8) --------------------------------------

    def _submit_for_new_draft(self, death, completion):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        submission = intake_svc.submit_draft(draft, self.interviewer, completion=completion)
        return draft, submission

    def _stored_outcome(self, submission):
        version = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == submission.va_sid,
                VaSubmissionPayloadVersion.version_status == PAYLOAD_VERSION_STATUS_ACTIVE,
            )
        )
        return version.payload_data.get("interview_outcome")

    def test_a_valid_form_is_completed_whatever_the_interviewer_picked(self):
        death = self._register_death()
        _draft, submission = self._submit_for_new_draft(
            death, self._completion(data={"interview_outcome": "partially_completed"})
        )
        self.assertEqual(self._stored_outcome(submission), "completed")
        self.assertEqual(death.status, "submitted")
        self.assertEqual(death.va_sid, submission.va_sid)
        self.assertEqual(get_submission_workflow_state(submission.va_sid), WORKFLOW_SMARTVA_PENDING)

    def test_consent_no_is_refused_kept_out_of_coding_and_leaves_the_case_open(self):
        death = self._register_death()
        # Consent no: the rest of the form is irrelevant, validity is not required.
        draft, submission = self._submit_for_new_draft(
            death, self._completion(valid=False, data={"Id10013": "no", "interview_outcome": "completed"})
        )
        self.assertEqual(self._stored_outcome(submission), "refused")
        self.assertEqual(submission.va_consent, "no")
        self.assertEqual(death.status, "refused")
        self.assertIsNone(death.va_sid)
        self.assertEqual(draft.va_sid, submission.va_sid)
        self.assertFalse(draft.client_valid)
        self.assertEqual(get_submission_workflow_state(submission.va_sid), WORKFLOW_CONSENT_REFUSED)

    def _no_identity(self, **data):
        completion = {"valid": data.pop("valid", False), "issues": [], "data": data}
        return completion

    def test_a_direct_start_refused_at_consent_submits_without_identity(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        case = db.session.get(VaDeathRegister, draft.death_id)
        self.assertEqual(case.status, "draft_identity")
        submission = intake_svc.submit_draft(
            draft, self.interviewer, completion=self._no_identity(Id10013="no", **self.VISIT_NOTE)
        )
        self.assertEqual(self._stored_outcome(submission), "refused")
        self.assertEqual(case.status, "cancelled")
        self.assertIsNone(case.deceased_name)
        self.assertEqual(get_submission_workflow_state(submission.va_sid), WORKFLOW_CONSENT_REFUSED)
        # The visit note is the only record of which household it was.
        version = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == submission.va_sid,
                VaSubmissionPayloadVersion.version_status == PAYLOAD_VERSION_STATUS_ACTIVE,
            )
        )
        self.assertEqual(
            {k: version.payload_data.get(k) for k in self.VISIT_NOTE},
            {"visit_address": "12 Mill Road, Ward 4", "visit_date": "2026-09-30", "visit_remarks": "Family away"},
        )
        self.assertEqual(draft.meta["visitNote"]["visit_address"], "12 Mill Road, Ward 4")

    VISIT_NOTE = {
        "visit_address": "  12 Mill Road, Ward 4 ",
        "visit_date": "2026-09-30",
        "visit_remarks": "Family away",
    }

    def test_an_identity_less_refusal_requires_a_valid_visit_note(self):
        future = (date.today() + timedelta(days=1)).isoformat()
        for label, note in (
            ("none", {}),
            ("no address", {"visit_address": " ", "visit_date": "2026-09-30"}),
            ("no date", {"visit_address": "12 Mill Road"}),
            ("future date", {"visit_address": "12 Mill Road", "visit_date": future}),
            ("bad date", {"visit_address": "12 Mill Road", "visit_date": "30/09/2026"}),
        ):
            with self.subTest(note=label):
                draft = intake_svc.start_draft(
                    self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
                )
                with self.assertRaises(intake_svc.WebIntakeError) as ctx:
                    intake_svc.submit_draft(
                        draft, self.interviewer, completion=self._no_identity(Id10013="no", **note)
                    )
                self.assertEqual(ctx.exception.status_code, 422)

    def test_a_name_without_sex_or_date_still_needs_the_visit_note(self):
        # The case stays draft_identity until name, sex and date of death are
        # all present, so the note is required exactly as for no identity.
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.submit_draft(
                draft, self.interviewer, completion=self._no_identity(Id10013="no", Id10017="Asha")
            )
        self.assertEqual(ctx.exception.status_code, 422)
        submission = intake_svc.submit_draft(
            draft,
            self.interviewer,
            completion=self._no_identity(Id10013="no", Id10017="Asha", **self.VISIT_NOTE),
        )
        case = db.session.get(VaDeathRegister, draft.death_id)
        self.assertEqual(self._stored_outcome(submission), "refused")
        self.assertEqual(case.status, "cancelled")

    def test_remarks_are_optional_and_a_register_case_needs_no_visit_note(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        submission = intake_svc.submit_draft(
            draft,
            self.interviewer,
            completion=self._no_identity(
                Id10013="no", visit_address="12 Mill Road", visit_date="2026-09-30"
            ),
        )
        self.assertEqual(self._stored_outcome(submission), "refused")
        death = self._register_death()
        _d, refused = self._submit_for_new_draft(death, self._completion(data={"Id10013": "no"}))
        self.assertEqual(self._stored_outcome(refused), "refused")
        self.assertEqual(death.status, "refused")

    def test_a_direct_start_without_identity_still_cannot_submit_anything_else(self):
        for data in ({"interview_outcome": "partially_completed"}, {"Id10013": "yes", "valid": True}):
            with self.subTest(data=data):
                draft = intake_svc.start_draft(
                    self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
                )
                with self.assertRaises(intake_svc.WebIntakeError) as ctx:
                    intake_svc.submit_draft(
                        draft, self.interviewer, completion=self._no_identity(**data)
                    )
                self.assertEqual(ctx.exception.status_code, 422)

    def test_incomplete_outcomes_are_stored_kept_out_of_coding_and_set_the_waiting_state(self):
        for outcome, case_state in (
            ("partially_completed", "paused"),
            ("respondent_unavailable", "not_reachable"),
        ):
            with self.subTest(outcome=outcome):
                death = self._register_death()
                _draft, submission = self._submit_for_new_draft(
                    death, self._completion(valid=False, data={"interview_outcome": outcome})
                )
                self.assertIsNotNone(db.session.get(VaSubmissions, submission.va_sid))
                self.assertEqual(self._stored_outcome(submission), outcome)
                self.assertEqual(death.status, case_state)
                self.assertIsNone(death.va_sid)
                self.assertEqual(
                    get_submission_workflow_state(submission.va_sid), WORKFLOW_CONSENT_REFUSED
                )
                action = db.session.scalar(
                    sa.select(MapCaseTransition.action)
                    .where(MapCaseTransition.death_id == death.death_id,
                           MapCaseTransition.to_state == case_state)
                    .order_by(MapCaseTransition.created_at.desc())
                    .limit(1)
                )
                self.assertEqual(action, f"submitted_{outcome}")

    def test_an_invalid_form_needs_an_incomplete_outcome(self):
        death = self._register_death()
        for picked in (None, "completed", "refused", "bogus"):
            with self.subTest(picked=picked):
                draft = intake_svc.start_draft(
                    self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                    death_id=death.death_id,
                )
                with self.assertRaises(intake_svc.WebIntakeError) as ctx:
                    intake_svc.submit_draft(
                        draft, self.interviewer,
                        completion=self._completion(valid=False, data={"interview_outcome": picked}),
                    )
                self.assertEqual(ctx.exception.status_code, 422)
                self.assertEqual(draft.status, "draft")

    def test_a_later_complete_submission_wins_over_a_refusal_and_an_incomplete_one(self):
        death = self._register_death()
        _d, refused = self._submit_for_new_draft(death, self._completion(data={"Id10013": "no"}))
        # The web form's own refusal path: consent no validates, so valid is true.
        self.assertEqual(death.status, "refused")
        self.assertEqual(self._stored_outcome(refused), "refused")
        _d, partial = self._submit_for_new_draft(
            death, self._completion(valid=False, data={"interview_outcome": "partially_completed"})
        )
        self.assertEqual(death.status, "paused")
        _d, complete = self._submit_for_new_draft(death, self._completion())
        self.assertEqual(death.status, "submitted")
        self.assertEqual(death.va_sid, complete.va_sid)
        # The earlier submissions are kept, still outside coding.
        for superseded in (refused, partial):
            self.assertEqual(
                get_submission_workflow_state(superseded.va_sid), WORKFLOW_CONSENT_REFUSED
            )
        # First complete submission wins: the case is closed to another one.
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            self._submit_for_new_draft(death, self._completion())
        self.assertEqual(ctx.exception.status_code, 409)

    # -- last completed version wins (digitva-xpqm) -------------------------

    def test_completion_time_is_the_skew_corrected_device_time_never_after_now(self):
        now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
        hour = timedelta(hours=1)
        # The device clock is an hour behind the server: its "10:00" is 11:00 here.
        behind = {"completedAt": "2026-10-05T10:00:00+00:00", "deviceClockAt": "2026-10-05T11:00:00+00:00"}
        self.assertEqual(intake_svc._completion_time(behind, now), now - hour)
        # A clock running ahead cannot date a completion in the future.
        ahead = {"completedAt": "2026-10-05T14:00:00+00:00", "deviceClockAt": "2026-10-05T13:00:00+00:00"}
        self.assertEqual(intake_svc._completion_time(ahead, now), now)
        # Without both times (a browser submit, an older app): when it was received.
        for envelope in ({}, {"completedAt": behind["completedAt"]}, {"deviceClockAt": behind["deviceClockAt"]}):
            self.assertEqual(intake_svc._completion_time(envelope, now), now)

    def _resubmit(self, draft, data, *, envelope=None, valid=True):
        return intake_svc.revise_submission(
            self.interviewer, draft.va_sid, reason_code=intake_svc.RESUBMITTED_REASON, data=data,
            answers_sha256=None, completion={"valid": valid, "issues": []}, envelope=envelope or {}, resubmit=True,
        )

    def test_a_resubmission_wins_unless_older_and_an_older_one_is_history_once(self):
        death = self._register_death()
        draft, submission = self._submit_for_new_draft(death, self._completion())
        stored = datetime.fromisoformat(draft.meta["effectiveSavedAt"])
        self.assertEqual(stored, draft.submitted_at)
        data = self._completion(data={"Id10017": "Second"})["data"]
        hour_ago = {"completedAt": (stored - timedelta(hours=1)).isoformat(), "deviceClockAt": stored.isoformat()}
        replaced = sa.select(sa.func.count()).select_from(VaWebIntakeDraft).where(
            VaWebIntakeDraft.death_id == death.death_id, VaWebIntakeDraft.status == "replaced")
        for _ in range(2):
            reply = self._resubmit(draft, data, envelope=hour_ago)
            self.assertEqual((reply["kept"], reply["locked"], reply["changed"]), ("server", False, False))
            self.assertEqual(db.session.scalar(replaced), 1)
        self.assertEqual(self._stored_outcome(submission), "completed")
        # A time equal to the stored one is received later: it wins.
        tie = {"completedAt": stored.isoformat(), "deviceClockAt": stored.isoformat()}
        reply = self._resubmit(draft, data, envelope=tie)
        self.assertEqual((reply["kept"], reply["locked"], reply["changed"]), ("incoming", False, True))
        self.assertGreaterEqual(datetime.fromisoformat(draft.meta["effectiveSavedAt"]), stored)

    def test_a_resubmission_the_case_cannot_take_is_history_and_locked(self):
        death = self._register_death()
        draft, _submission = self._submit_for_new_draft(death, self._completion())
        death.status = "cancelled"
        db.session.flush()
        reply = self._resubmit(draft, self._completion(data={"Id10017": "Late"})["data"])
        self.assertEqual((reply["kept"], reply["locked"], reply["changed"]), ("server", True, False))
        self.assertEqual(death.status, "cancelled")

    # -- a second draft on a case the caller's own earlier draft won (digitva-9kqk) --

    def _won_case_with_open_second_draft(self, user=None):
        """The reachable state: the interviewer's first interview regressed to
        partial, they opened a new draft, then the first was completed again
        and won the case. Returns ``(death, first, second)``; with *user* the
        second draft is that teammate's, opened while the case was open."""
        death = self._register_death()
        first, _submission = self._submit_for_new_draft(death, self._completion())
        partial = self._completion(valid=False, data={"interview_outcome": "partially_completed"})["data"]
        self._resubmit(first, partial, valid=False)
        self.assertIsNone(death.va_sid)  # the regression freed the case
        second = intake_svc.start_draft(
            user or self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=death.death_id,
        )
        self._resubmit(first, self._completion()["data"])
        self.assertEqual((death.status, death.va_sid), ("submitted", first.va_sid))
        return death, first, second

    def _payload_versions(self, va_sid):
        return db.session.scalar(sa.select(sa.func.count()).select_from(VaSubmissionPayloadVersion).where(
            VaSubmissionPayloadVersion.va_sid == va_sid))

    def _history(self, death):
        return db.session.scalars(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.death_id == death.death_id, VaWebIntakeDraft.status == "replaced")).all()

    def test_a_second_own_draft_on_the_callers_won_case_is_a_correction(self):
        death, first, second = self._won_case_with_open_second_draft()
        before = self._payload_versions(first.va_sid)
        completion = self._completion(data={"Id10017": "Second"})
        folded = intake_svc.fold_into_own_submission(self.interviewer, second, completion=completion)
        self.assertIsNotNone(folded)
        own, reply = folded
        self.assertEqual(own.draft_id, first.draft_id)
        self.assertEqual((reply["va_sid"], reply["kept"], reply["locked"], reply["changed"]), (first.va_sid, "incoming", False, True))
        self.assertEqual(self._payload_versions(first.va_sid), before + 1)
        self.assertEqual((death.status, death.va_sid), ("submitted", first.va_sid))
        # The second draft is closed with its answers; it is no superseded copy.
        self.assertEqual((second.status, second.va_sid), ("replaced", None))
        self.assertEqual(second.meta["replacedDraftId"], str(first.draft_id))
        self.assertEqual(intake_svc._answers_of(second)["Id10017"], "Second")
        self.assertEqual(intake_svc._answers_of(first)["Id10017"], "Second")
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraft).where(
            VaWebIntakeDraft.death_id == death.death_id, VaWebIntakeDraft.status == "superseded")), 0)

    def test_a_second_own_draft_when_coding_is_final_is_kept_as_history(self):
        from app.services.workflow.definition import WORKFLOW_CODER_FINALIZED
        from app.services.workflow.state_store import set_submission_workflow_state

        death, first, second = self._won_case_with_open_second_draft()
        set_submission_workflow_state(first.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test")
        before = self._payload_versions(first.va_sid)
        self.assertGreater(before, 0)  # subject present
        folded = intake_svc.fold_into_own_submission(
            self.interviewer, second, completion=self._completion(data={"Id10017": "Too late"}))
        self.assertIsNotNone(folded)
        _own, reply = folded
        self.assertEqual((reply["kept"], reply["locked"], reply["changed"]), ("server", True, False))
        self.assertEqual(self._payload_versions(first.va_sid), before)
        self.assertEqual(second.status, "replaced")
        self.assertEqual(intake_svc._answers_of(second)["Id10017"], "Too late")
        # The coder's version stands, and the late answers are history.
        self.assertIn("Too late", [intake_svc._merged_answers(r).get("Id10017") for r in self._history(death)])
        self.assertEqual((death.status, death.va_sid), ("submitted", first.va_sid))

    def test_a_teammates_draft_on_a_won_case_is_still_a_superseded_copy(self):
        other = self._get_or_make_user("web.interviewer9kqk@test.local", "WebIntake123")
        db.session.add(VaUserAccessGrants(
            user_id=other.user_id, role=VaAccessRoles.interviewer, scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT_ID, notes="teammate", grant_status=VaStatuses.active,
        ))
        db.session.flush()
        death, first, theirs = self._won_case_with_open_second_draft(user=other)
        before = self._payload_versions(first.va_sid)
        self.assertEqual((death.va_sid, theirs.status), (first.va_sid, "draft"))  # subject present
        self.assertIsNone(intake_svc.fold_into_own_submission(other, theirs, completion=self._completion()))
        self.assertIsNone(intake_svc.submit_draft(theirs, other, completion=self._completion(data={"Id10017": "Theirs"})))
        self.assertEqual(theirs.status, "superseded")
        self.assertEqual(self._payload_versions(first.va_sid), before)
        self.assertEqual((death.status, death.va_sid), ("submitted", first.va_sid))

    def test_the_public_revision_still_refuses_the_servers_own_reason(self):
        death = self._register_death()
        draft, _submission = self._submit_for_new_draft(death, self._completion())
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.revise_submission(
                self.interviewer, draft.va_sid, reason_code="resubmitted", data={}, answers_sha256="a" * 64,
                completion={"valid": True, "issues": []}, envelope={},
            )
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (422, "invalid_reason"))

    # -- the locale a draft was filled in -----------------------------------

    def test_a_new_draft_starts_in_the_base_locale(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        self.assertEqual(draft.meta["locale"], "en")
        self.assertEqual(draft.meta["translation_version"], 0)

    def test_a_locale_switch_is_recorded_on_the_draft(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        intake_svc.save_draft_sections(
            draft, sections={}, meta={"locale": "hi", "translation_version": 7}
        )
        self.assertEqual(draft.meta["locale"], "hi")
        self.assertEqual(draft.meta["translation_version"], 7)
        envelope = intake_svc.load_draft_envelope(draft)
        self.assertEqual(envelope["locale"], "hi")
        self.assertEqual(envelope["translation_version"], 7)
        # The keys the envelope already carried are not disturbed by the switch.
        self.assertIn("createdAt", draft.meta)

    def test_a_malformed_locale_or_version_is_refused(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        for bad in ({"locale": "not a locale!"}, {"locale": 7},
                    {"translation_version": -1}, {"translation_version": "7"}):
            with self.subTest(meta=bad):
                with self.assertRaises(intake_svc.WebIntakeError):
                    intake_svc.save_draft_sections(draft, sections={}, meta=bad)
        self.assertEqual(draft.meta["locale"], "en")

    def test_the_payload_carries_the_locale_and_translation_version(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        intake_svc.save_draft_sections(
            draft, sections={}, meta={"locale": "hi", "translation_version": 7}
        )
        payload, _ = intake_svc.build_web_payload(
            draft, {"Id10013": "yes"}, self.interviewer,
            submitted_at=datetime.now(timezone.utc),
        )
        self.assertEqual(payload["intake_locale"], "hi")
        self.assertEqual(payload["intake_translation_version"], 7)

    def test_build_web_payload_lifts_attachment_answers_out_of_the_payload(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        payload, references = intake_svc.build_web_payload(
            draft,
            {
                "Id10013": "yes",
                "death_certificate": "who-va-attachment:abc123",
            },
            self.interviewer,
            submitted_at=datetime.now(timezone.utc),
        )
        self.assertEqual(references, {"death_certificate": "who-va-attachment:abc123"})
        self.assertIsNone(payload["death_certificate"])
        self.assertEqual(payload["AttachmentsExpected"], 1)
        self.assertEqual(payload["intake_source"], "web")
        self.assertEqual(payload["Site"], self.SITE_ID)
        self.assertEqual(payload["form_def"], draft.form_id)

    # ── the web form and ODK sync ──────────────────────────────────────────

    def test_web_form_is_not_enumerated_or_rewritten_by_odk_runtime_sync(self):
        web_form = ensure_web_runtime_form(self.PROJECT_ID, self.SITE_ID)
        db.session.add(MapProjectSiteOdk(
            project_id=self.PROJECT_ID,
            site_id=self.SITE_ID,
            odk_project_id=7,
            odk_form_id=f"ODK_{self.ODK_FORM_ID}",
        ))
        db.session.flush()

        synced = sync_runtime_forms_from_site_mappings()

        self.assertNotIn(web_form.form_id, [f.form_id for f in synced])
        db.session.refresh(web_form)
        self.assertEqual(web_form.form_source, "web")
        self.assertEqual(web_form.odk_form_id, "WEB_WHOVA2022")
        self.assertEqual(web_form.odk_project_id, "0")

    # ── organization unit lifecycle ────────────────────────────────────────

    def _org_unit(self, *, active=True):
        """A one-level tree with a single unit for this project."""
        from app.models.mas_organization import MasOrgLevel, MasOrgUnit

        level = db.session.scalar(
            sa.select(MasOrgLevel).where(
                MasOrgLevel.project_id == self.PROJECT_ID,
                MasOrgLevel.level_code == "district",
            )
        )
        if level is None:
            level = MasOrgLevel(
                project_id=self.PROJECT_ID,
                level_code="district",
                level_name="District",
                depth=1,
            )
            db.session.add(level)
            db.session.flush()
        code = f"D{uuid.uuid4().hex[:6]}"
        unit = MasOrgUnit(
            org_unit_id=uuid.uuid4(),
            project_id=self.PROJECT_ID,
            org_level_id=level.org_level_id,
            unit_code=code,
            unit_name="Test District",
            # ltree path of unit codes; a root unit's path is its own code.
            path=code,
            is_active=active,
        )
        db.session.add(unit)
        db.session.flush()
        return unit

    def test_submit_is_refused_when_the_unit_was_deactivated(self):
        """Routing only attributes to a live unit, and since the routed unit
        decides who may code, an unrouted case reaches no coder at all. Fail
        loudly while the draft is still safe."""
        unit = self._org_unit()
        # self.interviewer holds a project-scoped grant, which reaches any
        # active unit of this tree project (that is the point of a
        # project-scoped grant) — a different rule from the one under test
        # here, which is about a unit going inactive after routing.
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            org_unit_id=unit.org_unit_id,
        )
        unit.is_active = False
        db.session.flush()

        with self.assertRaises(intake_svc.WebIntakeError) as caught:
            intake_svc.submit_draft(draft, self.interviewer, completion=self._completion())
        self.assertIn("no longer active", str(caught.exception))
        self.assertEqual(draft.status, "draft", "the draft must survive the refusal")

    def _unplaced_unit(self):
        """A depth-2 unit with no parent: imported, not yet mapped."""
        from app.models.mas_organization import MasOrgLevel, MasOrgUnit
        from app.services import organization_service as org

        level = db.session.scalar(
            sa.select(MasOrgLevel).where(
                MasOrgLevel.project_id == self.PROJECT_ID,
                MasOrgLevel.level_code == "chc",
            )
        )
        if level is None:
            level = MasOrgLevel(
                project_id=self.PROJECT_ID,
                level_code="chc",
                level_name="CHC",
                depth=2,
            )
            db.session.add(level)
            db.session.flush()
        code = f"C{uuid.uuid4().hex[:6]}"
        unit = MasOrgUnit(
            org_unit_id=uuid.uuid4(),
            project_id=self.PROJECT_ID,
            org_level_id=level.org_level_id,
            unit_code=code,
            unit_name="Test CHC",
            path=code,
        )
        db.session.add(unit)
        db.session.flush()
        return unit, org

    def test_submit_is_refused_while_the_unit_is_unplaced(self):
        """An imported unit whose parent is not yet mapped cannot be
        attributed to a coder any more than an inactive one can."""
        district = self._org_unit()  # gives WIT01 a top-level district
        unit, org = self._unplaced_unit()
        self.assertIn(unit.unit_code, org.unplaced_unit_codes(self.PROJECT_ID))

        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            org_unit_id=unit.org_unit_id,
        )
        with self.assertRaises(intake_svc.WebIntakeError) as caught:
            intake_svc.submit_draft(draft, self.interviewer, completion=self._completion())
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("not yet placed", str(caught.exception))
        self.assertEqual(draft.status, "draft", "the draft must survive the refusal")

        org.update_unit(self.PROJECT_ID, unit.org_unit_id, parent_org_unit_id=district.org_unit_id)
        db.session.flush()
        self.assertNotIn(unit.unit_code, org.unplaced_unit_codes(self.PROJECT_ID))

        submission = intake_svc.submit_draft(draft, self.interviewer, completion=self._completion())
        self.assertIsNotNone(submission)

    def test_a_deactivated_unit_contributes_no_code_to_the_payload(self):
        unit = self._org_unit(active=False)
        self.assertNotIn("org_district_code", intake_svc._unit_context(unit.org_unit_id))

    # ── unit routing is mandatory in a tree project (regression guard) ─────
    #
    # Before this rule, a project- or site-scoped interviewer grant produced
    # an empty ``org_units`` list from ``interviewer_context`` (unit-scoped
    # grants are the only source), so the "unit required" check never fired
    # and the entry was created with ``org_unit_id = NULL`` — unroutable, and
    # so invisible to every coder. See docs/policy/organization-model.md.

    def test_project_scoped_interviewer_in_tree_project_refused_without_unit(self):
        self._org_unit()  # gives WIT01 an organization tree
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            self._register_death()
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("organization unit", str(ctx.exception))

    def test_project_scoped_interviewer_in_tree_project_succeeds_with_any_unit(self):
        # self.interviewer's grant is project-scoped (no unit grant at all),
        # but a project-scoped interviewer grant reaches every active unit of
        # the project — that is the point of a scope wider than one unit.
        unit = self._org_unit()
        death = self._register_death(org_unit_id=str(unit.org_unit_id))
        self.assertEqual(death.org_unit_id, unit.org_unit_id)

    def test_unit_scoped_interviewer_refused_a_unit_outside_their_subtree(self):
        granted_unit = self._org_unit()
        other_unit = self._org_unit()
        unit_interviewer = self._get_or_make_user(
            "web.unit.interviewer@test.local", "WebIntake123"
        )
        db.session.add(VaUserAccessGrants(
            user_id=unit_interviewer.user_id,
            role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=granted_unit.org_unit_id,
            notes="unit-scoped web intake test grant",
            grant_status=VaStatuses.active,
        ))
        db.session.flush()

        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.register_death(
                unit_interviewer,
                project_id=self.PROJECT_ID,
                site_id=self.SITE_ID,
                org_unit_id=str(other_unit.org_unit_id),
                deceased_name="Outside Subtree",
                deceased_sex="male",
                date_of_death=date.today().isoformat(),
            )
        self.assertEqual(ctx.exception.status_code, 403)

        death = intake_svc.register_death(
            unit_interviewer,
            project_id=self.PROJECT_ID,
            site_id=self.SITE_ID,
            org_unit_id=str(granted_unit.org_unit_id),
            deceased_name="Inside Subtree",
            deceased_sex="male",
            date_of_death=date.today().isoformat(),
        )
        self.assertEqual(death.org_unit_id, granted_unit.org_unit_id)

    def test_no_tree_project_still_creates_entry_with_null_unit(self):
        # PROJECT_ID has no MasOrgLevel row unless a test opts in via
        # _org_unit(); this test deliberately does not.
        death = self._register_death()
        self.assertIsNone(death.org_unit_id)

    # ── partial date of birth (digitva-tld2) ────────────────────────────────

    def test_register_death_keeps_a_partial_birth_date_and_serializes_it(self):
        for value in ("1950", "1950-07"):
            with self.subTest(value=value):
                death = self._register_death(date_of_birth_partial=f" {value} ")
                self.assertEqual(death.date_of_birth_partial, value)
                self.assertIsNone(death.date_of_birth)
                body = intake_svc.serialize_death(death)
                self.assertEqual(body["date_of_birth_partial"], value)
                self.assertIsNone(body["date_of_birth"])
        exact = self._register_death(date_of_birth="1950-07-12")
        self.assertIsNone(intake_svc.serialize_death(exact)["date_of_birth_partial"])

    def test_register_death_refuses_a_bad_partial_birth_date(self):
        today = date.today()
        death_day = today - timedelta(days=10)
        next_month = (today.replace(day=1) + timedelta(days=32)).strftime("%Y-%m")
        for value in (
            "1950-13", "1950-00", "1950-7", "50", "1950-07-01", "195O", "1899", "1899-12",
            str(today.year + 1), next_month,
        ):
            with self.subTest(value=value), self.assertRaises(intake_svc.WebIntakeError):
                self._register_death(date_of_birth_partial=value)
        # After the date of death, at the precision given.
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(
                date_of_death="2000-03-15", date_of_birth_partial="2000-04",
            )
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(date_of_death="2000-03-15", date_of_birth_partial="2001")
        # The same month or year as the death is plausible.
        same = self._register_death(
            date_of_death=death_day.isoformat(), date_of_birth_partial=death_day.strftime("%Y-%m"),
        )
        self.assertEqual(same.date_of_birth_partial, death_day.strftime("%Y-%m"))
        with self.assertRaises(intake_svc.WebIntakeError) as both:
            self._register_death(date_of_birth="1950-07-12", date_of_birth_partial="1950-07")
        self.assertIn("not both", str(both.exception))

    def test_prefill_maps_a_partial_birth_date_to_the_who_precision_fields(self):
        month_year = self._register_death(date_of_birth_partial="1950-07", age_years=None)
        prefill = intake_svc._prefill_from_death(month_year, self.interviewer)
        self.assertNotIn("dateOfBirth", prefill["deceased"])
        self.assertNotIn("Id10021", prefill["answers"])
        self.assertEqual(
            {k: prefill["answers"].get(k) for k in ("Id10020", "dob_precision", "dob_month_year", "dob_year")},
            {"Id10020": "no", "dob_precision": "month_year", "dob_month_year": "1950-07-01", "dob_year": None},
        )

        year = self._register_death(date_of_birth_partial="1950", age_years=74)
        prefill = intake_svc._prefill_from_death(year, self.interviewer)
        self.assertEqual(
            {k: prefill["answers"].get(k) for k in ("Id10020", "dob_precision", "dob_month_year", "dob_year")},
            {"Id10020": "no", "dob_precision": "year", "dob_month_year": None, "dob_year": "1950-01-01"},
        )
        # The age still prefills beside it and is locked; the partial date is not.
        self.assertEqual(prefill["deceased"]["ageInYears"], 74)
        self.assertIn("age_adult", prefill["lockedQuestionNames"])
        self.assertFalse({"dob_precision", "dob_year", "Id10020"} & set(prefill["lockedQuestionNames"]))

        exact = self._register_death(date_of_birth="1950-07-12")
        prefill = intake_svc._prefill_from_death(exact, self.interviewer)
        self.assertEqual(prefill["deceased"]["dateOfBirth"], "1950-07-12")
        self.assertNotIn("dob_precision", prefill["answers"])

    def test_partial_birth_date_answers_survive_the_submit_relevance_strip(self):
        death = self._register_death(date_of_birth_partial="1950-07")
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=death.death_id,
        )
        answers = {k: draft.prefill["answers"][k] for k in ("Id10020", "dob_precision", "dob_month_year")}
        submission = intake_svc.submit_draft(draft, self.interviewer, completion=self._completion(data=answers))
        payload = db.session.get(VaSubmissionPayloadVersion, submission.active_payload_version_id).payload_data
        self.assertEqual(payload["dob_precision"], "month_year")
        self.assertEqual(payload["dob_month_year"], "1950-07-01")
        self.assertNotIn("Id10021", payload)

    # ── locked prefill enforced on the server (digitva-p6fs.9) ──────────────

    def _locked_case_draft(self):
        """A draft whose prefill locks the interviewer, both area presets,
        ABHA and the registered age; returns (draft, the authoritative locked values)."""
        from app.services import organization_service as org

        self.interviewer.name = "Field Worker"
        self.interviewer.sex = "female"
        self.interviewer.year_of_birth = date.today().year - 40
        unit = self._org_unit()
        org.set_unit_va_presets(self.PROJECT_ID, unit.org_unit_id, hiv_mortality="high", malaria_mortality="low")
        death = self._register_death(org_unit_id=str(unit.org_unit_id), abha_number="12345678901234")
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=death.death_id,
        )
        authoritative = {
            "Id10010": "Field Worker", "Id10010b": "female",
            "Id10010c": str(self.interviewer.user_id), "Id10002": "high", "Id10003": "low",
            "abha_number": "12345678901234", "age_group": "adult", "age_adult": 62,
        }
        self.assertEqual(set(draft.prefill["lockedQuestionNames"]), set(authoritative))
        return draft, authoritative

    _TAMPERED = {
        "Id10010": "Someone Else", "Id10010b": "male",
        "Id10010c": "00000000-0000-0000-0000-000000000000", "Id10002": "veryl", "Id10003": "high",
        "abha_number": "99999999999999", "age_group": "child", "age_adult": 30,
    }

    def test_draft_save_overwrites_tampered_locked_answers(self):
        draft, authoritative = self._locked_case_draft()
        sent = {"interviewer": dict(self._TAMPERED), "background": {"Id10019": "female", "Id10002": "low"}}
        intake_svc.save_draft_sections(draft, sections=sent)
        data = intake_svc.load_draft_envelope(draft)["data"]
        for name, value in authoritative.items():
            with self.subTest(name=name):
                self.assertEqual(data[name], value)
        self.assertEqual(data["Id10019"], "female")
        # The caller's dicts are not rewritten in place.
        self.assertEqual(sent["interviewer"]["Id10010"], "Someone Else")

    def test_draft_save_keeps_a_dropped_locked_answer_and_clears_an_unlocked_one(self):
        draft, authoritative = self._locked_case_draft()
        intake_svc.save_draft_sections(
            draft, sections={"interviewer": {**authoritative, "Id10007": "Ramesh"}},
        )
        intake_svc.save_draft_sections(draft, sections={"interviewer": {"Id10010": "Field Worker"}})
        rows = {s.section_name: s.data for s in draft.sections}
        self.assertEqual(rows["interviewer"], authoritative)
        self.assertNotIn("Id10007", rows["interviewer"])

    def test_untampered_save_is_stored_exactly_as_sent(self):
        draft, authoritative = self._locked_case_draft()
        sent = {"interviewer": {**authoritative, "Id10007": "Ramesh"}, "consent": {"Id10013": "yes"}}
        intake_svc.save_draft_sections(draft, sections=sent)
        self.assertEqual({s.section_name: s.data for s in draft.sections}, sent)

    def test_submit_overwrites_tampered_locked_answers(self):
        draft, authoritative = self._locked_case_draft()
        submission = intake_svc.submit_draft(
            draft, self.interviewer, completion=self._completion(data=dict(self._TAMPERED)),
        )
        payload = db.session.get(VaSubmissionPayloadVersion, submission.active_payload_version_id).payload_data
        for name, value in authoritative.items():
            with self.subTest(name=name):
                self.assertEqual(payload[name], value)

    def test_a_draft_without_locked_names_is_recomputed_not_rewritten(self):
        self.interviewer.name = "Field Worker"
        draft = intake_svc.start_draft(self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID)
        draft.prefill = {}  # a draft started before lockedQuestionNames existed
        intake_svc.save_draft_sections(draft, sections={"interviewer": {"Id10010": "Anyone"}})
        self.assertEqual(draft.sections[0].data, {"Id10010": "Field Worker"})
        self.assertEqual(draft.prefill, {})
        self.assertEqual(intake_svc._locked_answers({}), {})
        self.assertEqual(
            intake_svc._locked_answers({"lockedQuestionNames": ["Id10010", "Id10002"], "interviewer": {}}), {},
        )


    # ── correcting a registered death (digitva-uq6v) ───────────────────────

    def _audit_rows(self, death, action):
        return db.session.scalars(
            sa.select(MapCaseTransition).where(
                MapCaseTransition.death_id == death.death_id, MapCaseTransition.action == action
            )
        ).all()

    def test_update_death_corrects_fields_audits_names_only_and_validates_as_register(self):
        death = self._register_death()
        corrected = intake_svc.update_death(
            self.interviewer, death.death_id, {"deceased_name": " Asha Rao ", "age_years": "63", "remarks": "x"},
        )
        self.assertEqual((corrected.deceased_name, corrected.age_years, corrected.remarks), ("Asha Rao", 63, "x"))
        self.assertEqual(corrected.deceased_sex, "female")
        rows = self._audit_rows(death, intake_svc.DETAILS_EDITED)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].reason, "deceased_name, age_years, remarks")
        self.assertNotIn("Rao", rows[0].reason)
        self.assertEqual((rows[0].from_state, rows[0].to_state), (death.status, death.status))
        # A repeat of the same values changes and audits nothing.
        intake_svc.update_death(self.interviewer, death.death_id, {"deceased_name": "Asha Rao"})
        self.assertEqual(len(self._audit_rows(death, intake_svc.DETAILS_EDITED)), 1)
        # Cross-field rules see the case as it would stand.
        for bad in (
            {"date_of_birth": (date.today() + timedelta(days=1)).isoformat()},
            {"date_of_birth": "1990-01-01", "date_of_birth_partial": "1990"},
            {"deceased_sex": "robot"},
            {"deceased_name": ""},
            {"age_years": "200"},
            {"abha_number": "12"},
            {"date_of_death": (date.today() - timedelta(days=9000)).isoformat(), "date_of_birth": "2020-01-01"},
            {"nope": "x"},
            {},
        ):
            with self.assertRaises(intake_svc.WebIntakeError, msg=str(bad)) as ctx:
                intake_svc.update_death(self.interviewer, death.death_id, bad)
            self.assertEqual(ctx.exception.status_code, 400, bad)
        self.assertEqual(death.deceased_name, "Asha Rao")

    def test_update_death_is_refused_once_an_interview_is_completed(self):
        death = self._register_death()
        intake_svc.update_death(self.interviewer, death.death_id, {"place_of_death": "Home"})
        self.assertEqual(death.place_of_death, "Home")  # allowed first
        self._submit_for_new_draft(death, self._completion())
        self.assertEqual(death.status, "submitted")
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.update_death(self.interviewer, death.death_id, {"place_of_death": "Hospital"})
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (409, "case_completed"))
        self.assertEqual(death.place_of_death, "Home")

    def test_an_incomplete_interview_does_not_lock_the_case(self):
        death = self._register_death()
        self._submit_for_new_draft(death, self._completion(valid=False, data={"interview_outcome": "partially_completed"}))
        self.assertEqual(death.status, "paused")
        intake_svc.update_death(self.interviewer, death.death_id, {"informant_name": "Ravi"})
        self.assertEqual(death.informant_name, "Ravi")

    def test_update_death_scope_supervisor_and_staleness(self):
        death = self._register_death()
        outsider = self._get_or_make_user("web.outsider@test.local", "WebIntake123")
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.update_death(outsider, death.death_id, {"remarks": "x"})
        self.assertEqual(ctx.exception.status_code, 404)
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.update_death(self.interviewer, "not-a-uuid", {"remarks": "x"})
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIsNone(death.remarks)

        # A supervisor with no interviewer grant may correct what they supervise.
        boss = self._get_or_make_user("web.boss@test.local", "WebIntake123")
        db.session.add(VaUserAccessGrants(
            user_id=boss.user_id, role=VaAccessRoles.data_manager, scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT_ID, notes="death edit test", grant_status=VaStatuses.active,
        ))
        db.session.flush()
        intake_svc.update_death(boss, death.death_id, {"remarks": "by boss"})
        self.assertEqual(death.remarks, "by boss")
        self.assertEqual(self._audit_rows(death, intake_svc.DETAILS_EDITED)[0].actor_user_id, boss.user_id)

        seen = death.updated_at.isoformat()
        intake_svc.update_death(self.interviewer, death.death_id, {"remarks": "new"}, if_updated_at=seen)
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.update_death(self.interviewer, death.death_id, {"remarks": "newer"}, if_updated_at=seen)
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (409, "death_stale"))
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.update_death(self.interviewer, death.death_id, {"remarks": "x"}, if_updated_at="yesterday")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(death.remarks, "new")

    def test_a_completed_superseded_copy_without_a_winner_locks_the_case(self):
        death = self._register_death()
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=death.death_id,
        )
        draft.status = "superseded"
        draft.meta = {**draft.meta, "interviewOutcome": "completed"}
        db.session.flush()
        self.assertIsNone(death.va_sid)  # subject present: no winning interview
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.update_death(self.interviewer, death.death_id, {"remarks": "x"})
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (409, "case_completed"))
        self.assertIsNone(death.remarks)

    def test_update_death_audit_reason_fits_when_every_field_changes(self):
        death = self._register_death()
        everything = {
            "deceased_name": "Asha Rao", "deceased_sex": "male", "abha_number": "12-3456-7890-1234",
            "abha_address": "asha.rao@abdm", "date_of_birth": "1960-01-01", "age_years": 64,
            "date_of_death": (date.today() - timedelta(days=5)).isoformat(), "place_of_death": "Home",
            "address": "1 Main Road", "address_house_street": "1 Main", "address_village_ward": "Ward 2",
            "address_landmark": "Temple", "informant_name": "Ravi", "informant_phone": "9876543210",
            "informant_phone_2": "9876543211", "remarks": "r", "father_name": "F", "mother_name": "M",
        }
        updated = intake_svc.update_death(self.interviewer, death.death_id, everything)
        self.assertEqual(updated.deceased_name, "Asha Rao")
        [row] = self._audit_rows(death, intake_svc.DETAILS_EDITED)
        self.assertEqual(row.reason, f"{len(everything)} fields")
        self.assertNotIn("Rao", row.reason)

    def test_a_legacy_invalid_stored_value_must_be_fixed_in_the_same_edit(self):
        death = self._register_death()
        death.informant_phone = "ask the neighbour"  # free text from before phone validation
        db.session.flush()
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.update_death(self.interviewer, death.death_id, {"remarks": "x"})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Informant phone", str(ctx.exception))
        self.assertIn("correct it in this edit", str(ctx.exception))
        self.assertIsNone(death.remarks)
        updated = intake_svc.update_death(
            self.interviewer, death.death_id, {"remarks": "x", "informant_phone": "98765 43210"},
        )
        self.assertEqual((updated.remarks, updated.informant_phone), ("x", "9876543210"))

    def test_a_direct_start_awaiting_its_details_is_not_editable(self):
        draft = intake_svc.start_draft(self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID)
        death = db.session.get(VaDeathRegister, draft.death_id)
        self.assertEqual(death.status, "draft_identity")
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.update_death(self.interviewer, death.death_id, {"remarks": "x"})
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (409, "details_pending"))

    def test_completing_an_interview_overwrites_case_identity_and_audits_the_fields(self):
        death = self._register_death()
        self.assertEqual(death.deceased_name, "Asha Devi")
        _draft, _submission = self._submit_for_new_draft(
            death, self._completion(data={"Id10018": "Rao", "Id10019": "male"}),
        )
        self.assertEqual((death.deceased_name, death.deceased_sex), ("Asha Rao", "male"))
        rows = self._audit_rows(death, intake_svc.IDENTITY_FROM_INTERVIEW)
        self.assertEqual([r.reason for r in rows], ["deceased_name, deceased_sex"])
        # An interview that agrees with the register writes no such row.
        other = self._register_death()
        self._submit_for_new_draft(other, self._completion())
        self.assertEqual(self._audit_rows(other, intake_svc.IDENTITY_FROM_INTERVIEW), [])

    def test_api_patch_death(self):
        death = self._register_death()
        db.session.commit()
        self._login(str(self.interviewer.user_id))
        url = f"/api/v1/intake/deaths/{death.death_id}"
        self.assertEqual(self.client.patch(url, json={"remarks": "x"}).status_code, 400)  # no CSRF
        response = self.client.patch(url, json={"remarks": "x", "deceased_name": "Asha Rao"}, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        case = response.get_json()["case"]
        self.assertEqual((case["deceased"]["name"], case["remarks"]), ("Asha Rao", "x"))
        response = self.client.patch(url, json={"deceased_sex": "robot"}, headers=self._csrf_headers())
        self.assertEqual((response.status_code, response.get_json()["code"]), (422, "invalid_death"))
        response = self.client.patch(
            url, json={"remarks": "y", "if_updated_at": "2020-01-01T00:00:00+00:00"}, headers=self._csrf_headers(),
        )
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "death_stale"))
        self._submit_for_new_draft(death, self._completion())
        db.session.commit()
        response = self.client.patch(url, json={"remarks": "z"}, headers=self._csrf_headers())
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "case_completed"))
        response = self.client.patch(
            f"/api/v1/intake/deaths/{uuid.uuid4()}", json={"remarks": "z"}, headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 404)


class WebFormTypeFromProjectSettingTests(BaseTestCase):
    """The web ``va_forms`` row carries the project's configured form type.

    WP1 of docs/planning/web-capture-project-configuration-plan.md: the form
    type was hardcoded to ``WHO_2022_VA``, so a project could not collect on
    the ``_SOCIAL`` layer through the browser at all.
    """

    PROJECT_ID = "WFT01"
    SITE_ID = "WF01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID,
            project_code=cls.PROJECT_ID,
            project_name="Web Form Type Project",
            project_nickname="WebFormType",
            project_status=VaStatuses.active,
            project_registered_at=now,
            project_updated_at=now,
            web_intake_mode="direct",
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID,
            site_name="Web Form Type Site",
            site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active,
            site_registered_at=now,
            site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT_ID,
            site_id=cls.SITE_ID,
            project_site_status=VaStatuses.active,
            project_site_registered_at=now,
            project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(cls.PROJECT_ID, cls.SITE_ID)

        # Interviewer grants resolve through va_forms, and the web form row is
        # what this class is about creating — so the grant hangs off an ODK
        # form, as it does for a project that collects both ways.
        db.session.add(VaForms(
            form_id="WFT01WF0101",
            project_id=cls.PROJECT_ID,
            site_id=cls.SITE_ID,
            odk_form_id="ODK_WFT01WF0101",
            odk_project_id="7",
            form_type="WHO VA 2022",
            form_source="odk",
            form_status=VaStatuses.active,
            form_registered_at=now,
            form_updated_at=now,
        ))
        db.session.flush()

        cls.base_type = cls._ensure_form_type("WHO_2022_VA", "WHO 2022 VA Form")
        cls.social_type = cls._ensure_form_type(
            "WHO_2022_VA_SOCIAL", "WHO 2022 VA with social autopsy"
        )
        cls.retired_type = cls._ensure_form_type(
            "WFT_RETIRED", "Web Form Type Retired", is_active=False
        )

        cls.interviewer = cls._get_or_make_user(
            "web.formtype@test.local", "WebIntake123"
        )
        db.session.add(VaUserAccessGrants(
            user_id=cls.interviewer.user_id,
            role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project,
            project_id=cls.PROJECT_ID,
            notes="web form type test grant",
            grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.project = db.session.get(VaProjectMaster, self.PROJECT_ID)
        self.project.web_intake_form_type_id = None
        db.session.commit()

    def _web_form(self):
        return db.session.scalar(
            sa.select(VaForms).where(
                VaForms.project_id == self.PROJECT_ID,
                VaForms.site_id == self.SITE_ID,
                VaForms.form_source == "web",
            )
        )

    def test_an_unconfigured_project_still_gets_the_default_form_type(self):
        form = ensure_web_runtime_form(self.PROJECT_ID, self.SITE_ID)
        self.assertEqual(form.form_type_id, self.base_type.form_type_id)

    def test_start_draft_creates_a_web_form_carrying_the_configured_type(self):
        """Positive control first: the row does not exist before start_draft."""
        self.assertIsNone(self._web_form())

        self.project.web_intake_form_type_id = self.social_type.form_type_id
        db.session.commit()

        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        form = db.session.get(VaForms, draft.form_id)
        self.assertEqual(form.form_source, "web")
        self.assertEqual(form.form_type_id, self.social_type.form_type_id)
        self.assertEqual(form.form_type, self.social_type.form_type_name)

    def test_an_inactive_configured_form_type_is_refused(self):
        """Positive control first: an active type materializes the row."""
        self.project.web_intake_form_type_id = self.social_type.form_type_id
        db.session.commit()
        self.assertIsNotNone(ensure_web_runtime_form(self.PROJECT_ID, self.SITE_ID))

        db.session.delete(self._web_form())
        self.project.web_intake_form_type_id = self.retired_type.form_type_id
        db.session.commit()

        with self.assertRaises(ValueError) as ctx:
            ensure_web_runtime_form(self.PROJECT_ID, self.SITE_ID)
        self.assertIn("not an active form type", str(ctx.exception))
        self.assertIsNone(self._web_form())

    def test_an_existing_web_form_keeps_the_type_it_was_created_with(self):
        first = ensure_web_runtime_form(self.PROJECT_ID, self.SITE_ID)
        self.assertEqual(first.form_type_id, self.base_type.form_type_id)

        self.project.web_intake_form_type_id = self.social_type.form_type_id
        db.session.commit()

        again = ensure_web_runtime_form(self.PROJECT_ID, self.SITE_ID)
        self.assertEqual(again.form_id, first.form_id)
        self.assertEqual(again.form_type_id, self.base_type.form_type_id)


class IntakeNoteResolutionTests(BaseTestCase):
    """NULL is the system default note; "" is no welcome screen at all."""

    def test_null_resolves_to_the_default_note(self):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.web_intake_intake_note = None
        self.assertEqual(
            intake_svc.resolve_intake_note(project), intake_svc.DEFAULT_INTAKE_NOTE
        )

    def test_a_stored_note_is_served_and_a_blank_one_means_no_screen(self):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.web_intake_intake_note = "Say this first."
        self.assertEqual(intake_svc.resolve_intake_note(project), "Say this first.")

        project.web_intake_intake_note = "   "
        self.assertEqual(intake_svc.resolve_intake_note(project), "")


class InterviewerUnitScopeTests(BaseTestCase):
    """The per-project-site grant rule (docs/policy/web-intake.md, "Who sees
    which cases"), as ``list_deaths``, the create-time ``_require_scope`` and
    ``reachable_unit_ids`` apply it.

    P has sites S1 and S2 and a tree: A (with child A1) and B. Q is another
    project with its own tree (QX) and site S3.
    """

    P, Q = "YW1P", "YW1Q"
    S1, S2, S3 = "YW11", "YW12", "YW13"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from app.services import organization_service as org

        now = datetime.now(timezone.utc)
        pairs = ((cls.P, cls.S1), (cls.P, cls.S2), (cls.Q, cls.S3))
        for project_id in (cls.P, cls.Q):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=project_id,
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, web_intake_mode="both",
            ))
        for site_id in (cls.S1, cls.S2, cls.S3):
            db.session.add(VaSiteMaster(
                site_id=site_id, site_name=site_id, site_abbr=site_id, site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
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
                odk_form_id=f"ODK_{project_id}{site_id}", odk_project_id="7", form_type="WHO VA 2022",
                form_source="odk", form_status=VaStatuses.active, form_registered_at=now,
                form_updated_at=now,
            ))
        db.session.flush()

        def tree(project_id, roots):
            org.seed_default_organization(project_id)
            levels = sorted(org.list_levels(project_id), key=lambda lv: lv.depth)
            return {
                code: org.create_unit(
                    project_id, org_level_id=levels[0].org_level_id, unit_code=code, unit_name=code
                )
                for code in roots
            }, levels

        roots, levels = tree(cls.P, ("YWA", "YWB"))
        cls.unit_a, cls.unit_b = roots["YWA"], roots["YWB"]
        cls.unit_a1 = org.create_unit(
            cls.P, org_level_id=levels[1].org_level_id, unit_code="YWA1", unit_name="YWA1",
            parent_org_unit_id=cls.unit_a.org_unit_id,
        )
        cls.unit_qx = tree(cls.Q, ("YWQX",))[0]["YWQX"]

        # Registers the deaths: a project grant sees every unit.
        cls.wide = cls._get_or_make_user("yw1.wide@test.local", "WebIntake123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.wide.user_id, role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project, project_id=cls.P,
            notes="yw11 test", grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.deaths = {
            (site_id, unit.unit_code): self._register(self.wide, site_id, unit)
            for site_id in (self.S1, self.S2)
            for unit in (self.unit_a1, self.unit_b)
        }

    # ── helpers ────────────────────────────────────────────────────────────

    def _register(self, user, site_id, unit):
        return intake_svc.register_death(
            user, project_id=self.P, site_id=site_id, org_unit_id=str(unit.org_unit_id),
            deceased_name="Scope Test", deceased_sex="male", date_of_death=date.today().isoformat(),
        ).death_id

    def _user(self, label, *grants):
        """A user with *grants*: ("unit", unit) | ("site", project, site) | ("project", project)."""
        user = self._get_or_make_user(f"yw1.{label}@test.local", "WebIntake123")
        for kind, *args in grants:
            scope = {
                "unit": lambda unit: dict(
                    scope_type=VaAccessScopeTypes.org_unit, org_unit_id=unit.org_unit_id),
                "site": lambda project_id, site_id: dict(
                    scope_type=VaAccessScopeTypes.project_site,
                    project_site_id=db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
                        VaProjectSites.project_id == project_id, VaProjectSites.site_id == site_id))),
                "project": lambda project_id: dict(
                    scope_type=VaAccessScopeTypes.project, project_id=project_id),
            }[kind](*args)
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.interviewer, notes="yw11 test",
                grant_status=VaStatuses.active, **scope,
            ))
        db.session.flush()
        return user

    def _listed(self, user, site_id):
        return {r.death_id for r in intake_svc.list_deaths(user, project_id=self.P, site_id=site_id)}

    def _create_status(self, user, site_id, unit):
        try:
            self._register(user, site_id, unit)
        except intake_svc.WebIntakeError as exc:
            return exc.status_code
        return 201

    def _assert_subtree_only(self, user, site_id):
        listed = self._listed(user, site_id)
        self.assertIn(self.deaths[(site_id, "YWA1")], listed)
        self.assertNotIn(self.deaths[(site_id, "YWB")], listed)
        reachable = intake_svc.reachable_unit_ids(user, self.P, site_id)
        self.assertIn(self.unit_a1.org_unit_id, reachable)
        self.assertEqual(reachable, {self.unit_a.org_unit_id, self.unit_a1.org_unit_id})
        self.assertEqual(self._create_status(user, site_id, self.unit_a1), 201)
        self.assertEqual(self._create_status(user, site_id, self.unit_b), 403)

    def _assert_whole_site(self, user, site_id):
        listed = self._listed(user, site_id)
        self.assertIn(self.deaths[(site_id, "YWA1")], listed)
        self.assertIn(self.deaths[(site_id, "YWB")], listed)
        self.assertIsNone(intake_svc.reachable_unit_ids(user, self.P, site_id))
        self.assertEqual(self._create_status(user, site_id, self.unit_b), 201)

    # ── the rule ───────────────────────────────────────────────────────────

    def test_unit_grant_only_reaches_its_subtree(self):
        user = self._user("unit", ("unit", self.unit_a))
        self._assert_subtree_only(user, self.S1)
        self._assert_subtree_only(user, self.S2)

    def test_unit_grant_in_another_project_does_not_reach_this_one(self):
        user = self._user("two.projects", ("unit", self.unit_a), ("unit", self.unit_qx))
        self._assert_subtree_only(user, self.S1)
        self.assertNotIn(self.unit_qx.org_unit_id, intake_svc.reachable_unit_ids(user, self.P))

        q_only = self._user("q.only", ("unit", self.unit_qx))
        self.assertEqual(intake_svc.reachable_unit_ids(q_only, self.Q), {self.unit_qx.org_unit_id})
        self.assertEqual(intake_svc.reachable_unit_ids(q_only, self.P), set())
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.list_deaths(q_only, project_id=self.P, site_id=self.S1)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(self._create_status(q_only, self.S1, self.unit_a1), 403)

    def test_site_grant_widens_its_own_site_only(self):
        user = self._user("site.plus.unit", ("site", self.P, self.S1), ("unit", self.unit_a))
        self._assert_whole_site(user, self.S1)
        self._assert_subtree_only(user, self.S2)

    def test_site_grant_beside_a_unit_grant_on_the_same_site_sees_the_whole_site(self):
        user = self._user("site.and.unit", ("site", self.P, self.S2), ("unit", self.unit_a))
        self._assert_whole_site(user, self.S2)
        self._assert_subtree_only(user, self.S1)

    def test_project_grant_beside_a_unit_grant_sees_every_site_whole(self):
        user = self._user("project.and.unit", ("project", self.P), ("unit", self.unit_a))
        self._assert_whole_site(user, self.S1)
        self._assert_whole_site(user, self.S2)

    def test_the_per_project_picker_offers_the_union_over_sites(self):
        site_grant = self._user("picker.site", ("site", self.P, self.S1))
        self.assertIsNone(intake_svc.reachable_unit_ids(site_grant, self.P))
        site_and_unit = self._user("picker.site.unit", ("site", self.P, self.S2), ("unit", self.unit_a))
        self.assertIsNone(intake_svc.reachable_unit_ids(site_and_unit, self.P))
        unit_only = self._user("picker.unit", ("unit", self.unit_a))
        self.assertEqual(
            intake_svc.reachable_unit_ids(unit_only, self.P),
            {self.unit_a.org_unit_id, self.unit_a1.org_unit_id},
        )
        self.assertEqual(intake_svc.reachable_unit_ids(site_grant, self.Q), set())
