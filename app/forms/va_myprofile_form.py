from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectMultipleField, SubmitField, SelectField
from wtforms.validators import EqualTo, Length
import pytz

class VaMyprofileForm(FlaskForm):
    va_current_password = PasswordField('Current Password')
    va_new_password = PasswordField('New Password', validators=[
        Length(min=8),
        EqualTo('va_confirm_password', message='New passwords must match while confirming.')
    ])
    va_confirm_password = PasswordField('Confirm New Password')
    va_languages = SelectMultipleField('VA Languages', coerce=str)
    va_timezone = SelectField('Time Zone', choices=[(tz, tz) for tz in pytz.common_timezones])
    va_update_password = SubmitField('Update Password')
    va_update_languages = SubmitField('Update Languages')
    va_update_timezone = SubmitField('Update Time Zone')