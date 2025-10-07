from datetime import datetime


def va_render_standardizedate(date_str):
    if not date_str:
        return ""
    try:
        if "T" in date_str:
            date_part = date_str.split("T")[0]
            dt = datetime.strptime(date_part, "%Y-%m-%d")
        else:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d-%m-%Y")
    except Exception as e:
        print(f"Error parsing date '{date_str}': {e}")
        return date_str
