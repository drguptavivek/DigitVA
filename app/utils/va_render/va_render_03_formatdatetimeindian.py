from datetime import datetime


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
