"""Display helpers for numbers stored as text."""


def whole_number(value):
    """Shows an integral number without its decimal point: "28.0" -> "28".

    Anything that is not a whole number (a fraction, NaN, infinity, a word,
    None) comes back as it was given, so the caller's own NaN/None checks
    still apply. Used as a Jinja filter and by the workspace API.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return str(int(number)) if number.is_integer() else value
