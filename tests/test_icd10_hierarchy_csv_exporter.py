from scripts.export_icd10_hierarchy_csv import (
    DEFAULT_XML_PATH,
    _load_classes,
    _row_for_code,
)


def test_xml_exporter_expands_modifier_derived_codes():
    classes, _ = _load_classes(DEFAULT_XML_PATH)

    for code in ("V01.1", "V10.4", "V90.0", "E10.0", "I70.0"):
        assert code in classes
    assert "V01-X59.0" not in classes

    v011 = _row_for_code("V01.1", classes)
    assert v011["node_type"] == "modifiedcategory"
    assert v011["semantic_level"] == "detailed_code"
    assert v011["parent_code"] == "V01"
    assert v011["three_character_code"] == "V01"
    assert v011["title"] == (
        "Pedestrian injured in collision with pedal cycle : Traffic accident"
    )

    v104 = _row_for_code("V10.4", classes)
    assert v104["parent_code"] == "V10"
    assert v104["three_character_code"] == "V10"
    assert "Driver injured in traffic accident" in v104["title"]

    v900 = _row_for_code("V90.0", classes)
    assert v900["parent_code"] == "V90"
    assert v900["three_character_code"] == "V90"
    assert "merchant ship" in v900["title"].lower()

    i700 = _row_for_code("I70.0", classes)
    assert i700["parent_code"] == "I70"
    assert i700["three_character_code"] == "I70"
