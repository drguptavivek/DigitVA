import logging
import sqlalchemy as sa
from app import db, limiter
from app.forms import VaMyprofileForm, VaForcePasswordChangeForm
from app.utils import va_render_serialisedates
from flask_login import login_required, current_user
from app.utils.va_permission.va_permission_01_abortwithflash import (
    va_permission_abortwithflash,
)
from flask import (
    Blueprint,
    render_template,
    flash,
    redirect,
    url_for,
    request
)

va_main = Blueprint("va_main", __name__)
log = logging.getLogger(__name__)


@va_main.route("/")
@va_main.route("/index")
@va_main.route("/vaindex")
def va_index():
    return render_template("va_frontpages/va_index.html")


@va_main.route("/vaprofile", methods=["GET", "POST"])
@login_required
def va_profile():
    form = VaMyprofileForm()
    from app.models.mas_languages import MasLanguages
    languages = db.session.scalars(
        sa.select(MasLanguages).where(MasLanguages.is_active == True).order_by(MasLanguages.language_name)
    ).all()
    form.va_languages.choices = [(l.language_code, l.language_name) for l in languages]

    if form.va_update_password.data and form.validate_on_submit():
        if not form.va_current_password.data or not form.va_new_password.data:
            flash("Please fill all password fields to update.", "warning")
        elif not current_user.check_password(form.va_current_password.data):
            flash("Incorrect current password.", "danger")
        else:
            current_user.set_password(form.va_new_password.data)
            db.session.commit()
            flash("Password updated successfully.", "success")
        return render_template("va_frontpages/va_myprofile.html", form=form)
    elif form.va_update_languages.data:
        current_user.vacode_language = form.va_languages.data
        db.session.commit()
        flash("VA Languages updated successfully.", "success")
        return render_template("va_frontpages/va_myprofile.html", form=form)
    elif form.va_update_timezone.data:
        current_user.timezone = request.form.get('va_timezone')
        db.session.commit()
        flash("Time Zone updated successfully.", "success")
        return render_template("va_frontpages/va_myprofile.html", form=form)

    form.va_languages.data = current_user.vacode_language
    form.va_timezone.data = current_user.timezone
    return render_template("va_frontpages/va_myprofile.html", form=form)


@va_main.route("/force-password-change", methods=["GET", "POST"])
@login_required
@limiter.limit("5 per minute", methods=["POST"])
def force_password_change():
    if current_user.pw_reset_t_and_c:
        return redirect(url_for("coding.dashboard"))
    form = VaForcePasswordChangeForm()
    if form.validate_on_submit():
        current_user.set_password(form.new_password.data)
        current_user.pw_reset_t_and_c = True
        db.session.commit()
        flash("Password updated successfully.", "success")
        return redirect(url_for("coding.dashboard"))
    return render_template("va_form_partials/va_forcepwreset.html", form=form)
