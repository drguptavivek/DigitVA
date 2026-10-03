from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, EqualTo, ValidationError

from app.forms.va_login_form import email_if_at
from app.utils.password_policy import password_error_message


def strong_password(form, field):
    error = password_error_message(field.data or "")
    if error:
        raise ValidationError(error)


class ForgotPasswordForm(FlaskForm):
    """Also the resend-verification form. A value without ``@`` is a mobile
    number: those accounts reset through their data manager instead."""

    email = StringField(
        "Email or mobile number",
        validators=[
            DataRequired(message="Email is required."),
            email_if_at,
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
