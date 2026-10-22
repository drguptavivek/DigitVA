"""Training report pages and CSV exports under /data-management/training (digitva-vd0g.2)."""

from app import db
from app.models import VaFinalAssessments
from app.services import training_demo_service as svc
from tests.services.test_training_report import PNEUMONIA, ReportTestBase

BASE = "/data-management/training"


class ReportRouteTests(ReportTestBase):
    def _add(self, tag, role, code="S001"):
        user = super()._add(tag, role, code)
        svc.complete_onboarding(user.user_id)  # a pending welcome page would redirect every page
        return user

    def _coded_session(self):
        coder = self._add("route.coder", "coder")
        db.session.add(VaFinalAssessments(
            va_sid="trn-S001-1", va_finassess_by=coder.user_id, va_conclusive_cod=PNEUMONIA))
        db.session.flush()
        return coder

    def test_session_manager_reads_the_report_and_csv(self):
        coder = self._coded_session()
        manager = self._add("route.rdm", "reviewer_data_manager")
        self._login(str(manager.user_id))
        listing = self.client.get(BASE)
        self.assertEqual(listing.status_code, 200)
        self.assertIn(b"S001", listing.data)
        self.assertNotIn(b"S002", listing.data)
        page = self.client.get(f"{BASE}/S001")
        self.assertEqual(page.status_code, 200)
        self.assertIn(coder.name.encode(), page.data)
        self.assertIn(b"VAs-01.02", page.data)
        self.assertNotIn(b"src-", page.data)
        coders = self.client.get(f"{BASE}/S001/coders.csv")
        self.assertEqual(coders.status_code, 200)
        self.assertEqual(coders.mimetype, "text/csv")
        self.assertIn("attachment", coders.headers["Content-Disposition"])
        self.assertTrue(coders.data.decode().startswith("name,email,slot"))
        self.assertIn(coder.email, coders.data.decode())
        cases = self.client.get(f"{BASE}/S001/cases.csv")
        self.assertEqual(cases.status_code, 200)
        self.assertIn("VAs-01.02", cases.data.decode())

    def test_admin_reads_any_session_and_unknown_is_404(self):
        self._login(self.base_admin_id)
        self.assertEqual(self.client.get(f"{BASE}/S002").status_code, 200)
        self.assertEqual(self.client.get(BASE).status_code, 200)
        self.assertEqual(self.client.get(f"{BASE}/S404").status_code, 404)

    def test_other_sessions_manager_and_trainees_are_refused_everywhere(self):
        self._coded_session()
        other = self._add("route.other", "reviewer_data_manager", code="S002")
        coder = self._add("route.trainee", "coder")
        interviewer = self._add("route.interviewer", "interviewer")
        for user in (other, coder, interviewer, self.base_coder_user):
            self._login(str(user.user_id))
            for path in ("", "/S001", "/S001/coders.csv", "/S001/cases.csv"):
                response = self.client.get(BASE + path)
                if path == "" and user is other:
                    self.assertEqual(response.status_code, 200)  # the list shows only their own session
                    self.assertNotIn(b"S001", response.data)
                    continue
                self.assertEqual(response.status_code, 403, (user.email, path))
                self.assertNotIn(b"Pneumonia", response.data)

    def test_anonymous_is_sent_to_sign_in(self):
        self.assertIn(self.client.get(f"{BASE}/S001").status_code, (302, 401))
        self.assertIn(self.client.get(f"{BASE}/S001/cases.csv").status_code, (302, 401))

    def test_welcome_checklist_links_the_report(self):
        manager = self._add("route.welcome", "reviewer_data_manager")
        self._login(str(manager.user_id))
        page = self.client.get("/demo/welcome")
        self.assertEqual(page.status_code, 200)
        self.assertIn(BASE.encode(), page.data)
        coder = self._add("route.welcome.coder", "coder")
        self._login(str(coder.user_id))
        self.assertNotIn(BASE.encode(), self.client.get("/demo/welcome").data)
        self.assertIsNotNone(svc.get_training_session("S001"))
