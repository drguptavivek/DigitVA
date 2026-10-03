from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired

from app.forms.va_login_form import email_if_at


class ForgotPasswordForm(FlaskForm):
    """Also the resend-verification form. A value without ``@`` is a mobile
    number: the link goes to that account's verified email, if it has one;
    a mobile-only account asks its data manager for a code instead."""

    email = StringField(
        "Email or mobile number",
        validators=[
            DataRequired(message="Email is required."),
            email_if_at,
        ],
    )
    submit = SubmitField("Send Reset Link")


class ConfirmLinkForm(FlaskForm):
    """The button behind an emailed link (verify email, reset password,
    factor reset): opening a link changes nothing, so a mail scanner that
    prefetches it cannot; pressing the button POSTs with the CSRF token."""

    submit = SubmitField("Continue")
