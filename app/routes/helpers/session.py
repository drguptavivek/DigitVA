"""Session guard shared across route packages."""

from functools import wraps

from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required, logout_user

from app.models import VaStatuses


def active_session_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.user_status != VaStatuses.active:
            logout_user()
            flash("Authentication required.", "primary")
            return redirect(url_for("va_auth.va_login", next=request.url))
        return view(*args, **kwargs)

    return wrapped
