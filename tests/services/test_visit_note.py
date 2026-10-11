"""The web-intake visit note: area count and link, data manager filter and
rows, redaction, case-view block (digitva-96a7).

Policy: docs/policy/web-intake.md "Visit note"; docs/policy/area-dashboard.md
"Visit notes column". Fixture: tests/services/test_area_dashboard_service.py
(tree ARDT01: PHC A1 under CHC A under District 1; CHC B; sites-mode ARDS01).
"""
from datetime import UTC, datetime

from app import db
from app.models import VaAccessRoles, VaAccessScopeTypes, VaDeathRegister, VaSubmissions
from app.services import area_dashboard_service as area
from app.services.data_management_service import dm_submissions_page
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.viewer_pii_service import should_redact_pii
from app.services.visit_note import note_from_payload, visit_note_for_viewer
from tests.services.test_area_dashboard_service import AreaDashboardFixture

ADDRESS = "House 12, Ward 4, Mill Road"
REMARKS = "Family declined at the door"


class VisitNoteFixture(AreaDashboardFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Notes: PHC A1 (under CHC A), CHC A itself, CHC B, and a sites-mode
        # site. uuid:area-pa2 has a payload with no note.
        cls._note("uuid:area-pa1")
        cls._note("uuid:area-ca1")
        cls._note("uuid:area-cb1")
        cls._note("uuid:area-s21")
        cls._payload("uuid:area-pa2", {"Id10013": "yes", "visit_date": "", "visit_address": ""})
        cls.collaborator = cls._get_or_make_user("area.vn.collab@test.local", "AreaUser123")
        cls._grant(cls.collaborator, VaAccessRoles.collaborator, VaAccessScopeTypes.project,
                   project_id=cls.TREE)
        db.session.commit()

    @classmethod
    def _payload(cls, sid, data):
        ensure_active_payload_version(db.session.get(VaSubmissions, sid), payload_data=data)

    @classmethod
    def _note(cls, sid):
        db.session.get(VaSubmissions, sid).va_consent = "no"
        cls._payload(sid, {
            "Id10013": "no",
            "visit_address": ADDRESS,
            "visit_date": "2026-10-01",
            "visit_remarks": REMARKS,
        })


class VisitNoteAreaTests(VisitNoteFixture):
    def _counts(self, user, project=None, unit=None):
        rows = self._by_key(area.area_summary(user, project or self.TREE, unit_id=unit))
        return {key: row["counts"]["visit_notes"] for key, row in rows.items()}, rows

    def test_unit_counts_its_subtree_once_and_ignores_empty_notes(self):
        counts, _ = self._counts(self.unit_user)
        # PHC A1 + CHC A itself; pa2 (empty note) and CHC B (outside) not counted.
        self.assertEqual(counts[str(self.chc_a.org_unit_id)], 2)

    def test_project_wide_root_and_drill_down(self):
        counts, _ = self._counts(self.project_user)
        self.assertEqual(counts[str(self.district_1.org_unit_id)], 3)
        self.assertEqual(counts[str(self.district_2.org_unit_id)], 0)
        child, _ = self._counts(self.project_user, unit=str(self.district_1.org_unit_id))
        self.assertEqual(child[str(self.chc_a.org_unit_id)], 2)
        self.assertEqual(child[str(self.chc_b.org_unit_id)], 1)

    def test_sites_mode_counts_per_site(self):
        counts, _ = self._counts(self.base_admin_user, project=self.SITES)
        self.assertEqual(counts[self.SITE_ONE], 0)
        self.assertEqual(counts[self.SITE_TWO], 1)

    def test_a_confirmed_duplicate_leaves_the_count(self):
        key = str(self.chc_a.org_unit_id)
        self.assertEqual(self._counts(self.unit_user)[0][key], 2)
        db.session.add(VaDeathRegister(
            project_id=self.TREE, site_id=self.TREE_SITE, death_number=990301,
            unique_id="VN-DUP-1", deceased_name="Asha Devi", deceased_sex="female",
            date_of_death=datetime.now(UTC).date(), registered_by=self.interviewer.user_id,
            status="duplicate", va_sid="uuid:area-pa1",
        ))
        db.session.commit()
        self.assertEqual(self._counts(self.unit_user)[0][key], 1)

    def test_count_carries_no_subject_data(self):
        _, rows = self._counts(self.project_user)
        flat = repr(rows)
        self.assertNotIn(ADDRESS, flat)
        self.assertNotIn(REMARKS, flat)

    def test_link_for_data_manager_only_with_unit_and_filter(self):
        _, rows = self._counts(self.project_user)
        link = rows[str(self.district_1.org_unit_id)]["links"]["visit_notes"]
        self.assertEqual(link["endpoint"], area.SCREEN_DATA_MANAGEMENT)
        self.assertEqual(link["params"]["visit_note"], "1")
        self.assertEqual(link["params"]["org_unit"], str(self.district_1.org_unit_id))
        self.assertEqual(link["params"]["project"], self.TREE)
        _, coder_rows = self._counts(self.unit_user)  # coder: no data manager screen
        self.assertEqual(coder_rows[str(self.chc_a.org_unit_id)]["links"], {})

    def test_sites_mode_link_names_the_site(self):
        _, rows = self._counts(self.base_admin_user, project=self.SITES)
        params = rows[self.SITE_TWO]["links"]["visit_notes"]["params"]
        self.assertEqual((params["site"], params["visit_note"]), (self.SITE_TWO, "1"))


class VisitNoteDataManagerTests(VisitNoteFixture):
    def _page(self, user, **kwargs):
        return dm_submissions_page(user, project=self.TREE, odk_sync="all", per_page=100, **kwargs)

    def _by_sid(self, result):
        return {row["va_sid"]: row for row in result["data"]}

    def test_filter_keeps_only_cases_with_a_note(self):
        everything = self._by_sid(self._page(self.project_user))
        self.assertIn("uuid:area-pa2", everything)  # present before it is filtered out
        self.assertIn("uuid:area-d21", everything)
        filtered = self._by_sid(self._page(self.project_user, visit_note="1"))
        self.assertEqual(set(filtered), {"uuid:area-pa1", "uuid:area-ca1", "uuid:area-cb1"})

    def test_org_unit_filter_takes_the_subtree(self):
        rows = self._by_sid(self._page(self.project_user, visit_note="1", org_unit=str(self.chc_a.org_unit_id)))
        self.assertEqual(set(rows), {"uuid:area-pa1", "uuid:area-ca1"})
        self.assertEqual(self._page(self.project_user, org_unit="not-a-uuid")["total"], 0)

    def test_unredacted_viewer_sees_address_and_remarks(self):
        self.assertFalse(should_redact_pii(self.project_user))
        note = self._by_sid(self._page(self.project_user, visit_note="1"))["uuid:area-pa1"]["visit_note"]
        self.assertEqual(
            note,
            {"date": "2026-10-01", "address": ADDRESS, "remarks": REMARKS, "redacted": False},
        )

    def test_redacted_viewer_gets_the_date_only(self):
        self.assertTrue(should_redact_pii(self.collaborator))
        # The same row is present and unredacted for the other viewer (above).
        rows = self._by_sid(self._page(self.collaborator, visit_note="1"))
        self.assertIn("uuid:area-pa1", rows)
        note = rows["uuid:area-pa1"]["visit_note"]
        self.assertEqual(note, {"date": "2026-10-01", "address": None, "remarks": None, "redacted": True})
        self.assertNotIn(ADDRESS, repr(rows))
        self.assertNotIn(REMARKS, repr(rows))

    def test_rows_without_a_note_carry_none(self):
        rows = self._by_sid(self._page(self.project_user))
        self.assertIsNone(rows["uuid:area-pa2"]["visit_note"])
        self.assertIsNone(rows["uuid:area-d21"]["visit_note"])


class VisitNoteCaseViewTests(AreaDashboardFixture):
    PAYLOAD = {"visit_address": ADDRESS, "visit_date": "2026-10-01", "visit_remarks": REMARKS}

    def test_note_from_payload_keeps_all_three(self):
        note = visit_note_for_viewer(note_from_payload(self.PAYLOAD), redact_pii=False)
        self.assertEqual(note["address"], ADDRESS)
        self.assertEqual(note["remarks"], REMARKS)
        self.assertEqual(note["date"], "2026-10-01")

    def test_redacted_variant_withholds_address_and_remarks(self):
        note = visit_note_for_viewer(note_from_payload(self.PAYLOAD), redact_pii=True)
        self.assertEqual(note, {"date": "2026-10-01", "address": None, "remarks": None, "redacted": True})

    def test_no_note_is_none(self):
        self.assertIsNone(visit_note_for_viewer(note_from_payload({"Id10013": "yes"}), redact_pii=False))
        self.assertIsNone(visit_note_for_viewer(note_from_payload(None), redact_pii=True))


class VisitNoteHeaderRenderTests(VisitNoteFixture):
    """The note rides in the case page header (a nameless refusal has no
    category data to carry it), redacted per viewer."""

    def _open(self, user):
        self._login(str(user.user_id))
        return self.client.get("/coding/area/uuid:area-pa1")

    def test_pii_viewer_sees_address_then_plain_collaborator_does_not(self):
        pii = self._get_or_make_user("area.vn.collabpii@test.local", "AreaUser123")
        self._grant(pii, VaAccessRoles.collaborator_pii, VaAccessScopeTypes.project,
                    project_id=self.TREE)
        db.session.commit()
        body = self._open(pii).get_data(as_text=True)
        self.assertEqual(self.client.get("/coding/area/uuid:area-pa1").status_code, 200)
        self.assertIn(ADDRESS, body)
        self.assertIn(REMARKS, body)

        body = self._open(self.collaborator).get_data(as_text=True)
        self.assertIn("2026-10-01", body)
        self.assertNotIn(ADDRESS, body)
        self.assertNotIn(REMARKS, body)
