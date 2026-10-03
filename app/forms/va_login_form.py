from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length


def email_if_at(form, field):
    """A value containing ``@`` must be a valid email; anything else is read
    as a mobile number and never refused here (docs/policy/mobile-sign-in.md
    section 2: an invalid number gets the same next page as a valid one)."""
    if "@" in (field.data or ""):
        Email(message="Please enter a valid email address.")(form, field)


class EmailStepForm(FlaskForm):
    """Step 1 of login: email or mobile number plus the proof-of-work CAPTCHA
    solution.

    The CAPTCHA fields are filled by app/static/js/pow_captcha.js once the
    browser has solved the challenge; DataRequired here just means "the form
    was actually submitted with a solution attached", not that the solution
    is valid -- pow_captcha_service.verify_challenge does that.
    """

    email = StringField(
        "Email or mobile number:",
        validators=[
            DataRequired(message="Email or mobile number is required."),
            email_if_at,
        ],
    )
    captcha_salt = HiddenField(validators=[DataRequired()])
    captcha_difficulty = HiddenField(validators=[DataRequired()])
    captcha_expires = HiddenField(validators=[DataRequired()])
    captcha_signature = HiddenField(validators=[DataRequired()])
    captcha_solution = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Continue")


class PasswordStepForm(FlaskForm):
    """Step 2 of login: the password form shown alongside the passkey button."""

    password = PasswordField(
        "Password:", validators=[DataRequired(message="Password is required.")]
    )
    remember_me = BooleanField("Remember Me")
    submit = SubmitField("Login")


class SecondFactorForm(FlaskForm):
    """Step 3 of login, only for users who must give a second factor (docs/
    policy/authentication-factors.md section 3): a TOTP code or a recovery
    code, accepted in either field."""

    code = StringField(
        "Code:", validators=[DataRequired(message="Code is required.")]
    )
    submit = SubmitField("Verify")


class RedeemCodeForm(FlaskForm):
    """"I have a code": a mobile-only account's number and the one-time code
    its data manager gave it, plus the same proof-of-work CAPTCHA as the
    email step (docs/policy/mobile-sign-in.md section 3)."""

    mobile = StringField(
        "Mobile number:",
        validators=[DataRequired(message="Mobile number is required."), Length(max=32)],
    )
    code = StringField(
        "Code:", validators=[DataRequired(message="Code is required."), Length(max=32)]
    )
    captcha_salt = HiddenField(validators=[DataRequired()])
    captcha_difficulty = HiddenField(validators=[DataRequired()])
    captcha_expires = HiddenField(validators=[DataRequired()])
    captcha_signature = HiddenField(validators=[DataRequired()])
    captcha_solution = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Get my password")
