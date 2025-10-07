from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField
from wtforms.validators import DataRequired

class VaUsernoteForm(FlaskForm):
    va_note_content = TextAreaField("Note", validators=[DataRequired()])
    va_note_submit = SubmitField("Save Notes")