"""Slide-to-slot puzzle CAPTCHA (docs/policy/public-privacy-and-data-requests.md section 7)."""
from unittest.mock import patch

from app import cache
from app.services import slide_captcha_service as slide
from tests.base import BaseTestCase


class SlideCaptchaServiceTest(BaseTestCase):
    def _issue(self):
        challenge = slide.issue_challenge()
        return challenge, cache.get(f"slide_captcha:{challenge['challenge_id']}")

    def _verify(self, challenge_id, x, duration_ms=800, moves=12):
        return slide.verify_challenge(challenge_id=challenge_id, x=x, duration_ms=duration_ms, moves=moves)

    def test_accepts_within_tolerance_at_both_edges(self):
        for offset in (-slide.TOLERANCE, 0, slide.TOLERANCE):
            with self.subTest(offset=offset):
                challenge, target = self._issue()
                self.assertTrue(self._verify(challenge["challenge_id"], target + offset))

    def test_rejects_just_outside_tolerance(self):
        challenge, target = self._issue()
        self.assertFalse(self._verify(challenge["challenge_id"], target + slide.TOLERANCE + 1))

    def test_non_ascii_digits_are_refused_not_a_crash(self):
        challenge, _ = self._issue()
        for value in ("\u00b2", "\u2460", "\u0663"):
            with self.subTest(value=value):
                self.assertFalse(self._verify(challenge["challenge_id"], value))
                self.assertFalse(self._verify(challenge["challenge_id"], 100, duration_ms=value))

    def test_rejects_too_fast_and_too_few_moves(self):
        challenge, target = self._issue()
        self.assertFalse(self._verify(challenge["challenge_id"], target, duration_ms=slide.MIN_DURATION_MS - 1))
        challenge, target = self._issue()
        self.assertFalse(self._verify(challenge["challenge_id"], target, moves=slide.MIN_MOVES - 1))

    def test_single_use_even_after_a_wrong_answer(self):
        challenge, target = self._issue()
        self.assertTrue(self._verify(challenge["challenge_id"], target))
        self.assertFalse(self._verify(challenge["challenge_id"], target))
        challenge, target = self._issue()
        self.assertFalse(self._verify(challenge["challenge_id"], target - 50))
        self.assertFalse(self._verify(challenge["challenge_id"], target))

    def test_expired_challenge_is_refused(self):
        challenge, target = self._issue()
        self.assertIsNotNone(target)
        with patch.object(cache, "get", return_value=None):
            self.assertFalse(self._verify(challenge["challenge_id"], target))

    def test_issued_with_the_ttl(self):
        with patch.object(cache, "set") as cache_set:
            slide.issue_challenge()
        self.assertEqual(cache_set.call_args.kwargs["timeout"], slide.CHALLENGE_TTL_SECONDS)

    def test_tampered_or_malformed_input_is_refused_without_spending(self):
        challenge, target = self._issue()
        for bad in (challenge["challenge_id"] + "x", "short", "", None, "a" * 16 + "!"):
            with self.subTest(bad=bad):
                self.assertFalse(self._verify(bad, target))
        for x in ("-1", "1e3", str(slide.TRACK + 1), "abc", None, "9" * 20):
            with self.subTest(x=x):
                self.assertFalse(self._verify(challenge["challenge_id"], x))
        self.assertTrue(self._verify(challenge["challenge_id"], target))

    def test_target_never_in_the_token(self):
        """The slot is drawn in the picture, so the target is visible there by
        design; what must hold is that the only value the form sends back,
        the challenge id, is random and carries no position: two challenges
        with the same target get unrelated ids, and the target is found only
        in the server-side cache."""
        with patch("app.services.slide_captcha_service.secrets.randbelow", return_value=7):
            first, first_target = self._issue()
            second, second_target = self._issue()
        self.assertEqual(first_target, second_target)
        self.assertNotEqual(first["challenge_id"], second["challenge_id"])
        self.assertEqual(len(first["challenge_id"]), 22)
        self.assertEqual(first["slot_x"], first_target)
        self.assertTrue(slide.PIECE + 16 <= first_target <= slide.TRACK - 8)
