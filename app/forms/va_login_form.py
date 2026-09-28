from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email


class EmailStepForm(FlaskForm):
    """Step 1 of login: email plus the proof-of-work CAPTCHA solution.

    The CAPTCHA fields are filled by app/static/js/pow_captcha.js once the
    browser has solved the challenge; DataRequired here just means "the form
    was actually submitted with a solution attached", not that the solution
    is valid -- pow_captcha_service.verify_challenge does that.
    """

    email = StringField(
        "Email:",
        validators=[
            DataRequired(message="Email is required."),
            Email(message="Please enter a valid email address."),
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
