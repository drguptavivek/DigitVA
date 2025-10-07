from flask_wtf import FlaskForm
from wtforms import PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length


class VaForcePasswordChangeForm(FlaskForm):
    new_password = PasswordField(
        "New Password",
        validators=[
            DataRequired(),
            Length(min=8),
            EqualTo("confirm_password", message="Passwords must match."),
        ],
    )
    confirm_password = PasswordField(
        "Confirm New Password", validators=[DataRequired()]
    )
    accept_terms = BooleanField(
        "I agree to the above Terms and Conditions.", validators=[DataRequired()]
    )
    submit = SubmitField("Set New Password")