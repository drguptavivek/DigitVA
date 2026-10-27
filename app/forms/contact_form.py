from flask_wtf import FlaskForm
from wtforms import HiddenField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length

# Topic codes are the only part of the form that may appear in a URL
# (``/contact?topic=deletion``); labels go into the delivered email's subject.
CONTACT_TOPICS = [
    ("general", "General question"),
    ("consent", "Consent change or withdrawal"),
    ("deletion", "Data deletion request"),
    ("technical", "Technical problem"),
]


class ContactForm(FlaskForm):
    """The public contact form (docs/policy/public-privacy-and-data-requests.md
    section 7). ``website`` is a honeypot hidden from people; the captcha_*
    fields are the proof-of-work CAPTCHA (filled by app/static/js/
    pow_captcha.js) and the slide_* fields the slide-to-slot puzzle (filled by
    app/static/js/slide_captcha.js). DataRequired on them only means a
    solution was attached; the services check it."""

    name = StringField(
        "Your name",
        validators=[DataRequired(message="Please enter your name."), Length(max=100)],
    )
    email = StringField(
        "Your email address",
        validators=[
            DataRequired(message="Please enter your email address."),
            Length(max=254),
            Email(message="Please enter a valid email address."),
        ],
    )
    topic = SelectField("Topic", choices=CONTACT_TOPICS, default="general")
    message = TextAreaField(
        "Message",
        validators=[
            DataRequired(message="Please write a message."),
            Length(max=4000, message="Please keep the message under 4000 characters."),
        ],
    )
    website = StringField("Leave this field empty")
    captcha_salt = HiddenField(validators=[DataRequired()])
    captcha_difficulty = HiddenField(validators=[DataRequired()])
    captcha_expires = HiddenField(validators=[DataRequired()])
    captcha_signature = HiddenField(validators=[DataRequired()])
    captcha_solution = HiddenField(validators=[DataRequired()])
    slide_id = HiddenField(validators=[DataRequired()])
    slide_x = HiddenField(validators=[DataRequired()])
    slide_ms = HiddenField(validators=[DataRequired()])
    slide_moves = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Send")
