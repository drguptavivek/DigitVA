"""Public privacy policy, contact us, and consent and data requests pages.

Policy: docs/policy/public-privacy-and-data-requests.md. No sign-in.
``/privacy`` and ``/data-requests`` are GET only with no form. ``/contact``
also carries the contact form (section 7): a normal POST with CSRF, the
proof-of-work CAPTCHA, the slide-to-slot puzzle and email confirmation via
``/contact/confirm/<token>``. Organisation details come from config; unset
values render neutral wording, never a placeholder.
"""

import hashlib

from flask import Blueprint, current_app, render_template, request

from app import limiter
from app.forms import ConfirmLinkForm, ContactForm
from app.forms.contact_form import CONTACT_TOPICS
from app.services import contact_form_service, email_service, slide_captcha_service
from app.services.pow_captcha_service import verify_challenge as verify_pow_challenge

public_pages = Blueprint("public_pages", __name__)

_DEFAULT_ORG = "the DigitVA programme team"
_TOPIC_LABELS = dict(CONTACT_TOPICS)
_CAPTCHA_FIELDS = (
    "captcha_salt", "captcha_difficulty", "captcha_expires", "captcha_signature",
    "captcha_solution", "slide_id", "slide_x", "slide_ms", "slide_moves",
)
_CAPTCHA_ERROR = "We could not check the puzzle. Please slide the piece into the gap again and send."


def _org():
    cfg = current_app.config
    return {
        "name": cfg.get("PUBLIC_ORG_NAME") or _DEFAULT_ORG,
        "email": cfg.get("PUBLIC_CONTACT_EMAIL") or "",
        "grievance_officer": cfg.get("PUBLIC_GRIEVANCE_OFFICER") or "",
        "address": cfg.get("PUBLIC_POSTAL_ADDRESS") or "",
    }


def _page(template):
    response = current_app.make_response(render_template(template, org=_org()))
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


def _private(body):
    """A page carrying a CSRF token, a captcha challenge or a link token:
    never cached. (The app-wide strict-origin-when-cross-origin referrer
    policy already keeps the token path from other sites.)"""
    response = current_app.make_response(body)
    response.headers["Cache-Control"] = "no-store"
    return response


def _contact_email_key():
    """Per-sender limiter key: a hash of the posted address, so the limiter
    store never holds the address itself. Plus-tags, and dots for Gmail, are
    folded so one inbox shares one bucket."""
    email = (request.form.get("email") or "").strip().lower()
    local, at, domain = email.partition("@")
    if at:
        local = local.split("+", 1)[0]
        if domain in ("gmail.com", "googlemail.com"):
            local, domain = local.replace(".", ""), "gmail.com"
        email = f"{local}@{domain}"
    return "contact:" + hashlib.sha256(email.encode("utf-8")).hexdigest()


_SENT_FLAG = "digitva.contact_confirmation_started"


def _contact_sent_counts(_response):
    """Count only submissions that queued a confirmation email. The flag
    lives on this request's WSGI environ, not ``g``, which the test suite's
    pushed app context shares across requests."""
    return bool(request.environ.get(_SENT_FLAG))


def _render_contact(**context):
    return _private(render_template("va_frontpages/va_public_contact.html", org=_org(), **context))


def _render_contact_form(form, error=None):
    """The form with a fresh puzzle; any posted captcha values are dropped."""
    for name in _CAPTCHA_FIELDS:
        form[name].data = ""
    challenge = slide_captcha_service.issue_challenge()
    form.slide_id.data = challenge["challenge_id"]
    geometry = {
        "width": slide_captcha_service.WIDTH,
        "height": slide_captcha_service.HEIGHT,
        "piece": slide_captcha_service.PIECE,
        "track": slide_captcha_service.TRACK,
    }
    return _render_contact(form=form, slide=challenge, geometry=geometry, error=error)


@public_pages.get("/privacy")
def privacy():
    return _page("va_frontpages/va_public_privacy.html")


@public_pages.route("/contact", methods=["GET", "POST"])
# Every GET issues a puzzle into the cache, so GETs are limited too.
@limiter.limit("30 per minute", methods=["GET"])
@limiter.limit("5 per minute", methods=["POST"])
@limiter.limit("20 per hour", methods=["POST"])
@limiter.limit("3 per hour", methods=["POST"], key_func=_contact_email_key, deduct_when=_contact_sent_counts)
def contact():
    """Contact details, plus the form when ``PUBLIC_CONTACT_EMAIL`` is set and
    mail is configured (otherwise the confirmation link could never arrive).
    Every valid submission gets the same neutral reply; a filled honeypot
    gets it too, with nothing stored or sent."""
    if not _org()["email"] or not email_service.is_mail_configured():
        if request.method == "POST":
            return _render_contact(refused=True)
        return _page("va_frontpages/va_public_contact.html")

    form = ContactForm()
    if request.method == "GET":
        topic = request.args.get("topic")
        if topic in _TOPIC_LABELS:
            form.topic.data = topic
        return _render_contact_form(form)

    if form.website.data:
        return _render_contact(sent=True)
    if not form.validate_on_submit():
        return _render_contact_form(form)

    # Both checks always run, so a submission always spends its puzzle.
    pow_ok = verify_pow_challenge(
        salt=form.captcha_salt.data,
        difficulty=form.captcha_difficulty.data,
        expires=form.captcha_expires.data,
        signature=form.captcha_signature.data,
        solution=form.captcha_solution.data,
    )
    slide_ok = slide_captcha_service.verify_challenge(
        challenge_id=form.slide_id.data,
        x=form.slide_x.data,
        duration_ms=form.slide_ms.data,
        moves=form.slide_moves.data,
    )
    if not (pow_ok and slide_ok):
        return _render_contact_form(form, error=_CAPTCHA_ERROR)

    contact_form_service.start(
        name=form.name.data.strip(),
        email=form.email.data.strip(),
        topic=form.topic.data,
        topic_label=_TOPIC_LABELS[form.topic.data],
        message=form.message.data,
    )
    request.environ[_SENT_FLAG] = True
    return _render_contact(sent=True)


@public_pages.route("/contact/confirm/<token>", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def contact_confirm(token):
    """Opening the emailed link only shows a button, so a mail scanner that
    prefetches it sends nothing; the POST (CSRF) delivers the message once.
    Unknown, expired and used links all get the same neutral page."""
    if request.method == "POST":
        state = "sent" if contact_form_service.confirm(token) else "invalid"
    else:
        state = "ready" if contact_form_service.is_pending(token) else "invalid"
    return _private(render_template(
        "va_frontpages/va_public_contact_confirm.html",
        form=ConfirmLinkForm(), token=token, state=state, org=_org(),
    ))


@public_pages.get("/data-requests")
def data_requests():
    return _page("va_frontpages/va_public_data_requests.html")
