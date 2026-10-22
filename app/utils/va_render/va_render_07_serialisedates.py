def va_render_serialisedates(row, date_fields):
    row_dict = dict(row)
    for key in date_fields:
        value = row_dict.get(key)
        if value:
            row_dict[key] = value.strftime("%Y-%m-%d")
        else:
            row_dict[key] = ""
    return row_dict


def va_user_timezone_name(user):
    """The user's IANA timezone name, or the app default when unset/invalid.

    Mirrors ``app._current_user_timezone`` so a list shows the same day the
    ``user_timezone`` template filter does.
    """
    import pytz

    name = getattr(user, "timezone", None) or "Asia/Kolkata"
    try:
        return pytz.timezone(name).zone
    except pytz.UnknownTimeZoneError:
        return "Asia/Kolkata"


def va_local_date(column, tz_name):
    """SQL calendar date of a naive-UTC *column* in *tz_name* (bound parameter).

    ``timezone('UTC', col)`` makes the naive value a timestamptz, the outer
    ``timezone(tz, ...)`` converts it back to local wall time.
    """
    import sqlalchemy as sa

    return sa.func.date(sa.func.timezone(tz_name, sa.func.timezone("UTC", column)))
