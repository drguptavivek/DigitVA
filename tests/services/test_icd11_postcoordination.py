"""WHO scale normalization and axis-bound option navigation."""

from unittest.mock import patch

import pytest

from app.services.icd11_postcoordination import (
    X_CHAPTER_URI,
    PostcoordinationError,
    guidance_request,
    hierarchy,
    postcoordination,
    postcoordination_availability,
    postcoordination_options,
    related_terms,
    search_terms,
    selection_refusal,
    valid_subtree_uris,
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
            "classKind": "category",
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
        "subtree_uris": [LEFT],
        "truncated": False,
    }]
    # Stem is an MMS category outside chapter X: WHO's open-ended "Other
    # postcoordination?" search is offered, scoped to the X chapter root.
    assert result["other_postcoordination"] == {"subtree_uris": [X_CHAPTER_URI]}


def test_other_postcoordination_is_null_for_x_chapter_stem_and_non_category(who):
    entities = _entities()
    entities[ROOT]["code"] = "XA0000"
    with (
        patch(
            "app.services.icd11_postcoordination.get_icd11_codeinfo",
            return_value={"code": "XA0000", "stemId": ROOT},
        ),
        patch("app.services.icd11_postcoordination._entity", side_effect=entities.__getitem__),
    ):
        result = postcoordination("XA0000")
    assert result["other_postcoordination"] is None

    entities = _entities()
    del entities[ROOT]["classKind"]
    with (
        patch(
            "app.services.icd11_postcoordination.get_icd11_codeinfo",
            return_value={"code": "1B12.2", "stemId": ROOT},
        ),
        patch("app.services.icd11_postcoordination._entity", side_effect=entities.__getitem__),
    ):
        result = postcoordination("1B12.2")
    assert result["other_postcoordination"] is None


def test_valid_subtree_uris_accepts_who_uris_and_rejects_the_rest():
    assert valid_subtree_uris(None) is True
    assert valid_subtree_uris([ROOT, LEFT]) is True
    assert valid_subtree_uris([]) is False
    assert valid_subtree_uris(["not-a-uri"]) is False
    assert valid_subtree_uris([ROOT + " "]) is False
    assert valid_subtree_uris(["http://id.who.int/icd/" + "x" * 200]) is False
    assert valid_subtree_uris([ROOT] * 41) is False
    assert valid_subtree_uris("not-a-list") is False


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


def test_search_terms_flags_extension_and_leaf_and_omits_unknown_leaf():
    upstream = type("Upstream", (), {"json": lambda self: {"destinationEntities": [
        {"theCode": "XK8G", "id": "u1", "title": "Left", "isLeaf": True, "chapter": "X"},
        {"theCode": "NC72", "id": "u2", "title": "Fracture of femur", "isLeaf": False, "chapter": "22"},
        {"theCode": "NC72.7", "id": "u3", "title": "Shaft", "isLeaf": True, "chapter": "22"},
        # No isLeaf and no chapter: leaf stays unknown, extension falls back to the code.
        {"theCode": "XA0001", "id": "u4", "title": "Old reply"},
    ]}})()
    with patch("app.services.icd11_postcoordination.proxy_who_icd_request", return_value=upstream):
        items = search_terms("femur")["items"]

    assert [(item["code"], item["extension"], item.get("leaf")) for item in items] == [
        ("XK8G", True, True), ("NC72", False, False), ("NC72.7", False, True), ("XA0001", True, None),
    ]
    assert "leaf" not in items[3]


EXTENSION = "XK8G is an extension code. It cannot be used alone: add it to a stem through + Build."
CATEGORY = "NC72 is a category, not a final code. Choose a more specific code under it."


@pytest.mark.parametrize(("item", "message"), [
    ({"code": "XK8G", "leaf": True, "extension": True}, EXTENSION),
    ({"code": "NC72", "leaf": False, "extension": False}, CATEGORY),
    # The stem of a built expression decides: NC72&XK8G is still a category.
    ({"code": "NC72&XK8G", "leaf": False, "extension": False}, CATEGORY),
    ({"code": "NC72.7", "leaf": True, "extension": False}, None),
    ({"code": "NC72.7&XK8G", "leaf": True, "extension": False}, None),
])
def test_selection_refusal_uses_the_first_stem_flags_without_calling_who(item, message):
    with patch("app.services.icd11_postcoordination._stem") as stem:
        assert selection_refusal(item) == message
    stem.assert_not_called()


def test_selection_refusal_reads_each_further_cluster_stem():
    entities = {"BD54": {"code": "BD54"}, "NC72": {"code": "NC72", "child": ["c"]}}
    with patch(
        "app.services.icd11_postcoordination._stem",
        side_effect=lambda code: ({"code": code}, entities[code]),
    ) as stem:
        assert selection_refusal({"code": "JB64.4/BD54", "leaf": True}) is None
        assert selection_refusal({"code": "JB64.4/NC72&XK8G", "leaf": True}) == CATEGORY
        assert selection_refusal({"code": "JB64.4/XK8G", "leaf": True}) == EXTENSION
    assert [call.args for call in stem.call_args_list] == [("BD54",), ("NC72",)]


WINDOW = "http://id.who.int/icd/release/11/2026-01/mms/500"


def test_uncoded_leaf_axis_root_is_skipped_not_fatal():
    # WHO lists window entities (no code, no children) among scale roots.
    entities = _entities()
    entities[ROOT]["postcoordinationScale"][0]["scaleEntity"] = [WINDOW, LEFT]
    entities[WINDOW] = {
        "code": "", "classKind": "window",
        "title": {"@value": "Neoplasms of the musculoskeletal system"},
        "parent": [], "child": [],
    }
    with (
        patch(
            "app.services.icd11_postcoordination.get_icd11_codeinfo",
            return_value={"code": "1B12.2", "stemId": ROOT},
        ),
        patch("app.services.icd11_postcoordination._entity", side_effect=entities.__getitem__),
    ):
        result = postcoordination("1B12.2")
    axis = result["axes"][0]
    assert [option["uri"] for option in axis["options"]] == [LEFT]
    assert axis["subtree_uris"] == [WINDOW, LEFT]


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


def test_related_terms_returns_who_exact_composite_first():
    stem_uri = "http://id.who.int/icd/release/11/2026-01/mms/500"
    maternal_foundation = "http://id.who.int/icd/entity/999"
    maternal_mms = "http://id.who.int/icd/release/11/2026-01/mms/999"
    entities = {
        stem_uri: {
            "code": "BD54",
            "title": {"@value": "Diabetic foot ulcer"},
            "parent": [],
            "relatedEntitiesInMaternalChapter": [maternal_foundation],
        },
        maternal_mms: {
            "code": "JB64.4",
            "title": {"@value": "Diseases of the circulatory system complicating pregnancy"},
            "child": [],
        },
    }
    with (
        patch(
            "app.services.icd11_postcoordination.get_icd11_codeinfo",
            return_value={"code": "BD54", "stemId": stem_uri},
        ),
        patch("app.services.icd11_postcoordination._entity", side_effect=entities.__getitem__),
    ):
        result = related_terms("BD54", "maternal")
    assert result["composite"] == {
        "code": "JB64.4/BD54",
        "title": "Diseases of the circulatory system complicating pregnancy / Diabetic foot ulcer",
        "uri": "",
    }
    assert result["terms"][0]["code"] == "JB64.4"


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
