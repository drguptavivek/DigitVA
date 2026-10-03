"""Web intake prefill map (digitva-vzk.1) and interviewer profile (vzk.3).

One test per row of the prefill map in docs/policy/web-intake.md, for a
registered case and a direct start, plus which answers are locked: only the
interviewer's name, sex and id, the area presets, ABHA and the case's
registered age (digitva-q219). Everything else is an ordinary editable answer.
"""
import uuid
from datetime import UTC, date, datetime, timedelta

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
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

INTERVIEWER_LOCKS = {"Id10010", "Id10010b", "Id10010c"}
ADULT_AGE_LOCKS = {"age_group", "age_adult"}


class WebIntakePrefillTests(BaseTestCase):
    PROJECT_ID = "WPF01"
    SITE_ID = "WPF1"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID, project_code=cls.PROJECT_ID, project_name="Prefill Test",
            project_nickname="Prefill", project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now, web_intake_mode="both",
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID, site_name="Prefill Site", site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT_ID, site_id=cls.SITE_ID, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(cls.PROJECT_ID, cls.SITE_ID)
        # Interviewer grants resolve through va_forms, as in a real project.
        db.session.add(VaForms(
            form_id="WPF01WPF101", project_id=cls.PROJECT_ID, site_id=cls.SITE_ID,
            odk_form_id="ODK_WPF01", odk_project_id="7", form_type="WHO VA 2022", form_source="odk",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))

        # A two-level tree: Himachal Pradesh > Solan.
        state = MasOrgLevel(project_id=cls.PROJECT_ID, level_code="state", level_name="State", depth=1)
        district = MasOrgLevel(project_id=cls.PROJECT_ID, level_code="district", level_name="District", depth=2)
        db.session.add_all([state, district])
        db.session.flush()
        root = MasOrgUnit(
            org_unit_id=uuid.uuid4(), project_id=cls.PROJECT_ID, org_level_id=state.org_level_id,
            unit_code="HP", unit_name="Himachal Pradesh", path="HP", is_active=True,
        )
        db.session.add(root)
        db.session.flush()
        cls.unit = MasOrgUnit(
            org_unit_id=uuid.uuid4(), project_id=cls.PROJECT_ID, org_level_id=district.org_level_id,
            parent_org_unit_id=root.org_unit_id, unit_code="SOL", unit_name="Solan", path="HP.SOL",
            is_active=True,
        )
        db.session.add(cls.unit)

        cls.interviewer = cls._get_or_make_user("prefill.interviewer@test.local", "Prefill12345")
        cls.interviewer.name = "Meera Thakur"
        db.session.add(VaUserAccessGrants(
            user_id=cls.interviewer.user_id, role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project, project_id=cls.PROJECT_ID,
            notes="prefill test grant", grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.interviewer.name = "Meera Thakur"
        # The interview year is read in the interviewer's timezone.
        this_year = intake_svc._expression_now(self.interviewer, datetime.now(UTC)).year
        self.interviewer.year_of_birth = this_year - 40
        self.interviewer.sex = "female"

    # ── helpers ────────────────────────────────────────────────────────────

    def _register(self, **overrides):
        fields = {
            "deceased_name": "Ram Kumar Sharma",
            "deceased_sex": "male",
            "date_of_death": (date.today() - timedelta(days=10)).isoformat(),
            "age_years": 64,
            "place_of_death": "Home",
            "address_village_ward": "Kandaghat",
            "address": "Near the temple",
            "informant_name": "Sita Sharma",
            "father_name": "Mohan Lal",
            "mother_name": "Kamla Devi",
        }
        fields.update(overrides)
        return intake_svc.register_death(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            org_unit_id=str(self.unit.org_unit_id), **fields,
        )

    def _start(self, death=None):
        return intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            org_unit_id=str(self.unit.org_unit_id), death_id=death.death_id if death else None,
        )

    # ── registered case: every row of the map ─────────────────────────────

    def test_device_case_rows_batch_prefill_matches_the_web_form(self):
        """The device download resolves presets and org paths for a whole
        page at once (digitva-kmk.4); each case's prefill must still be the
        one the web form gets, inherited presets included."""
        from app.models.mas_organization import MapOrgUnitVaPresets

        root_id = self.unit.parent_org_unit_id
        db.session.add_all([
            MapOrgUnitVaPresets(org_unit_id=root_id, hiv_mortality="high"),
            MapOrgUnitVaPresets(org_unit_id=self.unit.org_unit_id, malaria_mortality="low"),
        ])
        db.session.flush()
        first, second = self._register(), self._register(deceased_name="Asha Devi", deceased_sex="female")
        root_case = intake_svc.register_death(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, org_unit_id=str(root_id),
            deceased_name="Root Case", deceased_sex="male",
            date_of_death=(date.today() - timedelta(days=3)).isoformat(),
        )
        rows = intake_svc.device_case_rows(
            self.interviewer, [(first, "Solan", None), (second, "Solan", None), (root_case, "Himachal Pradesh", None)]
        )
        for death, row in zip((first, second, root_case), rows, strict=True):
            self.assertEqual(row["prefill"], intake_svc._prefill_from_death(death, self.interviewer, death.org_unit_id))
        prefill = rows[0]["prefill"]
        self.assertEqual((prefill["answers"]["Id10002"], prefill["answers"]["Id10003"]), ("high", "low"))
        self.assertTrue({"Id10002", "Id10003"} <= set(prefill["lockedQuestionNames"]))
        self.assertTrue(prefill["answers"]["Id10057"].startswith("Himachal Pradesh, Solan"))
        self.assertEqual(rows[2]["prefill"]["answers"]["Id10002"], "high")
        self.assertNotIn("Id10003", rows[2]["prefill"]["answers"])

    def test_registered_case_prefills_every_map_row(self):
        prefill = self._start(self._register()).prefill
        deceased, answers = prefill["deceased"], prefill["answers"]

        # Id10017/Id10018: first word given name, the rest surname.
        self.assertEqual((deceased["givenNames"], deceased["surname"]), ("Ram", "Kumar Sharma"))
        self.assertEqual(deceased["sex"], "male")  # Id10019
        self.assertEqual(deceased["ageInYears"], 64)  # age_group adult + age_adult
        self.assertNotIn("dateOfBirth", deceased)
        self.assertEqual(deceased["dateOfDeath"], (date.today() - timedelta(days=10)).isoformat())
        self.assertEqual(answers["Id10058"], "home")
        self.assertEqual(answers["Id10057"], "Himachal Pradesh, Solan; Kandaghat, Near the temple")
        self.assertEqual(answers["Id10055"], "Kandaghat, Near the temple")
        self.assertEqual(answers["Id10051"], "yes")
        self.assertEqual(answers["Id10007"], "Sita Sharma")
        self.assertEqual(answers["Id10061"], "Mohan Lal")
        self.assertEqual(answers["Id10062"], "Kamla Devi")
        self.assertEqual(prefill["interviewer"], {
            "name": "Meera Thakur", "id": str(self.interviewer.user_id), "sex": "female",
        })

    def test_only_interviewer_presets_abha_and_age_are_locked(self):
        prefill = self._start(self._register(abha_number="12345678901234")).prefill
        self.assertEqual(set(prefill["lockedQuestionNames"]), INTERVIEWER_LOCKS | ADULT_AGE_LOCKS | {"abha_number"})
        for editable in ("Id10007", "Id10051", "Id10055", "Id10057", "Id10058", "Id10061", "Id10062"):
            self.assertIn(editable, prefill["answers"])
            self.assertNotIn(editable, prefill["lockedQuestionNames"])

    def test_date_of_birth_wins_over_age(self):
        dob = (date.today() - timedelta(days=365 * 30)).isoformat()
        deceased = self._start(self._register(date_of_birth=dob)).prefill["deceased"]
        self.assertEqual(deceased["dateOfBirth"], dob)
        self.assertNotIn("ageInYears", deceased)

    def test_child_age_goes_to_the_child_age_fields(self):
        prefill = self._start(self._register(age_years=5)).prefill
        self.assertNotIn("ageInYears", prefill["deceased"])
        self.assertEqual(
            {k: prefill["answers"][k] for k in ("Id10020", "age_group", "age_child_unit", "age_child_years")},
            {"Id10020": "no", "age_group": "child", "age_child_unit": "years", "age_child_years": 5},
        )
        self.assertTrue({"age_group", "age_child_unit", "age_child_years"} <= set(prefill["lockedQuestionNames"]))
        self.assertNotIn("Id10020", prefill["lockedQuestionNames"])

    def test_age_zero_is_not_prefilled(self):
        prefill = self._start(self._register(age_years=0)).prefill
        self.assertIn("deceased", prefill)
        self.assertNotIn("ageInYears", prefill["deceased"])
        self.assertNotIn("age_group", prefill["answers"])

    def test_missing_optional_fields_are_not_prefilled(self):
        prefill = self._start(self._register(
            place_of_death="", address_village_ward="", address="", informant_name="",
            father_name="", mother_name="",
        )).prefill
        answers = prefill["answers"]
        for absent in ("Id10058", "Id10007", "Id10061", "Id10062"):
            self.assertNotIn(absent, answers)
        # No address: the residence falls back to the org path.
        self.assertEqual(answers["Id10057"], "Himachal Pradesh, Solan")
        self.assertEqual(answers["Id10055"], "Himachal Pradesh, Solan")

    # ── direct start ───────────────────────────────────────────────────────

    def test_direct_start_prefills_the_org_path_and_interviewer_only(self):
        prefill = self._start().prefill
        self.assertNotIn("deceased", prefill)
        self.assertEqual(prefill["answers"], {
            "Id10057": "Himachal Pradesh, Solan",
            "Id10055": "Himachal Pradesh, Solan",
            "Id10051": "yes",
        })
        self.assertEqual(set(prefill["lockedQuestionNames"]), INTERVIEWER_LOCKS)

    def test_prefill_applies_once_when_the_draft_is_created(self):
        death = self._register()
        draft = self._start(death)
        self.interviewer.sex = None
        self.assertEqual(self._start(death).prefill, draft.prefill)
        self.assertEqual(draft.prefill["interviewer"]["sex"], "female")

    # ── parents' names ─────────────────────────────────────────────────────

    def test_parents_names_round_trip_through_the_case(self):
        death = self._register()
        serialized = intake_svc.serialize_death(death)
        self.assertEqual((serialized["father_name"], serialized["mother_name"]), ("Mohan Lal", "Kamla Devi"))
        answers = self._start(death).prefill["answers"]
        self.assertEqual((answers["Id10061"], answers["Id10062"]), ("Mohan Lal", "Kamla Devi"))

    def test_parents_names_are_length_checked(self):
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register(father_name="x" * 201)

    # ── Id10058 mapping ────────────────────────────────────────────────────

    def test_place_of_death_maps_to_who_choices(self):
        cases = {
            "Hospital": "hospital",
            "District Hospital Solan": "hospital",
            "Other health facility": "other_health_facility",
            "PHC Kandaghat": "other_health_facility",
            "nursing home": "other_health_facility",
            "on the way to hospital": "on_route_to_hospital_or_facility",
            "On route to hospital or facility": "on_route_to_hospital_or_facility",
            "at home": "home",
            "other": "other",
            "in the field": None,
            "": None,
            None: None,
        }
        for text, expected in cases.items():
            self.assertEqual(intake_svc._who_place_of_death(text), expected, text)

    # ── interviewer sex and lock ───────────────────────────────────────────

    def test_no_profile_sex_leaves_sex_asked(self):
        self.interviewer.sex = None
        prefill = self._start().prefill
        self.assertIn("Id10010c", prefill["lockedQuestionNames"])
        self.assertNotIn("sex", prefill["interviewer"])
        self.assertNotIn("Id10010b", prefill["lockedQuestionNames"])

    def test_name_outside_the_who_constraint_is_not_locked(self):
        self.interviewer.name = "Dr. Meera Thakur"
        prefill = self._start().prefill
        self.assertEqual(prefill["interviewer"]["name"], "Dr. Meera Thakur")
        self.assertIn("Id10010c", prefill["lockedQuestionNames"])
        self.assertNotIn("Id10010", prefill["lockedQuestionNames"])

    def test_set_interviewer_profile_validates(self):
        user = self.interviewer
        user.set_interviewer_profile("1980", "MALE")
        self.assertEqual((user.year_of_birth, user.sex), (1980, "male"))
        user.set_interviewer_profile("", None)
        self.assertEqual((user.year_of_birth, user.sex), (None, None))
        for year, sex in (("abc", None), (1899, None), (datetime.now(UTC).year + 1, None), (None, "other")):
            with self.assertRaises(ValueError):
                user.set_interviewer_profile(year, sex)

    # ── PII registry ───────────────────────────────────────────────────────

    def test_prefilled_personal_fields_are_registered_pii(self):
        from app.services.pii_field_registry import PII_FIELDS

        for field_id in ("Id10007", "Id10010", "Id10010a", "Id10010b", "Id10010c",
                         "Id10017", "Id10018", "Id10055", "Id10057", "Id10061", "Id10062"):
            self.assertIn(field_id, PII_FIELDS)
