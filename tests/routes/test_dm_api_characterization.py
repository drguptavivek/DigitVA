"""Characterization of the data-manager API before the r8nh.15 refactor.

Pins what /api/v1/data-management/ answers today, so moving the filter
parsing, the typed not-found / not-permitted errors, the sync preview, the
export cache and the unrouted queue into services changes none of it:
status, error code and message, JSON keys, the arguments the routes pass to
the services, and which refusals roll the session back.
"""
from __future__ import annotations

import tempfile
import uuid
from unittest.mock import patch

from app import db, limiter
from tests.authz.fixture import FORMS, TA, AuthzFixtureMixin
from tests.base import BaseTestCase

DM_API = "/api/v1/data-management"

TEXT_FILTERS = (
    "search", "project", "site", "odk_status", "smartva", "age_group", "gender",
    "odk_sync", "workflow", "visit_note", "org_unit",
)
DATE_FILTERS = ("date_from", "date_to", "death_from", "death_to")
ALL_FILTERS = (
    "search", "project", "site", "date_from", "date_to", "death_from", "death_to",
    "odk_status", "smartva", "age_group", "gender", "odk_sync", "workflow",
    "visit_note", "org_unit",
)
NOT_FOUND = {"error": "Submission not found.", "code": "not_found"}
FORBIDDEN = {"error": "You do not have access to this submission.", "code": "forbidden"}


class DmApiCharacterizationTests(AuthzFixtureMixin, BaseTestCase):

    def setUp(self):
        super().setUp()
        limiter.reset()  # sync/preview allows 5 a minute; buckets outlive a test

    def _as(self, key):
        self._login(str(self.user(key).user_id))

    def _post(self, url, json=None):
        return self.client.post(f"{DM_API}{url}", json=json, headers=self._csrf_headers())

    def _unique(self) -> str:
        """A query-string tail that no other request in the session sends,
        so the route's result cache never answers instead of the service."""
        return f"&_={uuid.uuid4().hex}"

    # -- filter parsing ------------------------------------------------------

    def _captured(self, mock):
        self.assertEqual(mock.call_count, 1)
        return mock.call_args.kwargs

    def test_submissions_passes_all_filters_with_defaults_when_missing(self):
        self._as("dm_ta")
        with patch(
            "app.routes.api.data_management.dm_submissions_page", return_value={"rows": []}
        ) as page:
            response = self.client.get(f"{DM_API}/submissions")
        self.assertEqual(response.status_code, 200)
        kwargs = self._captured(page)
        for name in TEXT_FILTERS:
            self.assertEqual(kwargs[name], "", name)
        for name in DATE_FILTERS:
            self.assertIsNone(kwargs[name], name)
        self.assertEqual(
            (kwargs["page"], kwargs["per_page"], kwargs["sort_field"], kwargs["sort_dir"]),
            (1, 25, "va_submission_date", "desc"),
        )

    def test_submissions_keeps_empty_text_and_turns_empty_dates_into_none(self):
        self._as("dm_ta")
        query = "&".join(f"{name}=" for name in ALL_FILTERS)
        with patch(
            "app.routes.api.data_management.dm_submissions_page", return_value={}
        ) as page:
            self.client.get(f"{DM_API}/submissions?{query}")
        kwargs = self._captured(page)
        for name in TEXT_FILTERS:
            self.assertEqual(kwargs[name], "", name)
        for name in DATE_FILTERS:
            self.assertIsNone(kwargs[name], name)

    def test_submissions_passes_values_through_unstripped_and_unvalidated(self):
        self._as("dm_ta")
        with patch(
            "app.routes.api.data_management.dm_submissions_page", return_value={}
        ) as page:
            self.client.get(
                f"{DM_API}/submissions?search=%20x%20&date_from=not-a-date"
                "&death_to=2026-13-40&gender=bogus&org_unit=%20"
            )
        kwargs = self._captured(page)
        self.assertEqual(kwargs["search"], " x ")
        self.assertEqual(kwargs["date_from"], "not-a-date")
        self.assertEqual(kwargs["death_to"], "2026-13-40")
        self.assertEqual(kwargs["gender"], "bogus")
        self.assertEqual(kwargs["org_unit"], " ")

    def test_kpi_passes_every_filter_but_search(self):
        self._as("dm_ta")
        query = "search=s&project=P&date_from=&death_from=d1&smartva=" + self._unique()
        with patch(
            "app.routes.api.data_management.get_dm_kpi_from_mv", return_value={"total": 1}
        ) as kpi:
            response = self.client.get(f"{DM_API}/kpi?{query}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"total": 1})
        kwargs = self._captured(kpi)
        self.assertNotIn("search", kwargs)
        self.assertEqual(
            set(kwargs) - {"unit_ids"}, set(ALL_FILTERS) - {"search"},
        )
        self.assertEqual(kwargs["project"], "P")
        self.assertIsNone(kwargs["date_from"])
        self.assertEqual(kwargs["death_from"], "d1")
        self.assertEqual(kwargs["smartva"], "")

    def test_project_site_submissions_passes_project_apart_and_no_search(self):
        self._as("dm_ta")
        with patch(
            "app.routes.api.data_management.get_dm_project_site_stats_from_mv",
            return_value=[],
        ) as stats:
            response = self.client.get(
                f"{DM_API}/project-site-submissions?search=s&project=P&date_to=&odk_sync=x"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.get_json()), {"group_by", "stats", "timezone"})
        kwargs = self._captured(stats)
        self.assertNotIn("search", kwargs)
        self.assertEqual(
            set(kwargs),
            (set(ALL_FILTERS) - {"search"}) | {"project_ids", "project_site_pairs", "unit_ids"},
        )
        self.assertEqual(kwargs["project"], "P")
        self.assertIsNone(kwargs["date_to"])
        self.assertEqual(kwargs["odk_sync"], "x")

    def test_coder_daily_stats_passes_all_fifteen_filters(self):
        self._as("dm_ta")
        with patch(
            "app.routes.api.data_management.dm_coder_daily_statistics", return_value={"days": []}
        ) as stats:
            response = self.client.get(
                f"{DM_API}/coder-daily-stats?search=q&date_from=&workflow=w{self._unique()}"
            )
        self.assertEqual(response.status_code, 200)
        kwargs = self._captured(stats)
        self.assertEqual(set(kwargs), set(ALL_FILTERS) | {"days"})
        self.assertEqual((kwargs["search"], kwargs["workflow"]), ("q", "w"))
        self.assertIsNone(kwargs["date_from"])
        self.assertEqual(kwargs["days"], 7)

    def _export_twice(self, url):
        calls = []

        def write(out, user, **filters):
            calls.append(filters)
            out.write("a,b\r\n1,2\r\n")

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(self.app.config, {
            "APP_DATA": tmpdir, "DM_EXPORT_CACHE_TTL_SECONDS": 300,
        }), patch(
            "app.routes.api.data_management.write_dm_submissions_export_csv", side_effect=write
        ):
            first = self.client.get(url)
            first_body = first.get_data()
            second = self.client.get(url)
            second.get_data()
        return calls, first, first_body, second

    @patch("app.services.authz.grant_cache.global_version", return_value="test-version")
    def test_export_passes_the_filters_and_caches_miss_then_hit(self, _version):
        self._as("dm_ta")
        calls, first, first_body, second = self._export_twice(
            f"{DM_API}/submissions/export.csv?search=e&date_to={self._unique()}"
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["X-Export-Cache"], "MISS")
        self.assertEqual(first.headers["Cache-Control"], "private, no-store")
        self.assertIn(b"a,b", first_body)
        self.assertEqual(second.headers["X-Export-Cache"], "HIT")
        self.assertEqual(len(calls), 1)
        self.assertEqual(list(calls[0]), list(ALL_FILTERS))
        self.assertEqual(calls[0]["search"], "e")
        self.assertIsNone(calls[0]["date_to"])

    @patch("app.services.authz.grant_cache.global_version", return_value=None)
    def test_export_without_a_grant_version_is_never_served_from_cache(self, _version):
        self._as("dm_ta")
        calls, first, _body, second = self._export_twice(
            f"{DM_API}/submissions/export.csv?search=n{self._unique()}"
        )
        self.assertEqual(
            (first.headers["X-Export-Cache"], second.headers["X-Export-Cache"]), ("MISS", "MISS"),
        )
        self.assertEqual(len(calls), 2)

    def test_export_store_failure_sends_the_csv_inline_as_bypass(self):
        from app.services.export_store_service import ExportStoreError

        self._as("dm_ta")
        url = f"{DM_API}/submissions/export.csv?search=b{self._unique()}"
        with patch(
            "app.routes.api.data_management.write_dm_submissions_export_csv",
            side_effect=lambda out, user, **f: out.write("x\r\n"),
        ), patch(
            "app.services.export_store_service.write_export",
            side_effect=ExportStoreError("down"),
        ):
            response = self.client.get(url)
            body = response.get_data()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Export-Cache"], "BYPASS")
        self.assertEqual(body, b"\xef\xbb\xbfx\r\n")  # UTF-8 BOM, then the CSV
        self.assertEqual(response.content_length, len(body))

    # -- not found vs bad request -------------------------------------------

    def _rollback_spy(self):
        return patch.object(db.session, "rollback", wraps=db.session.rollback)

    def test_collection_hold_unknown_submission_is_404_and_rolls_back(self):
        self._as("dm_ta")
        with self._rollback_spy() as rollback:
            response = self._post("/submissions/no-such-sid/collection-hold/release", {})
        self.assertEqual((response.status_code, response.get_json()), (404, NOT_FOUND))
        self.assertEqual(rollback.call_count, 1)

    def test_collection_hold_out_of_scope_is_403_and_rolls_back(self):
        self._as("dm_ta")
        with self._rollback_spy() as rollback:
            response = self._post("/submissions/sp-1/collection-hold/release", {})
        self.assertEqual((response.status_code, response.get_json()), (403, FORBIDDEN))
        self.assertEqual(rollback.call_count, 1)

    def test_collection_hold_bad_note_is_400_even_for_an_unknown_submission(self):
        self._as("dm_ta")
        response = self._post("/submissions/no-such-sid/collection-hold/reject", {"note": 5})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_request")
        self.assertTrue(response.get_json()["error"].startswith("note must be text"))

    def test_collection_hold_not_held_is_409(self):
        self._as("dm_ta")
        response = self._post("/submissions/ta-d1/collection-hold/release", {})
        self.assertEqual(
            (response.status_code, response.get_json()),
            (409, {"error": "This interview is not held.", "code": "conflict"}),
        )

    def test_collection_hold_unknown_action_is_404(self):
        self._as("dm_ta")
        response = self._post("/submissions/ta-d1/collection-hold/bogus", {})
        self.assertEqual(
            (response.status_code, response.get_json()),
            (404, {"error": "Not found.", "code": "not_found"}),
        )

    def test_cancel_revision_unknown_submission_is_404_without_rollback(self):
        self._as("dm_ta")
        with self._rollback_spy() as rollback:
            response = self._post("/submissions/no-such-sid/cancel-revision-request")
        self.assertEqual((response.status_code, response.get_json()), (404, NOT_FOUND))
        self.assertEqual(rollback.call_count, 0)

    def test_cancel_revision_out_of_scope_is_403_without_rollback(self):
        self._as("dm_ta")
        with self._rollback_spy() as rollback:
            response = self._post("/submissions/sp-1/cancel-revision-request")
        self.assertEqual((response.status_code, response.get_json()), (403, FORBIDDEN))
        self.assertEqual(rollback.call_count, 0)

    def test_cancel_revision_wrong_state_is_400_not_cancellable(self):
        self._as("dm_ta")
        response = self._post("/submissions/ta-d1/cancel-revision-request")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {
            "error": "Submission is in state 'None', not finalized_upstream_changed.",
            "code": "not_cancellable",
        })

    def test_other_actions_answer_an_unknown_submission_with_400(self):
        self._as("dm_ta")
        for action in (
            "accept-upstream-change", "screening-pass", "screening-reject",
            "reject-upstream-change",
        ):
            with self.subTest(action=action):
                response = self._post(f"/submissions/no-such-sid/{action}")
                self.assertEqual(
                    (response.status_code, response.get_json()),
                    (400, {"error": "Submission not found.", "code": "invalid_request"}),
                )

    def test_other_actions_answer_out_of_scope_with_403(self):
        self._as("dm_ta")
        for action in (
            "accept-upstream-change", "screening-pass", "screening-reject",
            "reject-upstream-change",
        ):
            with self.subTest(action=action):
                response = self._post(f"/submissions/sp-1/{action}")
                self.assertEqual((response.status_code, response.get_json()), (403, FORBIDDEN))

    def test_upstream_change_details_unknown_submission_is_404(self):
        self._as("dm_ta")
        response = self.client.get(f"{DM_API}/submissions/no-such-sid/upstream-change-details")
        self.assertEqual((response.status_code, response.get_json()), (404, NOT_FOUND))

    # -- sync preview --------------------------------------------------------

    def _forms(self):
        ta1, _, site1 = FORMS["ta1"]
        ta2, _, site2 = FORMS["ta2"]
        return [
            {"form_id": ta1, "project_id": TA, "site_id": site1, "site_name": "S1",
             "odk_project_id": "95", "odk_form_id": "AZ_F1",
             "last_synced_at": "2026-01-02T03:04:05+00:00"},
            {"form_id": ta2, "project_id": TA, "site_id": site2, "site_name": "S2",
             "odk_project_id": None, "odk_form_id": "AZ_F2", "last_synced_at": None},
        ]

    def _preview(self, body=None, forms=None):
        with patch(
            "app.routes.api.data_management.dm_scoped_forms",
            return_value=self._forms() if forms is None else forms,
        ):
            return self._post("/sync/preview", {"project_ids": [TA]} if body is None else body)

    @patch("app.utils.va_odk_delta_count", return_value=3)
    @patch("app.utils.va_odk_fetch_instance_ids", return_value=["a", "b"])
    @patch("app.utils.va_odk.va_odk_01_clientsetup.va_odk_clientsetup")
    def test_sync_preview_reply(self, clientsetup, fetch, delta):
        clientsetup.return_value = object()
        self._as("dm_ta")
        response = self._preview()
        self.assertEqual(response.status_code, 200, response.get_json())
        ta1, ta2 = FORMS["ta1"][0], FORMS["ta2"][0]
        self.assertEqual(response.get_json(), {
            "totals": {
                "forms": 2, "local_submissions": 8, "odk_submissions": 2,
                "new_fetch_candidates": 2, "missing_in_odk_flags": 7, "updated_candidates": 3,
            },
            "forms": [
                {"form_id": ta1, "project_id": TA, "site_id": "AZS1", "site_name": "S1",
                 "last_synced_at": "2026-01-02T03:04:05+00:00",
                 "local_submissions": 7, "odk_submissions": 2,
                 "new_fetch_candidates": 2, "missing_in_odk_flags": 7,
                 "updated_candidates": 3, "preview_status": "ok"},
                {"form_id": ta2, "project_id": TA, "site_id": "AZS2", "site_name": "S2",
                 "last_synced_at": None,
                 "local_submissions": 1, "odk_submissions": 0,
                 "new_fetch_candidates": 0, "missing_in_odk_flags": 0,
                 "updated_candidates": None, "preview_status": "unmapped"},
            ],
        })
        self.assertEqual(clientsetup.call_count, 1)
        self.assertEqual(clientsetup.call_args.kwargs, {"project_id": TA})
        self.assertEqual(delta.call_args.kwargs["odk_project_id"], 95)

    @patch("app.utils.va_odk_delta_count", side_effect=RuntimeError("odk down"))
    @patch("app.utils.va_odk_fetch_instance_ids", return_value=["a"])
    @patch("app.utils.va_odk.va_odk_01_clientsetup.va_odk_clientsetup", return_value=object())
    def test_sync_preview_delta_failure_leaves_updated_candidates_null(self, *_mocks):
        self._as("dm_ta")
        response = self._preview()
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsNone(payload["forms"][0]["updated_candidates"])
        self.assertEqual(payload["totals"]["updated_candidates"], 0)

    @patch(
        "app.utils.va_odk.va_odk_01_clientsetup.va_odk_clientsetup",
        side_effect=RuntimeError("no connection"),
    )
    def test_sync_preview_odk_failure_is_500(self, _clientsetup):
        self._as("dm_ta")
        response = self._preview()
        self.assertEqual(
            (response.status_code, response.get_json()),
            (500, {"error": "Operation failed. Check server logs.", "code": "server_error"}),
        )

    def test_sync_preview_no_match_is_zero_totals(self):
        self._as("dm_ta")
        response = self._preview({"project_ids": ["NOPE01"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "totals": {
                "forms": 0, "local_submissions": 0, "odk_submissions": 0,
                "new_fetch_candidates": 0, "missing_in_odk_flags": 0, "updated_candidates": 0,
            },
            "forms": [],
        })

    def test_sync_preview_refusals(self):
        self._as("dm_ta")
        bad = self._preview({"project_ids": "TA"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.get_json()["error"], "project_ids and site_ids must be lists of text.")
        not_object = self._preview([1])
        self.assertEqual(
            (not_object.status_code, not_object.get_json()["error"]),
            (400, "A JSON object is required."),
        )
        self._as("dm_c1")
        unit_only = self._preview()
        self.assertEqual(
            (unit_only.status_code, unit_only.get_json()),
            (403, {"error": "Form sync requires a project or site grant.", "code": "forbidden"}),
        )

    # -- unrouted queue and pinning -----------------------------------------

    def test_unrouted_queue_reply_shape(self):
        self._as("dm_ta")
        response = self.client.get(f"{DM_API}/submissions/unrouted?include=unrouted")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(set(payload), {"submissions", "truncated", "limit"})
        self.assertEqual((payload["truncated"], payload["limit"]), (False, 200))
        rows = {row["va_sid"]: row for row in payload["submissions"]}
        self.assertIn("ta-unr", rows)
        self.assertEqual(set(rows["ta-unr"]), {
            "va_sid", "submission_date", "data_collector", "project_id", "site_id",
            "resolution", "unit_code", "unit_name",
        })
        self.assertEqual(
            (rows["ta-unr"]["project_id"], rows["ta-unr"]["site_id"],
             rows["ta-unr"]["resolution"], rows["ta-unr"]["unit_code"]),
            (TA, "AZS1", None, None),
        )

    def test_unrouted_queue_masks_the_collector_by_pii_scope(self):
        from app.services.viewer_pii_service import pii_scope

        self._as("dm_ta")
        response = self.client.get(f"{DM_API}/submissions/unrouted?project={TA}")
        rows = {row["va_sid"]: row for row in response.get_json()["submissions"]}
        self.assertIn("ta-unr", rows)
        sees = pii_scope(self.user("dm_ta")).sees(TA)
        self.assertEqual(rows["ta-unr"]["data_collector"], "Collector" if sees else None)

    def test_unrouted_queue_rejects_an_unknown_include(self):
        self._as("dm_ta")
        response = self.client.get(f"{DM_API}/submissions/unrouted?include=all")
        self.assertEqual(
            (response.status_code, response.get_json()),
            (400, {"error": "include must be 'fallback' or 'unrouted'.", "code": "invalid_request"}),
        )

    def test_pin_and_clear_replies(self):
        self._as("dm_ta")
        unit = self.units["D1"]
        pinned = self._post("/submissions/ta-unr/org-unit", {"org_unit_id": str(unit.org_unit_id)})
        self.assertEqual(pinned.status_code, 200, pinned.get_json())
        body = pinned.get_json()
        self.assertEqual(set(body), {"va_sid", "org_unit_id", "unit_code", "resolution", "message"})
        self.assertEqual(
            (body["va_sid"], body["org_unit_id"], body["unit_code"], body["message"]),
            ("ta-unr", str(unit.org_unit_id), "D1", "Submission pinned to D1."),
        )
        cleared = self._post("/submissions/ta-unr/org-unit", {"org_unit_id": None})
        self.assertEqual(cleared.status_code, 200, cleared.get_json())
        self.assertEqual(cleared.get_json()["unit_code"], None)
        self.assertEqual(
            cleared.get_json()["message"],
            "Unit pin cleared. The next sync will route this submission again.",
        )

    def test_pin_refusals(self):
        self._as("dm_ta")
        cases = (
            ("no-such-sid", {"org_unit_id": None}, 404),
            ("ta-unr", [1], 400),
            ("ta-unr", {"org_unit_id": "not-a-uuid"}, 400),
        )
        for sid, body, status in cases:
            with self.subTest(sid=sid, body=body):
                response = self._post(f"/submissions/{sid}/org-unit", body)
                self.assertEqual(response.status_code, status, response.get_json())
        self.assertEqual(
            self._post("/submissions/ta-unr/org-unit", {"org_unit_id": "x"}).get_json(),
            {"error": "Invalid org_unit_id.", "code": "invalid_request"},
        )
        self._as("dm_c1")
        outside = self._post(
            "/submissions/ta-unr/org-unit", {"org_unit_id": str(self.units["D2"].org_unit_id)}
        )
        self.assertEqual(
            (outside.status_code, outside.get_json()),
            (403, {"error": "You may pin only to a unit inside your area.", "code": "forbidden"}),
        )
