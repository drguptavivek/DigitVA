"""ODK-only interviews get a death-register case in tree projects (digitva-l8y3).

Rules live in app/services/odk_case_service.py; policy in docs/policy/web-intake.md,
"Cases for ODK-only interviews". Reuses the routing fixtures (one tree project,
one ODK form, one site) from tests/test_org_unit_routing.py.
"""
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    MapCaseTransition,
    VaDeathRegister,
    VaForms,
    VaSubmissions,
    VaUsers,
    VaWebIntakeDraft,
)
from app.models.va_users import load_user
from app.services import area_dashboard_service as dashboard
from app.services import odk_case_service as odk_cases
from app.services import org_unit_routing_service as routing
from app.services.va_data_sync.va_data_sync_01_odkcentral import _upsert_form_submissions
from tests.base import BaseTestCase
from tests.test_org_unit_routing import OrgUnitRoutingFixtureMixin


class OdkCaseFixtureMixin(OrgUnitRoutingFixtureMixin):
    def setUp(self):
        super().setUp()
        self._clear_cases()

    def _clear_cases(self):
        db.session.execute(sa.delete(MapCaseTransition).where(
            MapCaseTransition.death_id.in_(
                sa.select(VaDeathRegister.death_id).where(VaDeathRegister.project_id == self.PROJECT)
            )
        ))
        db.session.execute(sa.delete(VaDeathRegister).where(VaDeathRegister.project_id == self.PROJECT))
        db.session.commit()

    def _record(self, instance_id, *, identity=True, **extras):
        now = datetime.now(UTC)
        record = {
            "KEY": instance_id,
            "sid": f"{instance_id}-{self.FORM_ID.lower()}",
            "form_def": self.FORM_ID,
            "SubmissionDate": now.isoformat(),
            "updatedAt": now.isoformat(),
            "SubmitterName": "Collector",
            "ReviewState": "hasIssues",
            "instanceName": instance_id,
            "unique_id": instance_id,
            "unique_id2": f"{instance_id}-masked",
            "Id10013": "yes",
            "language": "English",
            "finalAgeInYears": "42",
            "isNeonatal": "0",
            "isChild": "0",
            "isAdult": "1",
        }
        if identity:
            record.update({
                "Id10017": "Asha",
                "Id10018": "Devi",
                "Id10019": "female",
                "Id10023": "2026-01-10",
            })
        record.update(extras)
        return record

    def _sid(self, instance_id):
        return f"{instance_id}-{self.FORM_ID.lower()}"

    def _sync(self, records):
        amended = set()
        result = _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID), records, amended, {}, enrich_payloads=False,
        )
        db.session.commit()
        return result

    def _odk_cases(self, va_sid):
        return db.session.scalars(
            sa.select(VaDeathRegister).where(VaDeathRegister.va_sid == va_sid)
        ).all()


class OdkCaseCreationTests(OdkCaseFixtureMixin, BaseTestCase):

    def test_odk_only_interview_gets_one_submitted_case(self):
        _, _, phc = self._tree()
        self._mapping()
        sid = self._sid("uuid:odk-case-new")
        self._sync([self._record("uuid:odk-case-new", org_phc_code="P01")])

        (case,) = self._odk_cases(sid)
        self.assertEqual(case.source, "odk")
        self.assertEqual(case.status, "submitted")
        self.assertEqual(case.deceased_name, "Asha Devi")
        self.assertEqual(case.deceased_sex, "female")
        self.assertEqual(case.org_unit_id, phc.org_unit_id)
        self.assertEqual(case.site_id, self.SITE)
        self.assertEqual(case.project_id, self.PROJECT)
        self.assertEqual(case.registered_by, odk_cases.ODK_SYNC_USER_ID)
        self.assertTrue(case.unique_id.startswith(phc.unit_code + "-"))
        (audit,) = db.session.scalars(
            sa.select(MapCaseTransition).where(MapCaseTransition.death_id == case.death_id)
        ).all()
        self.assertEqual((audit.action, audit.from_state, audit.to_state), ("created", None, "submitted"))
        self.assertEqual(audit.actor_user_id, odk_cases.ODK_SYNC_USER_ID)

    def test_rerun_of_the_sync_creates_nothing_new(self):
        self._tree()
        self._mapping()
        sid = self._sid("uuid:odk-case-rerun")
        record = self._record("uuid:odk-case-rerun", org_phc_code="P01")
        self._sync([record])
        self._sync([self._record("uuid:odk-case-rerun", org_phc_code="P01", finalAgeInYears="43")])

        self.assertEqual(len(self._odk_cases(sid)), 1)

    def test_project_without_a_tree_creates_no_case(self):
        self._mapping()
        sid = self._sid("uuid:odk-case-sites")
        self._sync([self._record("uuid:odk-case-sites")])

        self.assertEqual(self._odk_cases(sid), [])

    def test_year_of_death_only_gives_a_case_dated_1_july(self):
        self._tree()
        self._mapping()
        sid = self._sid("uuid:odk-case-year")
        self._sync([self._record(
            "uuid:odk-case-year", org_phc_code="P01", Id10023="", Id10022="no", Id10024="2025-01-01",
        )])

        (case,) = self._odk_cases(sid)
        self.assertEqual(case.date_of_death, date(2025, 7, 1))

    def test_missing_identity_creates_no_case(self):
        self._tree()
        self._mapping()
        sid = self._sid("uuid:odk-case-noid")
        self._sync([self._record("uuid:odk-case-noid", identity=False, org_phc_code="P01")])

        self.assertIsNotNone(db.session.get(VaSubmissions, sid))
        self.assertEqual(self._odk_cases(sid), [])

    def test_an_existing_case_for_the_submission_is_kept(self):
        self._tree()
        self._mapping()
        sid = self._sid("uuid:odk-case-existing")
        self._sync([self._record("uuid:odk-case-existing", identity=False, org_phc_code="P01")])
        db.session.add(VaDeathRegister(
            project_id=self.PROJECT, site_id=self.SITE, death_number=987001,
            unique_id=f"{self.SITE}-987001", va_sid=sid, registered_by=self.base_admin_user.user_id,
            source="register", status="registered", deceased_name="Web Case",
            deceased_sex="male", date_of_death=datetime.now(UTC).date(),
        ))
        db.session.commit()

        self._sync([self._record("uuid:odk-case-existing", org_phc_code="P01")])

        (case,) = self._odk_cases(sid)
        self.assertEqual(case.source, "register")

    def test_a_non_odk_form_creates_no_case(self):
        web_form = SimpleNamespace(form_source="web", project_id=self.PROJECT, site_id=self.SITE)
        submission = db.session.get(VaSubmissions, self._sid("uuid:odk-case-web"))
        self.assertIsNone(
            odk_cases.ensure_case_for_odk_submission(submission, web_form, self._record("x"))
        )

    def test_a_lost_race_on_the_unique_index_keeps_the_batch(self):
        self._tree()
        self._mapping()
        sid = self._sid("uuid:odk-case-race")
        record = self._record("uuid:odk-case-race", identity=False, org_phc_code="P01")
        self._sync([record])
        submission = db.session.get(VaSubmissions, sid)
        form = db.session.get(VaForms, self.FORM_ID)
        identity = {
            "deceased_name": "A", "deceased_sex": "male", "date_of_death": datetime.now(UTC).date(),
        }
        # Another run inserts the case after this run's existence check.
        with db.session.begin_nested():
            odk_cases._insert_case(
                va_sid=sid, org_unit_id=submission.org_unit_id, project_id=self.PROJECT,
                site_id=self.SITE, payload={}, identity=identity,
            )
        db.session.commit()

        with patch.object(odk_cases, "_has_case_or_draft", return_value=False), \
                self.assertLogs(odk_cases.log, level="INFO") as logs:
            second = odk_cases.ensure_case_for_odk_submission(submission, form, self._record(sid))

        self.assertIsNone(second)
        self.assertEqual(len(self._odk_cases(sid)), 1)
        self.assertTrue(any("ODK case not created" in line for line in logs.output))

    def test_a_case_failure_does_not_block_the_form_sync(self):
        self._tree()
        self._mapping()
        real_allocate = odk_cases._allocate_unique_id
        calls = []

        def fail_first(unit_code):
            calls.append(unit_code)
            if len(calls) == 1:
                raise RuntimeError("counter unavailable")
            return real_allocate(unit_code)

        records = [self._record(f"uuid:odk-fail-{n}", org_phc_code="P01") for n in "abc"]
        sids = [self._sid(record["KEY"]) for record in records]
        with patch.object(odk_cases, "_allocate_unique_id", side_effect=fail_first), \
                self.assertLogs(odk_cases.log, level="WARNING") as logs:
            added, *_ = self._sync(records)

        self.assertEqual(added, 3)
        for sid in sids:
            self.assertIsNotNone(db.session.get(VaSubmissions, sid))
        missing = [sid for sid in sids if not self._odk_cases(sid)]
        self.assertEqual(len(missing), 1)
        self.assertEqual(sum(len(self._odk_cases(sid)) for sid in sids), 2)
        self.assertTrue(any(f"va_sid={missing[0]} " in line for line in logs.output))
        self.assertFalse(any("Asha" in line or "Devi" in line for line in logs.output))

    def test_a_backfill_failure_is_counted_and_the_rest_still_get_cases(self):
        self._tree()
        self._mapping()
        self._sync([
            self._record("uuid:odk-bf-fail-a", org_phc_code="P01"),
            self._record("uuid:odk-bf-fail-b", org_phc_code="P01"),
        ])
        self._clear_cases()
        real_allocate = odk_cases._allocate_unique_id
        calls = []

        def fail_first(unit_code):
            calls.append(unit_code)
            if len(calls) == 1:
                raise RuntimeError("counter unavailable")
            return real_allocate(unit_code)

        with patch.object(odk_cases, "_allocate_unique_id", side_effect=fail_first), \
                self.assertLogs(odk_cases.log, level="WARNING"):
            counts = odk_cases.backfill_odk_cases(project_id=self.PROJECT)

        self.assertEqual(counts["failed"], 1)
        self.assertEqual(counts["created"], 1)

    def test_the_death_is_counted_in_deaths_reported(self):
        self._tree()
        self._mapping()
        self._sync([self._record("uuid:odk-case-count", org_phc_code="P01")])

        counts = dashboard._case_counts_by_site(self.PROJECT, [self.SITE])
        self.assertEqual(counts[self.SITE]["deaths_reported"], 1)


class OdkCaseUnitTests(OdkCaseFixtureMixin, BaseTestCase):
    """The ODK case follows its submission's unit; an app case does not."""

    def _area_counts(self, phc, district):
        """Reported deaths: unrouted, and per unit subtree for the PHC and its district."""
        by_unit = dashboard._case_counts_by_unit(self.PROJECT, [phc.org_unit_id, district.org_unit_id])
        return (
            dashboard._case_counts_unrouted(self.PROJECT)["deaths_reported"],
            {unit_id: counts["deaths_reported"] for unit_id, counts in by_unit.items()},
        )

    def test_unrouted_odk_va_gets_a_case_with_no_unit_counted_as_unrouted(self):
        district, _, phc = self._tree()
        self._mapping()
        sid = self._sid("uuid:odk-unit-unrouted")
        self._sync([self._record("uuid:odk-unit-unrouted")])

        (case,) = self._odk_cases(sid)
        self.assertIsNone(case.org_unit_id)
        self.assertTrue(case.unique_id.startswith(self.SITE + "-"))
        unrouted, by_unit = self._area_counts(phc, district)
        self.assertEqual(unrouted, 1)
        self.assertEqual(by_unit, {})

    def test_a_dm_pin_moves_the_odk_case_and_its_area_count(self):
        district, _, phc = self._tree()
        self._mapping()
        sid = self._sid("uuid:odk-unit-pin")
        self._sync([self._record("uuid:odk-unit-pin")])
        submission = db.session.get(VaSubmissions, sid)

        routing.pin_submission_org_unit(
            submission, phc.org_unit_id,
            actor_user_id=self.base_admin_user.user_id, project_id=self.PROJECT,
        )
        db.session.commit()

        (case,) = self._odk_cases(sid)
        self.assertEqual(case.org_unit_id, phc.org_unit_id)
        self.assertTrue(case.unique_id.startswith(self.SITE + "-"))
        unrouted, by_unit = self._area_counts(phc, district)
        self.assertEqual(unrouted, 0)
        self.assertEqual(by_unit.get(phc.org_unit_id), 1)
        self.assertEqual(by_unit.get(district.org_unit_id), 1)

    def test_a_later_sync_reroute_moves_the_odk_case(self):
        _, _, phc = self._tree()
        self._mapping()
        sid = self._sid("uuid:odk-unit-reroute")
        self._sync([self._record("uuid:odk-unit-reroute")])
        self.assertIsNone(self._odk_cases(sid)[0].org_unit_id)

        self._sync([self._record("uuid:odk-unit-reroute", org_phc_code="P01")])

        (case,) = self._odk_cases(sid)
        self.assertEqual(case.org_unit_id, phc.org_unit_id)

    def test_a_pin_leaves_an_app_case_on_its_own_unit(self):
        district, chc, phc = self._tree()
        self._mapping()
        sid = self._sid("uuid:odk-unit-register")
        self._sync([self._record("uuid:odk-unit-register", identity=False, org_phc_code="P01")])
        db.session.add(VaDeathRegister(
            project_id=self.PROJECT, site_id=self.SITE, org_unit_id=chc.org_unit_id,
            death_number=987002, unique_id=f"{self.SITE}-987002", va_sid=sid,
            registered_by=self.base_admin_user.user_id, source="register", status="registered",
            deceased_name="Web Case", deceased_sex="male", date_of_death=datetime.now(UTC).date(),
        ))
        db.session.commit()

        routing.pin_submission_org_unit(
            db.session.get(VaSubmissions, sid), district.org_unit_id,
            actor_user_id=self.base_admin_user.user_id, project_id=self.PROJECT,
        )
        db.session.commit()

        (case,) = self._odk_cases(sid)
        self.assertEqual(case.source, "register")
        self.assertEqual(case.org_unit_id, chc.org_unit_id)

    def test_an_intake_draft_gets_no_odk_case(self):
        self._tree()
        self._mapping()
        sid = self._sid("uuid:odk-unit-draft")
        self._sync([self._record("uuid:odk-unit-draft", identity=False, org_phc_code="P01")])
        db.session.add(VaWebIntakeDraft(
            project_id=self.PROJECT, site_id=self.SITE, form_id=self.FORM_ID,
            user_id=self.base_admin_user.user_id, unique_id="draft-odk-unit", meta={}, prefill={},
            status="submitted", va_sid=sid,
        ))
        db.session.commit()
        try:
            self._sync([self._record("uuid:odk-unit-draft", org_phc_code="P01")])

            self.assertIsNotNone(db.session.get(VaSubmissions, sid))
            self.assertEqual(self._odk_cases(sid), [])
        finally:
            # The draft's va_sid is a foreign key: remove it before the next test's setUp deletes submissions.
            db.session.execute(sa.delete(VaWebIntakeDraft).where(VaWebIntakeDraft.va_sid == sid))
            db.session.commit()


class OdkCaseBackfillTests(OdkCaseFixtureMixin, BaseTestCase):

    def test_dry_run_writes_nothing_and_a_real_run_is_idempotent(self):
        self._tree()
        self._mapping()
        self._sync([
            self._record("uuid:odk-backfill-a", identity=False, org_phc_code="P01"),
            self._record("uuid:odk-backfill-b", org_phc_code="P01"),
        ])
        # Both submissions had no case yet: the sync created b's; remove it to
        # simulate an arrival from before the feature.
        self._clear_cases()

        dry = odk_cases.backfill_odk_cases(project_id=self.PROJECT, dry_run=True)
        self.assertEqual(dry["created"], 1)
        self.assertEqual(dry["identity_missing"], 1)
        self.assertEqual(self._odk_cases(self._sid("uuid:odk-backfill-b")), [])

        real = odk_cases.backfill_odk_cases(project_id=self.PROJECT)
        self.assertEqual(real["created"], 1)
        self.assertEqual(len(self._odk_cases(self._sid("uuid:odk-backfill-b"))), 1)

        again = odk_cases.backfill_odk_cases(project_id=self.PROJECT)
        self.assertEqual(again["created"], 0)
        self.assertEqual(again["linked"], 1)
        self.assertEqual(len(self._odk_cases(self._sid("uuid:odk-backfill-b"))), 1)


class OdkCaseAccountTests(BaseTestCase):

    def test_the_odk_sync_account_cannot_sign_in(self):
        account = db.session.get(VaUsers, odk_cases.ODK_SYNC_USER_ID)
        self.assertIsNotNone(account)
        self.assertFalse(account.is_active)
        self.assertFalse(account.check_password("!"))
        self.assertFalse(account.check_password(""))
        self.assertIsNone(load_user(str(odk_cases.ODK_SYNC_USER_ID)))

    def test_the_odk_sync_account_cannot_sign_in_through_the_password_route(self):
        account = db.session.get(VaUsers, odk_cases.ODK_SYNC_USER_ID)
        self.assertIsNotNone(account)
        limiter.reset()
        # The email step's validator rejects this .invalid address, so step 2 is
        # reached from its preauth state, as tests/test_two_step_login.py does.
        with self.client.session_transaction() as sess:
            sess["preauth"] = {
                "email": account.email,
                "issued_at": datetime.now(UTC).isoformat(),
                "next": None,
            }

        resp = self.client.post(
            "/vaauth/valogin/password",
            data={"password": "!"},
            headers=self._csrf_headers(),
            follow_redirects=False,
        )

        self.assertEqual(resp.status_code, 302)
        resp = self.client.get(resp.headers["Location"], follow_redirects=True)
        self.assertIn(b"Invalid email or password", resp.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)
