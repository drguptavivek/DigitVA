"""``age_marks_for_codes``: the DORIS term search's age marks (digitva-o16a)."""

from unittest.mock import patch

from app import db
from app.models import MasIcd11Mms
from app.services.icd11_mms_service import age_marks_for_codes
from tests.base import BaseTestCase

RELEASE = "TEST-AGEMARK"


class AgeMarksForCodesTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        for index, (code, age, note) in enumerate((("KZ31", "neonate", "Neonates only"), ("KZ32", "all", None))):
            db.session.add(MasIcd11Mms(
                release=RELEASE, linearization_uri=f"test://{code}", code=code, title=f"Zqagemark {code}",
                class_kind="category", chapter_no="19", sort_order=index, source_version="test", is_active=True,
                is_coding_selectable=True, sex_selectable="both", age_group_selectable=age, restriction_note=note,
            ))
        db.session.flush()

    def _marks(self, codes, age_group):
        context = {"va_sid": "SID", "age_group": age_group, "sex": "male"}
        with patch("app.services.icd11_mms_service.coding_context_for_submission", return_value=context) as lookup:
            return age_marks_for_codes(codes, "SID", release=RELEASE), lookup

    def test_marks_only_the_codes_the_age_conflicts_with(self):
        marks, _ = self._marks(["KZ31", "KZ32", "NOPE", None], "adult")
        self.assertEqual(marks, {"KZ31": {"age_restricted": True, "restriction_note": "Neonates only"}})

    def test_marks_nothing_for_a_matching_age_no_age_or_unknown_submission(self):
        self.assertEqual(self._marks(["KZ31"], "neonate")[0], {})
        self.assertEqual(self._marks(["KZ31"], None)[0], {})
        with patch("app.services.icd11_mms_service.coding_context_for_submission", return_value=None):
            self.assertEqual(age_marks_for_codes(["KZ31"], "SID", release=RELEASE), {})

    def test_no_codes_skips_the_lookup(self):
        marks, lookup = self._marks([], "adult")
        self.assertEqual(marks, {})
        lookup.assert_not_called()
