from flask_wtf import FlaskForm
from wtforms import BooleanField, SubmitField
from wtforms.validators import DataRequired


class VaForcePasswordChangeForm(FlaskForm):
    accept_terms = BooleanField(
        "I agree to the above Terms and Conditions.", validators=[DataRequired()]
    )
    submit = SubmitField("Continue")
