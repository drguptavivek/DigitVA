"""Proof-of-work CAPTCHA: signature, expiry, solution and single-use replay."""

import hashlib
import time
from unittest.mock import patch

from tests.base import BaseTestCase


def _solve(salt: str, difficulty: int) -> str:
    """Brute-force the smallest solution for a (low, test-only) difficulty."""
    number = 0
    while True:
        digest = hashlib.sha256((salt + str(number)).encode()).digest()
        value = int.from_bytes(digest, "big")
        if difficulty <= 0 or (value >> (256 - difficulty)) == 0:
            return str(number)
        number += 1


class PowCaptchaServiceTests(BaseTestCase):
    def test_issue_then_verify_solved_challenge_succeeds(self):
        from app.services.pow_captcha_service import issue_challenge, verify_challenge

        with self.app.app_context():
            challenge = issue_challenge()
            solution = _solve(challenge["salt"], challenge["difficulty"])
            self.assertTrue(
                verify_challenge(
                    salt=challenge["salt"],
                    difficulty=challenge["difficulty"],
                    expires=challenge["expires"],
                    signature=challenge["signature"],
                    solution=solution,
                )
            )

    def test_bad_signature_is_rejected(self):
        from app.services.pow_captcha_service import issue_challenge, verify_challenge

        with self.app.app_context():
            challenge = issue_challenge()
            solution = _solve(challenge["salt"], challenge["difficulty"])
            self.assertFalse(
                verify_challenge(
                    salt=challenge["salt"],
                    difficulty=challenge["difficulty"],
                    expires=challenge["expires"],
                    signature="0" * 64,
                    solution=solution,
                )
            )

    def test_tampered_difficulty_invalidates_signature(self):
        from app.services.pow_captcha_service import issue_challenge, verify_challenge

        with self.app.app_context():
            challenge = issue_challenge()
            solution = _solve(challenge["salt"], 0)
            self.assertFalse(
                verify_challenge(
                    salt=challenge["salt"],
                    difficulty=0,  # lowered from the signed value
                    expires=challenge["expires"],
                    signature=challenge["signature"],
                    solution=solution,
                )
            )

    def test_expired_challenge_is_rejected(self):
        from app.services.pow_captcha_service import issue_challenge, verify_challenge

        with self.app.app_context():
            challenge = issue_challenge()
            solution = _solve(challenge["salt"], challenge["difficulty"])
            with patch("time.time", return_value=challenge["expires"] + 1):
                self.assertFalse(
                    verify_challenge(
                        salt=challenge["salt"],
                        difficulty=challenge["difficulty"],
                        expires=challenge["expires"],
                        signature=challenge["signature"],
                        solution=solution,
                    )
                )

    def test_wrong_solution_is_rejected(self):
        from app.services.pow_captcha_service import issue_challenge, verify_challenge

        with self.app.app_context():
            challenge = issue_challenge()
            self.assertFalse(
                verify_challenge(
                    salt=challenge["salt"],
                    difficulty=challenge["difficulty"],
                    expires=challenge["expires"],
                    signature=challenge["signature"],
                    solution="not-a-valid-solution",
                )
            )

    def test_wrong_solution_does_not_burn_the_single_use(self):
        from app.services.pow_captcha_service import issue_challenge, verify_challenge

        with self.app.app_context():
            challenge = issue_challenge()
            solution = _solve(challenge["salt"], challenge["difficulty"])
            self.assertFalse(
                verify_challenge(
                    salt=challenge["salt"],
                    difficulty=challenge["difficulty"],
                    expires=challenge["expires"],
                    signature=challenge["signature"],
                    solution="wrong",
                )
            )
            self.assertTrue(
                verify_challenge(
                    salt=challenge["salt"],
                    difficulty=challenge["difficulty"],
                    expires=challenge["expires"],
                    signature=challenge["signature"],
                    solution=solution,
                )
            )

    def test_replay_of_a_solved_challenge_is_rejected(self):
        from app.services.pow_captcha_service import issue_challenge, verify_challenge

        with self.app.app_context():
            challenge = issue_challenge()
            solution = _solve(challenge["salt"], challenge["difficulty"])
            kwargs = dict(
                salt=challenge["salt"],
                difficulty=challenge["difficulty"],
                expires=challenge["expires"],
                signature=challenge["signature"],
                solution=solution,
            )
            self.assertTrue(verify_challenge(**kwargs))
            self.assertFalse(verify_challenge(**kwargs))
