"""Core public routes — index page."""

from flask import Blueprint, render_template

va_main = Blueprint("va_main", __name__)


@va_main.route("/")
@va_main.route("/index")
@va_main.route("/vaindex")
def va_index():
    return render_template("va_frontpages/va_index.html")
