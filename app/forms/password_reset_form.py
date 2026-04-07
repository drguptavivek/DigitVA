from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, ValidationError

from app.utils.password_policy import password_error_message


def strong_password(form, field):
    error = password_error_message(field.data or "")
    if error:
        raise ValidationError(error)


class ForgotPasswordForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[
            DataRequired(message="Email is required."),
            Email(message="Please enter a valid email address."),
        ],
    )
    submit = SubmitField("Send Reset Link")


class ResetPasswordForm(FlaskForm):
    new_password = PasswordField(
        "New Password",
        validators=[
            DataRequired(),
            EqualTo("confirm_password", message="Passwords must match."),
            strong_password,
        ],
    )
    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[DataRequired()],
    )
    submit = SubmitField("Reset Password")
