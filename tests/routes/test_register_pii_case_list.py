"""PII slice 2, T2: the shared case list over sealed register rows.

Every row of the ``test_cases_api`` fixture is sealed after it is built, so
all of that module's tests (scope, names by reach, location, supervision)
run again against NULL plaintext columns and must pass unchanged. The tests
below add what sealing changes: who decrypts, how often, and the export.
"""
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import VaDeathRegister
from app.services import case_list_service as case_list
from app.services import register_pii_accessor as accessor
from app.utils import pii_crypto as pc
from tests.routes import test_cases_api as base


class SealedCaseListTests(base.CaseListTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        stamps = {d.death_id: d.updated_at for d in db.session.scalars(sa.select(VaDeathRegister))}
        for death in db.session.scalars(sa.select(VaDeathRegister)):
            accessor.seal_register_pii(death)
        db.session.flush()
        # Sealing is not a case change: keep the order the fixture set up.
        for death_id, stamp in stamps.items():
            db.session.execute(sa.update(VaDeathRegister).where(VaDeathRegister.death_id == death_id)
                               .values(updated_at=stamp))
        db.session.commit()

    def _opened(self, who, query=""):
        with mock.patch.object(pc, "open_record", wraps=pc.open_record) as spy:
            rows = self._ids(who, query)
        return rows, spy

    def test_the_fixture_is_sealed(self):
        row = db.session.execute(
            sa.text("SELECT deceased_name, latitude, pii_sealed IS NOT NULL AS sealed FROM va_death_register "
                    "WHERE death_id = :i"), {"i": self.a.death_id}).one()
        self.assertEqual((row.deceased_name, row.latitude, row.sealed), (None, None, True))

    def test_names_open_once_per_visible_row_and_a_hidden_viewer_decrypts_nothing(self):
        rows, spy = self._opened(self.dana)
        named = [r for r in rows.values() if "deceased_name" in r]
        self.assertTrue(named)  # present before absent
        self.assertEqual(spy.call_count, len(named))
        self.assertIn("Asha Alpha", {r["deceased_name"] for r in named})
        # A coder reaches rows but sees no name: nothing is opened.
        rows, spy = self._opened(self.cody)
        self.assertTrue(rows)
        self.assertTrue(all("deceased_name" not in r for r in rows.values()))
        self.assertEqual(spy.call_count, 0)

    def test_a_redacted_viewer_gets_names_but_the_fix_opens_only_where_shown(self):
        # ian (interviewer, not redacted) sees the fix of a, so a opens name and fix in one call.
        rows, spy = self._opened(self.ian)
        self.assertEqual(rows[str(self.a.death_id)]["latitude"], 28.61)
        located = [r for r in rows.values() if "latitude" in r]
        self.assertTrue(located)
        self.assertEqual(spy.call_count, len(rows))  # one unwrap-and-open a row, never two
        # sue (supervisor with PII access, redacted of the fix): names, no fix.
        rows, spy = self._opened(self.sue)
        self.assertTrue(any("deceased_name" in r for r in rows.values()))
        self.assertTrue(all("latitude" not in r for r in rows.values()))
        self.assertEqual(spy.call_count, len(rows))

    def test_a_page_costs_the_same_queries_whatever_its_size(self):
        def queries(limit):
            seen = []
            event = sa.event
            record = lambda conn, cur, stmt, *a: seen.append(stmt)  # noqa: E731
            event.listen(db.engine, "before_cursor_execute", record)
            try:
                self._get(self.dana, f"?limit={limit}")
            finally:
                event.remove(db.engine, "before_cursor_execute", record)
            return len(seen)
        queries(2)  # warm the grant caches
        self.assertEqual(queries(2), queries(8))

    def test_the_export_path_selects_no_name_and_decrypts_nothing(self):
        self._login(str(self.dana.user_id))
        with self.app.test_request_context():
            pass
        user = db.session.get(type(self.dana), self.dana.user_id)
        with mock.patch.object(pc, "open_record", wraps=pc.open_record) as spy:
            page = case_list.list_cases(
                user, preset="deaths", filters=case_list.CaseFilters(), limit=50, with_identifiers=False,
                with_names=False)
            full = case_list.list_cases(user, preset="deaths", filters=case_list.CaseFilters(), limit=50,
                                        with_identifiers=False)
        self.assertTrue(full["cases"] and "deceased_name" in full["cases"][0])
        self.assertTrue(page["cases"])
        for row in page["cases"]:
            self.assertNotIn("deceased_name", row)
            self.assertNotIn("latitude", row)
        self.assertEqual(spy.call_count, len(full["cases"]))  # only the second call decrypted
