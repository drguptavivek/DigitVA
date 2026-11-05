import re
from datetime import datetime

# An ODK `time` answer: 10:08:00.000+05:30 (offset and fraction optional).
_ODK_TIME_RE = re.compile(r"^(\d{2}:\d{2}):\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$")


def va_render_formattime(value):
    """An ODK time answer as HH:MM; any other value comes back unchanged."""
    match = _ODK_TIME_RE.match(value) if isinstance(value, str) else None
    return match.group(1) if match else value


def va_render_formatdatetimeindian(dt_string):
    if not dt_string or not isinstance(dt_string, str):
        return dt_string
    try:
        if "Z" in dt_string:
            dt_string = dt_string.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt_string)
        return dt.strftime("%d-%m-%Y %H:%M")
        # use the following for the 12 hour am-pm format if required
        # return dt.strftime("%d-%m-%Y %I:%M %p")
    except Exception as e:
        print(f"Error formatting datetime: {e}")
        return dt_string
