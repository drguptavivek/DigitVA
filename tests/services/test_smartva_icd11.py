from app.services import smartva_icd11


def test_smartva_icd11_mapping_preserves_full_expression(monkeypatch):
    monkeypatch.setattr(
        smartva_icd11,
        "_crosswalk",
        lambda: {"A00.0": "1A00&XN8P1/1A00", "I21": "BA40"},
    )

    assert smartva_icd11.smartva_icd11_mapping(" a00.0 ") == "1A00&XN8P1/1A00"
    assert smartva_icd11.smartva_icd11_mapping("I21") == "BA40"
    assert smartva_icd11.smartva_icd11_mapping("unknown") is None
    assert smartva_icd11.smartva_icd11_mapping("NaN") is None
