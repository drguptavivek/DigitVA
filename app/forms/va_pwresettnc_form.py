from flask_wtf import FlaskForm
from wtforms import PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, EqualTo, ValidationError

from app.utils.password_policy import password_error_message


def strong_password(form, field):
    error = password_error_message(field.data or "")
    if error:
        raise ValidationError(error)


class VaForcePasswordChangeForm(FlaskForm):
    new_password = PasswordField(
        "New Password",
        validators=[
            DataRequired(),
            EqualTo("confirm_password", message="Passwords must match."),
            strong_password,
        ],
    )
    confirm_password = PasswordField(
        "Confirm New Password", validators=[DataRequired()]
    )
    accept_terms = BooleanField(
        "I agree to the above Terms and Conditions.", validators=[DataRequired()]
    )
    submit = SubmitField("Set New Password")
