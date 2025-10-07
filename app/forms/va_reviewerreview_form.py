from flask_wtf import FlaskForm
from wtforms import SelectField, TextAreaField, SubmitField
from wtforms.validators import Optional, AnyOf


class VaReviewerReviewForm(FlaskForm):
    va_rreview_narrpos = SelectField(
        "Number of positive symptoms",
        choices=[
            ("", "Select"),
            ("less_than_3", "Less than 3"),
            ("3_5_symptoms", "3 to 5 symptoms"),
            ("greater_than_5", "Greater than 5"),
        ],
        validators=[
            AnyOf(
                values=["less_than_3", "3_5_symptoms", "greater_than_5"],
                message="Please select a valid positive symptom count in submission.",
            )
        ],
    )

    va_rreview_narrneg = SelectField(
        "Presence of negative symptoms",
        choices=[
            ("", "Select"),
            ("present", "Present"),
            ("absent", "Absent"),
        ],
        validators=[
            AnyOf(
                values=["present", "absent"],
                message="Please select if negative symptoms are present in submission.",
            )
        ],
    )

    va_rreview_narrchrono = SelectField(
        "Chronology of events in narration",
        choices=[
            ("", "Select"),
            ("can_be_established", "Can be established"),
            ("cant_be_established", "Cannot be established"),
        ],
        validators=[
            AnyOf(
                values=["can_be_established", "cant_be_established"],
                message="Please select if chronology of events is present in narration.",
            )
        ],
    )

    va_rreview_narrdoc = SelectField(
        "Document review",
        choices=[
            ("", "Select"),
            ("not_present_inconclusive", "Not present or inconclusive"),
            ("provides_data", "Provides data that aid diagnosis"),
        ],
        validators=[
            AnyOf(
                values=["not_present_inconclusive", "provides_data"],
                message="Please select adequate document review.",
            )
        ],
    )

    va_rreview_narrcomorb = SelectField(
        "Information on comorbidities and risk factors",
        choices=[
            ("", "Select"),
            ("present", "Present"),
            ("absent", "Absent"),
        ],
        validators=[
            AnyOf(
                values=["present", "absent"],
                message="Please select if information about comorbidities and risk factors is present.",
            )
        ],
    )

    va_rreview = SelectField(
        "Does the VA form have any serious issues in it's narrative or structured questions and therefore should not be allocated to VA coders for Cause of Death Ascertainment ?",
        choices=[
            ("", "Select"),
            ("accepted", "Accept - No serious issues."),
            ("rejected", "Reject - Serious issues."),
        ],
        validators=[
            AnyOf(
                values=["accepted", "rejected"],
                message="Please select the VA form quality.",
            )
        ],
    )

    va_rreview_fail = TextAreaField(
        "Specify the reason for VA form's rejection",
        validators=[Optional()],
        render_kw={
            "rows": 2,
            "placeholder": "Please specify the reason for rejection here.",
        },
    )

    va_rreview_remark = TextAreaField(
        "Additional remarks (if any)",
        validators=[Optional()],
        render_kw={
            "rows": 2,
            "placeholder": "Please specify the additional details here, if any.",
        },
    )

    def validate(self, **kwargs):
        if not super().validate(**kwargs):
            return False
        if self.va_rreview.data == "rejected" and not self.va_rreview_fail.data.strip():
            self.va_rreview_fail.errors.append(
                "Reason for VA's QA rejection is required."
            )
            return False
        return True

    va_save_review = SubmitField("Save Review")
