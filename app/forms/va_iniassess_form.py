from flask_wtf import FlaskForm
from wtforms import SubmitField, HiddenField, SelectMultipleField
from wtforms.validators import DataRequired, Optional


class VaInitialAssessmentForm(FlaskForm):
    va_immediate_cod = HiddenField(
        validators=[DataRequired(message="Immediate CauseOfDeath is required.")]
    )
    va_antecedent_cod = HiddenField(
        validators=[DataRequired(message="Antecedent CauseOfDeath is required.")]
    )
    va_other_conditions = SelectMultipleField(
        "Other significant conditions (if any)",
        validators=[Optional()],
        render_kw={
            "rows": 2,
        },
        coerce=str
    )
    va_save_assessment = SubmitField("Save Assessment")
    va_not_codeable = SubmitField("Not Codeable")