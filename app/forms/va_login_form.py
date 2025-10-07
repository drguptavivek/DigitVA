from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email


class LoginForm(FlaskForm):
    email = StringField(
        "Email:",
        validators=[
            DataRequired(message="Email is required."),
            Email(message="Please enter a valid email address."),
        ],
    )
    password = PasswordField(
        "Password:", validators=[DataRequired(message="Password is required.")]
    )
    remember_me = BooleanField("Remember Me")
    submit = SubmitField("Login")