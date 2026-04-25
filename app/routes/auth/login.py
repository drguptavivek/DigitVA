"""Login and logout routes."""

from urllib.parse import urlparse

import sqlalchemy as sa
from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from app import db, limiter
from app.forms import LoginForm
from app.models import VaStatuses, VaUsers

from .recovery import va_auth


@va_auth.route("/valogin", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit(
    "20 per hour",
    methods=["POST"],
    key_func=lambda: (request.form.get("email") or "").lower().strip(),
)
def va_login():
    if request.method == "POST":
        logout_user()

    if request.method == "GET" and current_user.is_authenticated:
        if current_user.user_status != VaStatuses.active:
            logout_user()
            return redirect(url_for("va_auth.va_login"))
        return redirect(current_user.landing_url())

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

        if not user.email_verified:
            flash("Please verify your email address before logging in.", "email_unverified")
            return redirect(url_for("va_auth.va_login"))

        if user.user_status != VaStatuses.active:
            flash(
                "Invalid email or password. Please, re-check and login again.",
                "primary",
            )
            return redirect(url_for("va_auth.va_login"))

        session.permanent = True
        login_user(user, remember=False)

        next_page = request.args.get("next")
        if not next_page or urlparse(next_page).netloc != "":
            next_page = user.landing_url()

        return redirect(next_page)
    return render_template("va_frontpages/va_login.html", form=form)


@va_auth.route("/valogout", methods=["POST"])
def va_logout():
    if current_user.is_anonymous:
        return redirect(url_for("va_main.va_index"))
    logout_user()
    flash("You have been successfully logged out.", "primary")
    return redirect(url_for("va_main.va_index"))
