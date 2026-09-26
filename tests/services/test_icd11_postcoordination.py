"""WHO scale normalization and axis-bound option navigation."""

from unittest.mock import patch

import pytest

from app.services.icd11_postcoordination import (
    PostcoordinationError,
    guidance_request,
    hierarchy,
    postcoordination,
    postcoordination_availability,
    postcoordination_options,
)

ROOT = "http://id.who.int/icd/release/11/2026-01/mms/100"
LEFT = "http://id.who.int/icd/release/11/2026-01/mms/200"
CHILD = "http://id.who.int/icd/release/11/2026-01/mms/300"
FOREIGN = "http://id.who.int/icd/release/11/2026-01/mms/400"
AXIS = "http://id.who.int/icd/schema/specificAnatomy"


def _entities():
    return {
        ROOT: {
            "code": "1B12.2",
            "title": {"@value": "Tuberculosis of ear"},
            "postcoordinationScale": [{
                "axisName": AXIS,
                "requiredPostcoordination": "true",
                "allowMultipleValues": "AllowedExceptFromSameBlock",
                "scaleEntity": [LEFT],
            }],
            "parent": [],
            "child": [FOREIGN],
            "indexTerm": [{"label": {"@value": "<b>Ear tuberculosis</b>"}}],
            "relatedEntitiesInMaternalChapter": [],
            "relatedEntitiesInPerinatalChapter": [],
        },
        LEFT: {
            "code": "", "title": {"@value": "Inner ear"},
            "parent": [], "child": [CHILD],
        },
        CHILD: {
            "code": "XA3MS6", "title": {"@value": "Cochlea"},
            "parent": [LEFT], "child": [],
        },
        FOREIGN: {
            "code": "XA0000", "title": {"@value": "Foreign"},
            "parent": [], "child": [],
        },
    }


@pytest.fixture
def who():
    with (
        patch(
            "app.services.icd11_postcoordination.get_icd11_codeinfo",
            return_value={"code": "1B12.2", "stemId": ROOT},
        ),
        patch("app.services.icd11_postcoordination._entity", side_effect=_entities().__getitem__),
    ):
        yield


def test_postcoordination_preserves_who_axis_order_and_required_flags(who):
    result = postcoordination("1B12.2")
    assert result["release"] == "2026-01"
    assert result["stem"]["code"] == "1B12.2"
    assert result["axes"] == [{
        "id": "specificAnatomy",
        "label": "Specific anatomy",
        "required": True,
        "instruction": "use additional code",
        "allow_multiple": True,
        "allow_multiple_values": "AllowedExceptFromSameBlock",
        "options": [{
            "code": "", "title": "Inner ear", "uri": LEFT,
            "has_children": True, "block_uri": LEFT,
        }],
        "truncated": False,
    }]


def test_options_accept_axis_descendant_and_reject_foreign_parent(who):
    result = postcoordination_options("1B12.2", "specificAnatomy", LEFT)
    assert result["items"][0]["code"] == "XA3MS6"
    assert result["items"][0]["block_uri"] == LEFT
    assert postcoordination_options("1B12.2", "specificAnatomy", CHILD)["items"] == []
    with pytest.raises(PostcoordinationError, match="outside the selected axis"):
        postcoordination_options("1B12.2", "specificAnatomy", FOREIGN)
    with pytest.raises(PostcoordinationError, match="Invalid WHO entity URI"):
        postcoordination_options("1B12.2", "specificAnatomy", "https://evil.example/400")


def test_hierarchy_uses_only_who_terms_and_bounded_children(who):
    result = hierarchy("1B12.2")
    assert result["selected"]["uri"] == ROOT
    assert result["matching_terms"] == ["Ear tuberculosis"]
    assert result["children"][0]["uri"] == FOREIGN
    assert result["related_maternal"] == []
    assert result["related_perinatal"] == []


def test_search_availability_does_not_infer_from_leaf_or_expression():
    assert postcoordination_availability(0) == (False, 0)
    assert postcoordination_availability(1) == (True, 1)
    assert postcoordination_availability(2) == (True, 2)
    assert postcoordination_availability("2") == (False, None)


def test_too_many_axis_roots_are_explicitly_truncated():
    entities = _entities()
    entities[ROOT]["postcoordinationScale"][0]["scaleEntity"] = [LEFT] * 13
    with (
        patch(
            "app.services.icd11_postcoordination.get_icd11_codeinfo",
            return_value={"code": "1B12.2", "stemId": ROOT},
        ),
        patch("app.services.icd11_postcoordination._entity", side_effect=entities.__getitem__),
    ):
        result = postcoordination("1B12.2")
    assert result["axes"][0]["truncated"] is True
    assert len(result["axes"][0]["options"]) == 12


def test_complete_expression_hierarchy_resolves_stem_and_retains_context():
    def codeinfo(code):
        if code == "1B12.2/5A13":
            return {"code": code, "stemCode": "1B12.2", "stemId": ROOT}
        return {"code": "1B12.2", "stemId": ROOT}

    with (
        patch("app.services.icd11_postcoordination.get_icd11_codeinfo", side_effect=codeinfo),
        patch("app.services.icd11_postcoordination._entity", side_effect=_entities().__getitem__),
    ):
        result = hierarchy("1B12.2/5A13")
    assert result["selected"]["code"] == "1B12.2"
    assert result["selected_expression"] == {
        "code": "1B12.2/5A13", "stem_code": "1B12.2"
    }


def test_guidance_capacity_is_separate_and_nonblocking():
    with patch(
        "app.services.icd11_postcoordination._guidance_capacity.acquire",
        return_value=False,
    ):
        with pytest.raises(PostcoordinationError) as error:
            with guidance_request():
                pass
    assert error.value.code == "GUIDANCE_BUSY"
    assert error.value.status == 429
