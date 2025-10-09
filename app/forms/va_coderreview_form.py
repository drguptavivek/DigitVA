from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField, SelectField
from wtforms.validators import AnyOf, Optional


class VaCoderReviewForm(FlaskForm):
    va_creview_reason = SelectField(
        "Please describe the reason for why the VA form could not be coded",
        choices=[
            ("", "Select"),
            ("narration_language", "I cannot read this narrative language."),
            ("narration_doesnt_match", "Narrative content doesn't match with the deceased whose VA form has been filled"),
            ("no_info", "There is no information available in Questions as well as Narration"),
            ("others", "Others")
        ],
        validators=[
            AnyOf(
                values=["narration_language", "narration_doesnt_match", "no_info", "form_is_empty", "others"],
                message="Please describe the reason for why the VA form could not be coded.",
            )
        ],
    )
    va_creview_other = TextAreaField(
        "Please brief the other issue",
        validators=[Optional()],
        render_kw={
            "rows": 2,
            "placeholder": "Brief about the issue here.",
        },
    )
    def validate(self, **kwargs):
        if not super().validate(**kwargs):
            return False
        if self.va_creview_reason.data == "others" and not self.va_creview_other.data.strip():
            self.va_creview_other.errors.append(
                "Please specify the other reason for why this VA form could not be coded."
            )
            return False
        return True
    va_report_issue = SubmitField("Report Issue")