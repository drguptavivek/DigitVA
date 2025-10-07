def va_render_serialisedates(row, date_fields):
    row_dict = dict(row)
    for key in date_fields:
        value = row_dict.get(key)
        if value:
            row_dict[key] = value.strftime("%Y-%m-%d")
        else:
            row_dict[key] = ""
    return row_dict
