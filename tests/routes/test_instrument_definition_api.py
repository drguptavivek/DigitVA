"""GET /api/v1/instruments/<code>/definition and /versions
(app/routes/api/instruments.py; contract in
docs/policy/field-data-collection.md "Form definition from the server").
"""
import gzip
import hashlib
import json
from datetime import UTC, datetime
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    MasInstrumentVersions,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import served_form_service as svc
from tests.base import BaseTestCase

PROJECT = "DEFN01"
CODE = "WHO_2022_VA"
DEFINITION_URL = f"/api/v1/instruments/{CODE}/definition?project_id={PROJECT}"
VERSIONS_URL = f"/api/v1/instruments/{CODE}/versions"


class InstrumentDefinitionApiTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(
            VaProjectMaster(
                project_id=PROJECT,
                project_code=PROJECT,
                project_name="Definition Project",
                project_nickname="Defn",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
                social_autopsy_enabled=False,
            )
        )
        db.session.flush()
        cls.granted = cls._get_or_make_user("defn.granted@test.local", "Defn12345")
        cls.no_grant = cls._get_or_make_user("defn.nogrant@test.local", "Defn12345")
        db.session.add(
            VaUserAccessGrants(
                user_id=cls.granted.user_id,
                role=VaAccessRoles.interviewer,
                scope_type=VaAccessScopeTypes.project,
                project_id=PROJECT,
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()

    def setUp(self):
        super().setUp()
        # The test transaction rolls recorded rows back; the process-level
        # "already recorded" memory must not outlive them.
        svc._recorded.clear()
        self.addCleanup(svc._recorded.clear)
        svc._retry_at = 0.0
        project = db.session.get(VaProjectMaster, PROJECT)
        project.social_autopsy_enabled = False
        db.session.commit()

    def _get(self, url=DEFINITION_URL, **kwargs):
        self._login(str(self.granted.user_id))
        return self.client.get(url, **kwargs)

    # -- access -------------------------------------------------------------

    def test_anonymous_is_refused(self):
        self.assertIn(self.client.get(DEFINITION_URL).status_code, (302, 401))
        self.assertIn(self.client.get(VERSIONS_URL).status_code, (302, 401))

    def test_a_user_with_no_grant_on_the_project_gets_403(self):
        self._login(str(self.no_grant.user_id))
        self.assertEqual(self.client.get(DEFINITION_URL).status_code, 403)
        # ... while the same user may read the version list (not per project).
        self.assertEqual(self.client.get(VERSIONS_URL).status_code, 200)

    def test_project_id_is_required_and_must_exist(self):
        self.assertEqual(self._get(f"/api/v1/instruments/{CODE}/definition").status_code, 400)
        self.assertEqual(self._get(f"/api/v1/instruments/{CODE}/definition?project_id=NOPE99").status_code, 404)

    def test_an_unknown_instrument_is_404(self):
        self.assertEqual(self._get(f"/api/v1/instruments/NOPE/definition?project_id={PROJECT}").status_code, 404)
        self.assertEqual(self._get("/api/v1/instruments/NOPE/versions").status_code, 404)

    # -- definition ---------------------------------------------------------

    def test_headers_body_and_etag_agree(self):
        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        sha = hashlib.sha256(response.data).hexdigest()
        self.assertEqual(response.headers["ETag"], f'"{sha}"')
        self.assertEqual(response.headers["X-Definition-SHA256"], sha)
        cache_control = response.headers["Cache-Control"]
        self.assertIn("private", cache_control)
        self.assertIn("no-cache", cache_control)
        body = json.loads(response.data)
        self.assertEqual(body["version"], svc.composed_version())
        self.assertEqual(body["engineVersion"], 1)
        self.assertNotIn("sha256", body)

    def test_the_slice_follows_the_projects_enabled_extensions(self):
        marker = next(
            q["name"] for q in svc.composed_definition()["questions"] if q.get("extensions") == ["social_autopsy"]
        )

        def served_names():
            return {q["name"] for q in json.loads(self._get().data)["questions"]}

        # Present first: medical records are on by default, social autopsy off.
        names = served_names()
        self.assertIn("md_available", names)
        self.assertNotIn(marker, names)

        project = db.session.get(VaProjectMaster, PROJECT)
        project.social_autopsy_enabled = True
        db.session.commit()
        self.assertIn(marker, served_names())

    def test_if_none_match_gets_a_bodiless_304(self):
        first = self._get()
        etag = first.headers["ETag"]
        again = self._get(headers={"If-None-Match": etag})
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again.data, b"")
        self.assertEqual(again.headers["ETag"], etag)
        self.assertIn("no-cache", again.headers["Cache-Control"])
        stale = self._get(headers={"If-None-Match": '"0000"'})
        self.assertEqual(stale.status_code, 200)
        self.assertEqual(stale.data, first.data)

    def test_a_gzip_client_gets_the_same_json_compressed(self):
        plain = self._get()
        packed = self._get(headers={"Accept-Encoding": "gzip"})
        self.assertEqual(packed.status_code, 200)
        self.assertEqual(packed.headers["Content-Encoding"], "gzip")
        self.assertIn("Accept-Encoding", packed.headers["Vary"])
        self.assertLess(len(packed.data), len(plain.data) // 3)
        self.assertEqual(gzip.decompress(packed.data), plain.data)
        sha = plain.headers["X-Definition-SHA256"]
        self.assertEqual(packed.headers["X-Definition-SHA256"], sha)
        self.assertEqual(packed.headers["ETag"], f'"{sha}.gz"')
        # Either representation's ETag revalidates.
        self.assertEqual(
            self._get(headers={"Accept-Encoding": "gzip", "If-None-Match": plain.headers["ETag"]}).status_code, 304)

    # -- historical slice ---------------------------------------------------

    OLD = "2026010101-aaaaaaaaaa"

    def _old_version(self):
        """A recorded older version: tagged definition with two extensions."""
        def q(name, *tags):
            return {"name": name, "type": "text", **({"extensions": list(tags)} if tags else {})}

        db.session.add(MasInstrumentVersions(
            instrument_code=CODE, version=self.OLD, activated_at=datetime(2026, 1, 1, tzinfo=UTC),
            definition={"version": self.OLD, "engineVersion": 1, "sections": [],
                        "questions": [q("base"), q("only_abha", "abha"), q("only_md", "medical_records")]},
        ))
        db.session.commit()
        svc._stored_definition.cache_clear()
        self.addCleanup(svc._stored_definition.cache_clear)

    def _old(self, extensions, **kwargs):
        return self._get(f"{DEFINITION_URL}&version={self.OLD}&extensions={extensions}", **kwargs)

    def test_the_body_names_its_extensions(self):
        self.assertEqual(self._get().get_json()["extensions"], ["death_summary", "medical_records"])  # defaults
        project = db.session.get(VaProjectMaster, PROJECT)
        project.social_autopsy_enabled = True
        db.session.commit()
        self.assertEqual(self._get().get_json()["extensions"], ["death_summary", "medical_records", "social_autopsy"])

    def test_a_slice_re_served_from_its_stored_copy_hashes_exactly_as_first_served(self):
        # The JSONB copy does not keep key order; the bytes must not depend on it.
        svc.record_served_version()
        svc._stored_definition.cache_clear()
        svc._serve_historical.cache_clear()
        self.addCleanup(svc._serve_historical.cache_clear)
        for chosen in (frozenset(), frozenset({"abha"}), frozenset({"death_summary", "medical_records"})):
            with self.subTest(extensions=sorted(chosen)):
                first = svc.served_definition(chosen)
                again = svc._serve_historical(svc.composed_version(), chosen)
                self.assertEqual(again.sha256, first.sha256)
                self.assertEqual(again.body, first.body)

    def test_a_recorded_older_version_is_served_as_the_slice_it_was(self):
        self._old_version()
        response = self._old("abha")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual((body["version"], body["extensions"]), (self.OLD, ["abha"]))
        self.assertEqual([q["name"] for q in body["questions"]], ["base", "only_abha"])
        sha = hashlib.sha256(response.data).hexdigest()
        self.assertEqual(response.headers["X-Definition-SHA256"], sha)
        self.assertEqual(response.headers["ETag"], f'"{sha}"')
        # Another slice of the same version is another sha; none/empty is allowed.
        none = self._old("")
        self.assertEqual([q["name"] for q in none.get_json()["questions"]], ["base"])
        self.assertNotEqual(none.headers["X-Definition-SHA256"], sha)
        both = self._old("medical_records,abha")
        self.assertEqual(both.get_json()["extensions"], ["abha", "medical_records"])
        self.assertEqual(both.data, self._old("abha,medical_records,abha").data)
        # The project need not enable it today (social autopsy is off here).
        self.assertEqual(self._old("abha").data, response.data)

    def test_the_historical_route_revalidates_with_the_etag_and_gzips(self):
        self._old_version()
        first = self._old("abha")
        again = self._old("abha", headers={"If-None-Match": first.headers["ETag"]})
        self.assertEqual((again.status_code, again.data), (304, b""))
        packed = self._old("abha", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(packed.headers["Content-Encoding"], "gzip")
        self.assertEqual(gzip.decompress(packed.data), first.data)

    def test_the_current_version_with_matching_extensions_is_byte_identical_to_the_default(self):
        default = self._get()
        extensions = ",".join(default.get_json()["extensions"])
        explicit = self._get(f"{DEFINITION_URL}&version={svc.composed_version()}&extensions={extensions}")
        self.assertEqual(explicit.status_code, 200)
        self.assertEqual(explicit.data, default.data)
        self.assertEqual(explicit.headers["X-Definition-SHA256"], default.headers["X-Definition-SHA256"])

    def test_an_unrecorded_version_is_404_version_unknown(self):
        response = self._get(f"{DEFINITION_URL}&version=1999010101-ffffffffff&extensions=")
        self.assertEqual((response.status_code, response.get_json()["code"]), (404, "version_unknown"))

    def test_extensions_outside_the_versions_tags_are_422(self):
        self._old_version()
        for url in (
            f"{DEFINITION_URL}&version={self.OLD}&extensions=abha,nope",
            f"{DEFINITION_URL}&version={self.OLD}&extensions=social_autopsy",  # real, but not in that version
            f"{DEFINITION_URL}&version={svc.composed_version()}&extensions=nope",
        ):
            response = self._get(url)
            self.assertEqual((response.status_code, response.get_json()["code"]), (422, "invalid_extensions"), url)

    def test_version_and_extensions_are_given_together(self):
        self.assertEqual(self._get(f"{DEFINITION_URL}&version={svc.composed_version()}").status_code, 400)
        self.assertEqual(self._get(f"{DEFINITION_URL}&extensions=abha").status_code, 400)

    def test_the_historical_route_needs_project_access(self):
        self._old_version()
        self._login(str(self.no_grant.user_id))
        self.assertEqual(self.client.get(f"{DEFINITION_URL}&version={self.OLD}&extensions=").status_code, 403)

    def test_a_failed_version_record_backs_off_instead_of_retrying_every_request(self):
        with mock.patch.object(svc.db.session, "begin_nested", side_effect=RuntimeError("no table")) as nested:
            svc.record_served_version()
            svc.record_served_version()
        self.assertEqual(nested.call_count, 1)
        svc._retry_at = 0.0
        svc.record_served_version()
        self.assertEqual(len(self._rows()), 1)

    # -- versions -----------------------------------------------------------

    def _rows(self):
        return db.session.scalars(
            sa.select(MasInstrumentVersions).where(MasInstrumentVersions.instrument_code == CODE)
        ).all()

    def test_a_version_is_recorded_once_however_often_it_is_served(self):
        self.assertEqual(self._rows(), [])
        for _ in range(3):
            self.assertEqual(self._get().status_code, 200)
        self.assertEqual(self._get(VERSIONS_URL).status_code, 200)
        rows = self._rows()
        self.assertEqual([r.version for r in rows], [svc.composed_version()])
        self.assertEqual(rows[0].definition["version"], svc.composed_version())
        # The stored copy is the full tagged one, not a project's slice.
        self.assertTrue(any(q.get("extensions") for q in rows[0].definition["questions"]))

    def test_recording_is_idempotent_across_processes(self):
        svc.record_served_version()
        svc._recorded.clear()  # a second worker that never saw the first
        svc.record_served_version()
        self.assertEqual(len(self._rows()), 1)

    def test_versions_are_listed_newest_first_and_current_is_included(self):
        db.session.add(
            MasInstrumentVersions(
                instrument_code=CODE, version="2026010101-aaaaaaaaaa",
                activated_at=datetime(2026, 1, 1, tzinfo=UTC), definition={"questions": [], "sections": []},
            )
        )
        db.session.add(
            MasInstrumentVersions(
                instrument_code=CODE, version="2026050505-bbbbbbbbbb",
                activated_at=datetime(2026, 5, 5, tzinfo=UTC), definition={"questions": [], "sections": []},
            )
        )
        db.session.commit()

        payload = self._get(VERSIONS_URL).get_json()
        self.assertEqual(payload["instrument_code"], CODE)
        self.assertEqual(payload["current"], svc.composed_version())
        versions = [v["version"] for v in payload["versions"]]
        self.assertEqual(versions, [svc.composed_version(), "2026050505-bbbbbbbbbb", "2026010101-aaaaaaaaaa"])
        self.assertEqual(set(payload["versions"][0]), {"version", "activated_at"})
        stamps = [v["activated_at"] for v in payload["versions"]]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    # -- form-options -------------------------------------------------------

    def test_form_options_carries_the_composed_version_and_the_slices_sha(self):
        options = self._get(f"/api/v1/organization/{PROJECT}/form-options").get_json()
        definition = self._get()
        self.assertEqual(options["instrument_version"], svc.composed_version())
        self.assertEqual(options["definition_sha256"], definition.headers["X-Definition-SHA256"])
