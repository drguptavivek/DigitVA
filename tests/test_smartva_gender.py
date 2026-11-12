from app.utils.smartva_gender import smartva_gender


def test_maps_smartva_codes_to_words():
    assert smartva_gender("1") == "Male"
    assert smartva_gender("2") == "Female"
    assert smartva_gender(2.0) == "Female"


def test_leaves_words_missing_and_unknown_codes_alone():
    assert smartva_gender("Female") == "Female"
    assert smartva_gender(None) is None
    assert smartva_gender("NaN") == "NaN"
    assert smartva_gender("9") == "9"
