"""``flask seed test-media`` adds synthetic image and audio cases through web intake."""
import os
import sqlalchemy as sa

from app import db
from app.commands.seed import TEST_PROJECT_ID
from app.models import VaSubmissionAttachments, VaSubmissions, VaSubmissionWorkflow
from tests.base import BaseTestCase


class SeedTestMediaTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_form_type("WHO_2022_VA", "WHO VA 2022")
        db.session.commit()

    def _sids(self):
        return set(db.session.scalars(sa.select(VaSubmissions.va_sid)))

    def test_refused_outside_a_debug_or_testing_app(self):
        runner = self.app.test_cli_runner()
        self.app.testing, self.app.debug = False, False
        try:
            result = runner.invoke(args=["seed", "test-media"])
        finally:
            self.app.testing, self.app.debug = True, False
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("debug or testing", result.output)

    def test_adds_ready_cases_with_stored_image_and_audio(self):
        runner = self.app.test_cli_runner()
        self.assertEqual(runner.invoke(args=["seed", "test-project"]).exit_code, 0)
        before = self._sids()
        self.assertTrue(before is not None)
        result = runner.invoke(args=["seed", "test-media", "--count", "2"])
        self.assertEqual(result.exit_code, 0, result.output)
        db.session.expire_all()
        new = self._sids() - before
        self.assertEqual(len(new), 2)
        for sid in new:
            # SmartVA is queued after commit; the worker (absent here) then moves the case
            # to ready_for_coding.
            self.assertIn(
                db.session.scalar(sa.select(VaSubmissionWorkflow.workflow_state).where(VaSubmissionWorkflow.va_sid == sid)),
                ("smartva_pending", "ready_for_coding"),
            )
            rows = db.session.scalars(sa.select(VaSubmissionAttachments).where(VaSubmissionAttachments.va_sid == sid)).all()
            self.assertEqual(sorted(r.mime_type for r in rows), ["audio/wav", "image/png", "image/png"])
            for row in rows:
                self.assertTrue(row.local_path and os.path.isfile(row.local_path), row.local_path)
                with open(row.local_path, "rb") as fh:
                    self.assertTrue(fh.read(4) in (b"\x89PNG", b"RIFF"))
            self.assertIn(sid, result.output)
        # Nothing existing changed: a second run only adds.
        again = runner.invoke(args=["seed", "test-media", "--count", "1"])
        self.assertEqual(again.exit_code, 0, again.output)
        self.assertEqual(len(self._sids() - before), 3)
        self.assertTrue(new <= self._sids())
