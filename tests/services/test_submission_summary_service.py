import uuid

from app import db
from app.models import MasChoiceMappings, MasFieldDisplayConfig, MasFormTypes
from app.services.submission_summary_service import build_submission_summary
from tests.base import BaseTestCase


class TestSubmissionSummaryService(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.form_type = MasFormTypes(
            form_type_id=uuid.uuid4(),
            form_type_code="TEST_SUMMARY_FORM",
            form_type_name="Test Summary Form",
            is_active=True,
        )
        db.session.add(cls.form_type)
        db.session.flush()

        db.session.add_all(
            [
                MasFieldDisplayConfig(
                    form_type_id=cls.form_type.form_type_id,
                    field_id="symptom_yes",
                    field_type="select_one",
                    short_label="Fever",
                    summary_label="Fever",
                    summary_include=True,
                    flip_color=False,
                    display_order=1,
                    is_active=True,
                ),
                MasFieldDisplayConfig(
                    form_type_id=cls.form_type.form_type_id,
                    field_id="flip_no",
                    field_type="select_one",
                    short_label="Never breathed",
                    summary_label="Never breathed",
                    summary_include=True,
                    flip_color=True,
                    display_order=2,
                    is_active=True,
                ),
                MasFieldDisplayConfig(
                    form_type_id=cls.form_type.form_type_id,
                    field_id="Id10120",
                    field_type="integer",
                    short_label="Illness duration",
                    summary_label="Illness duration (in days)",
                    summary_include=True,
                    flip_color=False,
                    display_order=3,
                    is_active=True,
                ),
            ]
        )
        db.session.add(
            MasChoiceMappings(
                form_type_id=cls.form_type.form_type_id,
                field_id="symptom_yes",
                choice_value="yes",
                choice_label="Yes",
                display_order=1,
                is_active=True,
            )
        )
        db.session.commit()

    def test_builds_dynamic_summary_from_db_flags(self):
        summary = build_submission_summary(
            "TEST_SUMMARY_FORM",
            {
                "symptom_yes": "yes",
                "flip_no": "no",
                "Id10120": 5,
            },
        )

        self.assertEqual(
            summary,
            [
                "Fever",
                "Never breathed",
                "Illness duration (in days): 5",
            ],
        )
