"""SmartVA sex code to a word, the one mapping the web templates use (digitva-9cll.22.6)."""


def smartva_gender(value):
    """Shows SmartVA's sex code as a word: 1 -> "Male", 2 -> "Female".

    The stored column keeps the engine's raw value (analytics read it), so
    the mapping happens at display. The phone does the same in
    mobile/digitva-collect/src/smartva/gender.ts. Words and anything else
    come back as given, so the templates' own NaN/None checks still apply.
    """
    try:
        code = float(value)
    except (TypeError, ValueError):
        return value
    return {1.0: "Male", 2.0: "Female"}.get(code, value)
