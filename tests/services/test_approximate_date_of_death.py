"""The year-of-death fallback date (docs/policy/web-intake.md, "Date of death")."""
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from app.services.web_intake_service import _approximate_date_of_death as approx


class ApproximateDateOfDeathTests(unittest.TestCase):
    def test_year_only_gives_1_july(self):
        self.assertEqual(approx({"Id10022": "no", "Id10024": "2020-01-01"}), date(2020, 7, 1))
        self.assertEqual(approx({"Id10024": "2020"}), date(2020, 7, 1))

    def test_an_exact_date_wins(self):
        self.assertIsNone(approx({"Id10023": "2020-03-04", "Id10024": "2020"}))

    def test_date_known_without_a_date_gives_nothing(self):
        self.assertIsNone(approx({"Id10022": "yes", "Id10024": "2020"}))

    def test_a_july_still_ahead_is_capped_at_today(self):
        with patch("app.services.web_intake_service.date") as fake:
            fake.today.return_value = date(2026, 3, 5)
            fake.side_effect = date
            fake.fromisoformat = date.fromisoformat
            self.assertEqual(approx({"Id10022": "no", "Id10024": "2026"}), date(2026, 3, 5))

    def test_unusable_years_give_nothing(self):
        nxt = str(date.today().year + 1)
        for bad in (None, "", "abc", "20x0", "1899", nxt, "202"):
            self.assertIsNone(approx({"Id10022": "no", "Id10024": bad}), bad)


if __name__ == "__main__":
    unittest.main()
