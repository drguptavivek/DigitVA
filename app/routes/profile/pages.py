"""User profile pages."""

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user

from app import db, limiter
from app.forms import VaForcePasswordChangeForm
from app.routes.helpers import active_session_required

profile = Blueprint("profile", __name__)


@profile.get("/")
@active_session_required
def view():
    import pytz

    return render_template(
        "va_frontpages/va_myprofile.html",
        timezones=pytz.common_timezones,
    )


@profile.route("/force-password-change", methods=["GET", "POST"])
@active_session_required
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
