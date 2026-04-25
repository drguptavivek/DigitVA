from flask import abort, flash


def va_permission_abortwithflash(message, code):
    flash(message, "primary")
    abort(code)
