"""SmartVA hiv/malaria options come from the district setting, falling back to
the form flag (bead digitva-cts).

Rules under test: ``_derive_smartva_run_options`` (area preset of the
submission's org unit via the nearest ancestor, then the form flag, then off;
hiv and malaria independently; two queries however many submissions) and
``_generate_batch`` (one SmartVA run per option set, options + source recorded
on each run). Policy: docs/policy/smartva-generation-policy.md.
"""
import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import sqlalchemy as sa

from app import db
from app.models import (
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaSmartvaRun,
    VaStatuses,
    VaSubmissions,
)
from app.services import organization_service as org
from app.services import smartva_service
from app.services.smartva_service import _generate_batch
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.utils.va_smartva.va_smartva_02_prepdata import (
    SOURCE_DEFAULT,
    SOURCE_FORM_FLAG,
    _derive_smartva_run_options,
)
from tests.base import BaseTestCase

_SUFFIX = uuid.uuid4().hex[:4].upper()


class SmartvaRunOptionsTests(BaseTestCase):
    PROJECT = f"SO{_SUFFIX}"
    SITE = "SO01"
    FORM_ID = f"{PROJECT}{SITE}"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for model in (VaProjectMaster, VaResearchProjects):
            db.session.add(model(
                project_id=cls.PROJECT, project_code=cls.PROJECT,
                project_name="SmartVA Options", project_nickname="SvaOpt",
                project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE, site_name="Options Site", site_abbr=cls.SITE,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaSites(
            site_id=cls.SITE, project_id=cls.PROJECT, site_name="Options Site",
            site_abbr=cls.SITE, site_status=VaStatuses.active,
            site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT, site_id=cls.SITE,
            project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.add(VaForms(
            form_id=cls.FORM_ID, project_id=cls.PROJECT, site_id=cls.SITE,
            odk_form_id="SOPT_FORM", odk_project_id="86", form_type="WHO VA 2022",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
            form_smartvahiv="True", form_smartvamalaria="False",
        ))
        db.session.flush()
        # District > CHC > PHC, plus a sibling CHC under the same district.
        org.seed_default_organization(cls.PROJECT)
        lv = {level.level_code: level for level in org.list_levels(cls.PROJECT)}
        cls.district = org.create_unit(
            cls.PROJECT, org_level_id=lv["district"].org_level_id,
            unit_code="D01", unit_name="District",
        )
        cls.chc = org.create_unit(
            cls.PROJECT, org_level_id=lv["chc"].org_level_id,
            parent_org_unit_id=cls.district.org_unit_id, unit_code="C01", unit_name="CHC",
        )
        cls.phc = org.create_unit(
            cls.PROJECT, org_level_id=lv["phc"].org_level_id,
            parent_org_unit_id=cls.chc.org_unit_id, unit_code="P01", unit_name="PHC",
        )
        cls.other_district = org.create_unit(
            cls.PROJECT, org_level_id=lv["district"].org_level_id,
            unit_code="D02", unit_name="Other District",
        )
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.form = db.session.get(VaForms, self.FORM_ID)
        self.form.form_smartvahiv = "True"
        self.form.form_smartvamalaria = "False"

    def _presets(self, unit, hiv, malaria):
        org.set_unit_va_presets(
            self.PROJECT, unit.org_unit_id, hiv_mortality=hiv, malaria_mortality=malaria
        )
        db.session.flush()

    def _submission(self, name, unit=None):
        now = datetime.now(UTC)
        sid = f"uuid:{name}-{_SUFFIX.lower()}-{uuid.uuid4().hex[:6]}"
        sub = VaSubmissions(
            va_sid=sid, va_form_id=self.FORM_ID, va_submission_date=now,
            va_odk_updatedat=now.replace(tzinfo=None), va_data_collector="C",
            va_odk_reviewstate=None, va_consent="yes", va_narration_language="English",
            va_deceased_age=45, va_deceased_gender="male", va_uniqueid_masked="m",
            va_summary=[], va_catcount={}, va_category_list=[],
            org_unit_id=unit.org_unit_id if unit else None,
            org_unit_resolution="mapping_fallback" if unit else None,
        )
        db.session.add(sub)
        db.session.flush()
        ensure_active_payload_version(
            sub, payload_data={"sid": sid, "Id10002": "yes", "Id10003": "yes"},
            source_updated_at=sub.va_odk_updatedat, created_by_role="vasystem",
        )
        return sub.va_sid

    # -- resolution -------------------------------------------------------

    def test_preset_high_is_on_and_low_veryl_are_off(self):
        self._presets(self.phc, "high", "veryl")
        sid = self._submission("own", self.phc)

        got = _derive_smartva_run_options(self.form, {sid})[sid]

        self.assertEqual((got["hiv"], got["malaria"]), ("True", "False"))
        self.assertEqual(got["hiv_source"], str(self.phc.org_unit_id))
        self.assertEqual(got["malaria_source"], str(self.phc.org_unit_id))

    def test_low_preset_overrides_a_true_form_flag(self):
        self._presets(self.phc, "low", None)
        sid = self._submission("low", self.phc)

        got = _derive_smartva_run_options(self.form, {sid})[sid]

        self.assertEqual(got["hiv"], "False")  # form flag is "True"
        self.assertEqual(got["hiv_source"], str(self.phc.org_unit_id))

    def test_inherited_from_ancestor_and_fields_resolve_independently(self):
        self._presets(self.district, None, "high")
        self._presets(self.chc, "low", None)
        sid = self._submission("inherit", self.phc)

        got = _derive_smartva_run_options(self.form, {sid})[sid]

        self.assertEqual((got["hiv"], got["hiv_source"]), ("False", str(self.chc.org_unit_id)))
        self.assertEqual((got["malaria"], got["malaria_source"]), ("True", str(self.district.org_unit_id)))

    def test_unit_without_any_preset_falls_back_to_form_flag(self):
        sid = self._submission("noset", self.other_district)

        got = _derive_smartva_run_options(self.form, {sid})[sid]

        self.assertEqual((got["hiv"], got["hiv_source"]), ("True", SOURCE_FORM_FLAG))
        self.assertEqual((got["malaria"], got["malaria_source"]), ("False", SOURCE_FORM_FLAG))

    def test_one_field_preset_other_field_uses_form_flag(self):
        self._presets(self.other_district, None, "high")
        sid = self._submission("half", self.other_district)

        got = _derive_smartva_run_options(self.form, {sid})[sid]

        self.assertEqual((got["hiv"], got["hiv_source"]), ("True", SOURCE_FORM_FLAG))
        self.assertEqual(got["malaria"], "True")
        self.assertEqual(got["malaria_source"], str(self.other_district.org_unit_id))

    def test_unplaced_submission_uses_form_flag_and_ignores_answers(self):
        sid = self._submission("unplaced")  # payload says Id10003 = yes

        got = _derive_smartva_run_options(self.form, {sid})[sid]

        self.assertEqual((got["hiv"], got["malaria"]), ("True", "False"))
        self.assertEqual(got["malaria_source"], SOURCE_FORM_FLAG)

    def test_invalid_form_flag_is_off_by_default(self):
        sid = self._submission("noflag")
        form = SimpleNamespace(form_smartvahiv="", form_smartvamalaria=None)  # column is NOT NULL

        got = _derive_smartva_run_options(form, {sid})[sid]

        self.assertEqual((got["hiv"], got["hiv_source"]), ("False", SOURCE_DEFAULT))

    def test_empty_request_runs_no_query(self):
        self.assertEqual(_derive_smartva_run_options(self.form, set()), {})

    def test_query_count_is_constant_in_submission_count(self):
        self._presets(self.chc, "high", "low")
        sids = {self._submission(f"bulk{i}", self.phc if i % 2 else self.other_district) for i in range(12)}
        db.session.flush()  # setup writes must not count against the resolver
        statements = []

        def record(conn, cursor, statement, *args):
            statements.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", record)
        try:
            got = _derive_smartva_run_options(self.form, sids)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", record)

        self.assertEqual(len(got), 12)
        self.assertLessEqual(len(statements), 2, statements)

    # -- the run -----------------------------------------------------------

    def _generate(self, sids, run_side_effect=None, extra_patches=()):
        rows = [{
            "sid": sid, "age": 45.0, "sex": "male", "cause1": "Cardiovascular",
            "likelihood1": "High", "key_symptom1": None, "cause2": None,
            "likelihood2": None, "key_symptom2": None, "cause3": None,
            "likelihood3": None, "key_symptom3": None, "all_symptoms": None,
            "result_for": "for_adult", "cause1_icd": "I21", "cause2_icd": None,
            "cause3_icd": None,
        } for sid in sids]
        patches = [
            patch("app.utils.va_smartva_prepdata"),
            patch("app.utils.va_smartva_runsmartva", side_effect=run_side_effect),
            patch("app.services.smartva_service._read_raw_likelihood_outputs", return_value={}),
            patch("app.utils.va_smartva_formatsmartvaresult", return_value="/fake.csv"),
            patch("app.services.smartva_service._read_formatted_results", return_value=pd.DataFrame(rows)),
            patch("app.services.smartva_service._archive_completed_form_run"),
            *extra_patches,
        ]
        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            run = mocks[1]
            saved = _generate_batch(self.form, set(sids))
        return saved, [call.kwargs["run_options"] for call in run.call_args_list]

    def test_mixed_batch_splits_by_option_set_and_records_provenance(self):
        self._presets(self.phc, "low", "high")  # (hiv off, malaria on)
        placed = self._submission("mixed-placed", self.phc)
        unplaced = self._submission("mixed-unplaced")  # form flag: (hiv on, malaria off)
        sibling = self._submission("mixed-sibling", self.other_district)  # same set as unplaced
        db.session.commit()

        saved, options_per_run = self._generate({placed, unplaced, sibling})

        self.assertEqual(saved, 3)
        self.assertCountEqual(
            options_per_run,
            [{"hiv": "False", "malaria": "True"}, {"hiv": "True", "malaria": "False"}],
        )
        runs = {
            run.va_sid: run.run_metadata["smartva_options"]
            for run in db.session.scalars(
                sa.select(VaSmartvaRun).where(VaSmartvaRun.va_sid.in_({placed, unplaced, sibling}))
            )
        }
        unit = str(self.phc.org_unit_id)
        self.assertEqual(runs[placed], {
            "hiv": {"value": "False", "source": unit},
            "malaria": {"value": "True", "source": unit},
        })
        self.assertEqual(runs[unplaced], {
            "hiv": {"value": "True", "source": SOURCE_FORM_FLAG},
            "malaria": {"value": "False", "source": SOURCE_FORM_FLAG},
        })
        self.assertEqual(runs[sibling]["hiv"]["source"], SOURCE_FORM_FLAG)

    def test_uniform_batch_is_a_single_run(self):
        a = self._submission("uni-a")
        b = self._submission("uni-b", self.other_district)
        db.session.commit()

        saved, options_per_run = self._generate({a, b})

        self.assertEqual(saved, 2)
        self.assertEqual(options_per_run, [{"hiv": "True", "malaria": "False"}])

    # -- failures ----------------------------------------------------------

    def _runs(self, sids):
        return {
            run.va_sid: run
            for run in db.session.scalars(
                sa.select(VaSmartvaRun).where(VaSmartvaRun.va_sid.in_(sids))
            )
        }

    def _split_pair(self):
        """One submission per option set: (hiv off, malaria on) vs the form flag."""
        self._presets(self.phc, "low", "high")
        placed = self._submission("split-placed", self.phc)
        unplaced = self._submission("split-unplaced")
        db.session.commit()
        return placed, unplaced

    def test_failed_run_carries_the_options_it_ran_with(self):
        sid = self._submission("fail-meta")
        db.session.commit()

        def boom(*_args, **_kwargs):
            raise RuntimeError("smartva crashed")

        saved, _ = self._generate({sid}, run_side_effect=boom)

        run = self._runs({sid})[sid]
        self.assertEqual(saved, 1)
        self.assertEqual(run.va_smartva_outcome, VaSmartvaRun.OUTCOME_FAILED)
        self.assertEqual(run.va_smartva_failure_stage, "execution")
        self.assertEqual(run.run_metadata["smartva_options"]["hiv"],
                         {"value": "True", "source": SOURCE_FORM_FLAG})

    def test_one_failing_group_does_not_stop_the_other(self):
        placed, unplaced = self._split_pair()

        def fail_for_hiv_off(_form, _dir, run_options=None):
            if run_options["hiv"] == "False":
                raise RuntimeError("smartva crashed")

        saved, options_per_run = self._generate({placed, unplaced}, run_side_effect=fail_for_hiv_off)

        runs = self._runs({placed, unplaced})
        self.assertEqual(saved, 2)  # one failure row + one success row
        self.assertEqual(len(options_per_run), 2)
        self.assertEqual(runs[placed].va_smartva_outcome, VaSmartvaRun.OUTCOME_FAILED)
        self.assertEqual(runs[unplaced].va_smartva_outcome, VaSmartvaRun.OUTCOME_SUCCESS)

    def test_group_error_outside_its_own_handler_is_contained(self):
        placed, unplaced = self._split_pair()
        real = smartva_service._create_smartva_form_run
        calls = []

        def first_call_raises(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("form run insert failed")
            return real(*args, **kwargs)

        saved, _ = self._generate(
            {placed, unplaced},
            extra_patches=[patch("app.services.smartva_service._create_smartva_form_run", first_call_raises)],
        )

        runs = self._runs({placed, unplaced})
        self.assertEqual(saved, 2)
        outcomes = sorted(run.va_smartva_outcome for run in runs.values())
        self.assertEqual(outcomes, [VaSmartvaRun.OUTCOME_FAILED, VaSmartvaRun.OUTCOME_SUCCESS])
        failed = next(r for r in runs.values() if r.va_smartva_outcome == VaSmartvaRun.OUTCOME_FAILED)
        self.assertEqual(failed.va_smartva_failure_stage, "execution")
        self.assertIn("smartva_options", failed.run_metadata)

    def test_resolver_error_is_recorded_as_execution_failures(self):
        a = self._submission("resolver-a")
        b = self._submission("resolver-b")
        db.session.commit()

        saved, options_per_run = self._generate(
            {a, b},
            extra_patches=[patch(
                "app.utils.va_smartva.va_smartva_02_prepdata._derive_smartva_run_options",
                side_effect=RuntimeError("db down"),
            )],
        )

        runs = self._runs({a, b})
        self.assertEqual(saved, 2)
        self.assertEqual(options_per_run, [])  # SmartVA never ran
        for run in runs.values():
            self.assertEqual(run.va_smartva_outcome, VaSmartvaRun.OUTCOME_FAILED)
            self.assertEqual(run.va_smartva_failure_stage, "execution")
