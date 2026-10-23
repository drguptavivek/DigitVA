"""Single-form force-resync pages its ODK fetch (digitva-jvgp).

``run_single_form_sync`` fetches and upserts one page at a time, so a form's
records are never all held in memory, and hands the repair-map build only the
``{sid: KEY}`` map. The form is still one transaction: one commit after the
last page, and a failure on any page leaves nothing of the earlier pages.
"""

import gc
import weakref
from contextlib import ExitStack
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import VaSubmissions, VaSyncRun
from app.tasks.sync_tasks import run_single_form_sync
from tests.base import BaseTestCase
from tests.services.test_national_id_sync_rerun import create_form

UPDATED_AT = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
SYNC_MODULE = "app.services.va_data_sync.va_data_sync_01_odkcentral"
TASKS = "app.tasks.sync_tasks"


class _Record(dict):
    """A record that can be weakly referenced, to see whether a fetched page is retained."""


def _record(form_id: str, instance_id: str) -> _Record:
    return _Record(
        {
            "KEY": instance_id,
            "sid": f"{instance_id}-{form_id.lower()}",
            "form_def": form_id,
            "SubmissionDate": UPDATED_AT.isoformat(),
            "updatedAt": UPDATED_AT.isoformat(),
            "SubmitterName": "Collector",
            "ReviewState": None,
            "instanceName": instance_id,
            "unique_id": instance_id,
            "unique_id2": f"{instance_id}-masked",
            "Id10013": "yes",
            "language": "English",
            "finalAgeInYears": "52",
            "Id10019": "female",
        }
    )


class SingleFormSyncPagingTests(BaseTestCase):
    PROJECT_ID = "JVGP1"
    SITE_ID = "JV01"
    FORM_ID = "JVGP1JV0101"
    PAGE = 3

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_form(cls.PROJECT_ID, cls.SITE_ID, cls.FORM_ID)

    def _run(self, *, total=8, real_upsert=False, page_two_error=None, page_counts=None):
        events: list = []
        refs: list = []  # weakrefs to every fetched record
        upsert_amended: list = []  # the amended_sids object each upsert call received
        build_calls: list = []
        seen_before_failure: list = []
        real_commit = db.session.commit

        def fake_fetch(va_form, *, since, skip, client):
            events.append(("fetch", skip))
            self.assertIsNone(since)
            if page_two_error is not None and skip == self.PAGE:
                seen_before_failure.append(self._form_rows())
                raise page_two_error
            page = [
                _record(self.FORM_ID, f"uuid:jvgp-{i:02d}")
                for i in range(skip, min(skip + self.PAGE, total))
            ]
            refs.extend(weakref.ref(record) for record in page)
            return page

        def fake_upsert(va_form, records, amended_sids, upserted_map=None, **kwargs):
            events.append(("upsert", len(records)))
            self.assertIs(kwargs.get("enrich_payloads"), False)
            self.assertIs(kwargs.get("defer_protected_updates"), True)
            upsert_amended.append(amended_sids)
            for record in records:
                amended_sids.add(record["sid"])
                upserted_map[record["sid"]] = record["KEY"]
            return page_counts(len(records)) if page_counts else (len(records), 0, 0, 0)

        def fake_build(form_id, instance_ids_by_sid, upserted_map, **kwargs):
            events.append(("build",))
            gc.collect()
            build_calls.append(
                SimpleNamespace(
                    instance_ids_by_sid=instance_ids_by_sid,
                    upserted_map=dict(upserted_map),
                    alive=[ref() is not None for ref in refs],
                )
            )
            return {}, {}

        def counting_commit():
            events.append(("commit",))
            return real_commit()

        form_mapping = SimpleNamespace(last_synced_at=None, org_unit_id=None, odk_project_id=98)
        with ExitStack() as stack:
            for target, kwargs in (
                (f"{TASKS}._get_single_form_odk_client", {"return_value": object()}),
                (f"{TASKS}._authorize_data_manager_form_sync", {}),
                (f"{TASKS}._prepare_run_for_canonical_repair", {}),
                (f"{TASKS}.run_canonical_repair_batches_task.delay", {}),
                (f"{TASKS}.finalize_canonical_repair_run_task.delay", {}),
                (f"{TASKS}._build_repair_map_for_form", {"new": fake_build}),
                ("app.utils.va_odk_fetch_submissions_page", {"new": fake_fetch}),
                ("app.utils.va_odk_fetch_instance_ids", {"return_value": []}),
                (f"{SYNC_MODULE}._mark_form_sync_issues", {}),
                (f"{SYNC_MODULE}._ODK_FETCH_PAGE_SIZE", {"new": self.PAGE}),
                (
                    "app.services.runtime_form_sync_service.get_active_mapping_for_form",
                    {"return_value": form_mapping},
                ),
                *(() if real_upsert else ((f"{SYNC_MODULE}._upsert_form_submissions", {"new": fake_upsert}),)),
            ):
                stack.enter_context(patch(target, **kwargs))
            stack.enter_context(patch.object(db.session, "commit", side_effect=counting_commit))
            error = None
            try:
                run_single_form_sync.run(self.FORM_ID, triggered_by="manual", user_id=None)
            except Exception as exc:  # the failure test asserts on it
                error = exc
        sync_run = db.session.scalar(
            sa.select(VaSyncRun).order_by(VaSyncRun.started_at.desc()).limit(1)
        )
        return SimpleNamespace(
            events=events, refs=refs, upsert_amended=upsert_amended, build_calls=build_calls,
            seen_before_failure=seen_before_failure, sync_run=sync_run, error=error,
        )

    def _form_rows(self) -> int:
        return db.session.scalar(
            sa.select(sa.func.count()).select_from(VaSubmissions).where(
                VaSubmissions.va_form_id == self.FORM_ID
            )
        )

    def test_each_page_is_upserted_before_the_next_is_fetched_and_the_form_commits_once(self):
        run = self._run()

        self.assertIsNone(run.error)
        # The VaSyncRun creation commit comes first; none between pages.
        self.assertEqual(
            run.events[:9],
            [
                ("commit",),
                ("fetch", 0), ("upsert", 3),
                ("fetch", 3), ("upsert", 3),
                ("fetch", 6), ("upsert", 2),
                ("commit",), ("build",),
            ],
        )

    def test_one_amended_sids_set_is_shared_across_pages(self):
        run = self._run()

        self.assertEqual(len(run.upsert_amended), 3)
        self.assertIs(run.upsert_amended[0], run.upsert_amended[1])
        self.assertIs(run.upsert_amended[0], run.upsert_amended[2])

    def test_no_fetched_page_is_kept_when_the_repair_map_is_built(self):
        run = self._run()

        build = run.build_calls[0]
        self.assertEqual(len(build.alive), 8)
        self.assertEqual(build.alive, [False] * 8)
        self.assertIs(type(build.instance_ids_by_sid), dict)
        self.assertEqual(
            build.instance_ids_by_sid,
            {f"uuid:jvgp-{i:02d}-{self.FORM_ID.lower()}": f"uuid:jvgp-{i:02d}" for i in range(8)},
        )
        self.assertEqual(build.upserted_map, build.instance_ids_by_sid)

    def test_counts_are_summed_across_pages(self):
        run = self._run(page_counts=lambda n: (n, 1, 2, 3))

        self.assertEqual(run.sync_run.records_added, 8)
        self.assertEqual(run.sync_run.records_updated, 3)
        self.assertEqual(run.sync_run.status, "success")

    def test_a_full_last_page_costs_one_extra_empty_fetch(self):
        run = self._run(total=6)

        self.assertEqual(
            [e for e in run.events if e[0] in ("fetch", "upsert")],
            [("fetch", 0), ("upsert", 3), ("fetch", 3), ("upsert", 3), ("fetch", 6)],
        )
        self.assertEqual(run.sync_run.records_added, 6)

    def test_a_failing_later_page_leaves_nothing_of_the_earlier_pages(self):
        self.assertEqual(self._form_rows(), 0)

        run = self._run(real_upsert=True, page_two_error=ValueError("malformed OData page"))

        # Page 1 really was written before page 2 failed...
        self.assertEqual(run.seen_before_failure, [self.PAGE])
        self.assertIsInstance(run.error, ValueError)
        # ...and none of it survives; the only commits are the run's creation and
        # its error status.
        self.assertEqual(self._form_rows(), 0)
        self.assertEqual(run.sync_run.status, "error")
        self.assertEqual([e for e in run.events if e[0] == "build"], [])
        self.assertEqual(run.events.count(("commit",)), 2)
        self.assertEqual(run.events.index(("commit",)), 0)
