from app.utils.number_format import whole_number


def test_an_integral_number_drops_its_decimal_point():
    assert whole_number("28.0") == "28"
    assert whole_number(28.0) == "28"


def test_anything_else_is_returned_as_given():
    assert whole_number("28.5") == "28.5"
    assert whole_number("NaN") == "NaN"
    assert whole_number("n/a") == "n/a"
    assert whole_number("") == ""
    assert whole_number(None) is None
