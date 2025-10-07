from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectMultipleField, SubmitField
from wtforms.validators import EqualTo, Length

class VaMyprofileForm(FlaskForm):
    va_current_password = PasswordField('Current Password')
    va_new_password = PasswordField('New Password', validators=[
        Length(min=8),
        EqualTo('va_confirm_password', message='New passwords must match while confirming.')
    ])
    va_confirm_password = PasswordField('Confirm New Password')
    va_languages = SelectMultipleField('VA Languages', coerce=str)
    va_update_password = SubmitField('Update Password')
    va_update_languages = SubmitField('Update Languages')