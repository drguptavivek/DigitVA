from flask_wtf import FlaskForm
from wtforms import SelectField, SubmitField, TextAreaField
from wtforms.validators import AnyOf, Optional


class VaDataManagerReviewForm(FlaskForm):
    va_dmreview_reason = SelectField(
        "Please describe why this submission should be kept out of coding",
        choices=[
            ("", "Select"),
            ("submission_incomplete", "Submission information is incomplete or unusable."),
            ("source_data_mismatch", "Submission content does not match the expected deceased or source data."),
            ("duplicate_submission", "This appears to be a duplicate submission."),
            ("language_unreadable", "Narrative or key data cannot be understood for coding preparation."),
            ("others", "Others"),
        ],
        validators=[
            AnyOf(
                values=[
                    "submission_incomplete",
                    "source_data_mismatch",
                    "duplicate_submission",
                    "language_unreadable",
                    "others",
                ],
                message="Please choose a reason for the data-manager Not Codeable decision.",
            )
        ],
    )
    va_dmreview_other = TextAreaField(
        "Please brief the issue",
        validators=[Optional()],
        render_kw={
            "rows": 2,
            "placeholder": "Brief about the issue here.",
        },
    )
    va_mark_not_codeable = SubmitField("Mark Not Codeable")

    def validate(self, **kwargs):
        if not super().validate(**kwargs):
            return False
        other_text = (self.va_dmreview_other.data or "").strip()
        if self.va_dmreview_reason.data == "others" and not other_text:
            self.va_dmreview_other.errors.append(
                "Please specify the other reason for why this submission should be excluded from coding."
            )
            return False
        return True
