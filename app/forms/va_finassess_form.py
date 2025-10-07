from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField, HiddenField
from wtforms.validators import DataRequired, Optional


class VaFinalAssessmentForm(FlaskForm):
    va_conclusive_cod = HiddenField(
        validators=[DataRequired(message="Final Underlying / Antecedant CauseOfDeath is required.")]
    )
    va_finassess_remark = TextAreaField(
        "Remarks (if any)",
        validators=[Optional()],
        render_kw={
            "rows": 2,
            "placeholder": "Please enter the additional details here, if any.",
        },
    )
    va_save_assessment = SubmitField("Save Assessment")
