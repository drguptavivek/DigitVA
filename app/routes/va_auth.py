from app import db
from app.models import VaUsers
from app.forms import LoginForm
import sqlalchemy as sa
from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user

va_auth = Blueprint("va_auth", __name__)


@va_auth.route("/valogin", methods=["GET", "POST"])
def va_login():
    if current_user.is_authenticated:
        return redirect(
            url_for("va_main.va_dashboard", va_role=current_user.landing_page)
            if current_user.landing_page
            else url_for("va_main.va_index")
        )
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            sa.select(VaUsers).where(VaUsers.email == form.email.data)
        )
        if user is None or not user.check_password(form.password.data):
            flash(
                "Invalid email or password. Please, re-check and login again.",
                "primary",
            )
            return redirect(url_for("va_auth.va_login"))
        login_user(user, remember=form.remember_me.data)
        return redirect(
            url_for("va_main.va_dashboard", va_role=current_user.landing_page)
            if current_user.landing_page
            else url_for("va_main.va_index")
        )
    return render_template("va_frontpages/va_login.html", form=form)


@va_auth.route("/valogout")
def va_logout():
    if current_user.is_anonymous:
        return redirect(url_for("va_main.va_index"))
    logout_user()
    flash("You have been successfully logged out.", "primary")
    return redirect(url_for("va_main.va_index"))