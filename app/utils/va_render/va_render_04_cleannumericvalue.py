def va_render_cleannumericvalue(value):
    if isinstance(value, str) and value.endswith(".0"):
        return value[:-2]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value
