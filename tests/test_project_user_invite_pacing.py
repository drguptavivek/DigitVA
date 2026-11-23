from types import SimpleNamespace
from unittest.mock import patch

from app.models import VaStatuses
from app.services import project_user_import_service as user_import
from tests.base import BaseTestCase


def _invitations(n):
    return [
        SimpleNamespace(user_id=i, email=f"user{i}@example.test", name=f"User {i}")
        for i in range(n)
    ]


class TestInvitationPacing(BaseTestCase):
    def _finalize(self, invitations, results=None):
        with self.app.app_context(), patch(
            "app.services.email_service.is_mail_configured", return_value=True
        ), patch(
            "app.services.token_service.generate_token", return_value="tok"
        ), patch(
            "app.services.email_service.send_verification_email",
            side_effect=results or (lambda *a, **k: True),
        ) as send:
            queued, warnings = user_import.finalize_apply(
                "PRJ001",
                actor_user_id=1,
                actor_role="admin",
                changed_grants=[],
                invitations=invitations,
            )
        return queued, warnings, [c.kwargs["countdown"] for c in send.call_args_list]

    def test_110_invitations_are_spaced_two_seconds_apart(self):
        queued, _warnings, countdowns = self._finalize(_invitations(110))
        self.assertEqual(queued, 110)
        self.assertEqual(countdowns, list(range(0, 220, 2)))

    def test_skipped_invitation_does_not_consume_a_slot(self):
        outcomes = iter([True, False, True, True])
        queued, warnings, countdowns = self._finalize(
            _invitations(4), results=lambda *a, **k: next(outcomes)
        )
        self.assertEqual(queued, 3)
        self.assertEqual(countdowns, [0, 2, 2, 4])
        self.assertEqual(len(warnings), 1)

    def test_existing_account_rows_produce_no_invitation(self):
        existing = SimpleNamespace(user_id=9, email="old@example.test", name="Old")
        plan = [{
            "user": existing, "identity": "old@example.test", "grant": SimpleNamespace(
                user_id=9, grant_status=VaStatuses.active),
            "action": "noop", "unit": None, "cadre": None, "role": None,
        }]
        with self.app.app_context():
            invitations, audit, codes = user_import.apply("PRJ001", plan, actor_user_id=1)
        self.assertEqual((invitations, audit, codes), ([], [], []))
