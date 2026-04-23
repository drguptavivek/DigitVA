"""Auth-local helpers shared by login and recovery routes."""

from flask import flash, redirect, url_for


def inactive_account_response():
    flash("This account is inactive. Please contact an administrator.", "danger")
    return redirect(url_for("va_auth.va_login"))
