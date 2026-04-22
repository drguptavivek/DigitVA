"""User profile and account management routes — /profile/"""

from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user

from app import db, limiter
from app.forms import VaForcePasswordChangeForm
from app.models import VaStatuses

profile = Blueprint("profile", __name__)


def _active_session_required(f):
    @wraps(f)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.user_status != VaStatuses.active:
            logout_user()
            flash("Authentication required.", "primary")
            return redirect(url_for("va_auth.va_login", next=request.url))
        return f(*args, **kwargs)

    return wrapped


@profile.get("/")
@_active_session_required
def view():
    """Render the profile page (data loaded via API)."""
    import pytz
    return render_template("va_frontpages/va_myprofile.html", timezones=pytz.common_timezones)


@profile.route("/force-password-change", methods=["GET", "POST"])
@_active_session_required
@limiter.limit("5 per minute", methods=["POST"])
def force_password_change():
    if current_user.pw_reset_t_and_c:
        return redirect(url_for("coding.dashboard"))
    form = VaForcePasswordChangeForm()
    if form.validate_on_submit():
        current_user.pw_reset_t_and_c = True
        db.session.commit()
        flash("Terms accepted successfully.", "success")
        return redirect(url_for("coding.dashboard"))
    return render_template("va_form_partials/va_forcepwreset.html", form=form)
