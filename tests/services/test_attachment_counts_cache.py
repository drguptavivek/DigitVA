from unittest.mock import Mock, patch

from app.services.coding_service import _count_attachments_per_category


def _mapping_service():
    service = Mock()
    service.get_fieldsitepi.return_value = {
        "disease": {"images": {"photo_1": "Photo"}},
    }
    service.get_subcategory_render_modes.return_value = {
        "images": "media_gallery",
    }
    return service


def _count_calls(payloads, *, form_type_code="WHO_2022_VA"):
    cache_values = {}
    cache = Mock()
    cache.get.side_effect = cache_values.get
    cache.set.side_effect = lambda key, value, timeout: cache_values.__setitem__(key, value)
    mapping_service = _mapping_service()

    with (
        patch("app.cache", cache),
        patch(
            "app.services.field_mapping_service.get_mapping_service",
            return_value=mapping_service,
        ),
    ):
        results = [
            _count_attachments_per_category(form_type_code, payload, "SID-1")
            for payload in payloads
        ]

    return results, cache, cache_values


def test_attachment_add_remove_for_same_sid_uses_fresh_counts():
    results, cache, _ = _count_calls([{}, {"photo_1": "attachment"}, {}])

    assert results == [{}, {"disease": 1}, {}]
    cache.get.assert_not_called()
    cache.set.assert_not_called()


def test_repeated_payload_returns_stable_counts_and_ignores_unrelated_changes():
    results, cache, _ = _count_calls(
        [{"photo_1": "attachment", "unrelated": "first"}, {"photo_1": "attachment", "unrelated": "second"}]
    )

    assert results == [{"disease": 1}, {"disease": 1}]
    cache.get.assert_not_called()
    cache.set.assert_not_called()


def test_form_type_isolation_passes_each_form_type_to_mapping_service():
    cache_values = {}
    cache = Mock()
    cache.get.side_effect = cache_values.get
    cache.set.side_effect = lambda key, value, timeout: cache_values.__setitem__(key, value)
    mapping_service = _mapping_service()

    with (
        patch("app.cache", cache),
        patch(
            "app.services.field_mapping_service.get_mapping_service",
            return_value=mapping_service,
        ),
    ):
        first = _count_attachments_per_category("WHO_2022_VA", {"photo_1": "attachment"}, "SID-1")
        second = _count_attachments_per_category("PHMRC", {"photo_1": "attachment"}, "SID-1")

    assert first == second == {"disease": 1}
    cache.get.assert_not_called()
    cache.set.assert_not_called()
    assert [call.args[0] for call in mapping_service.get_fieldsitepi.call_args_list] == [
        "WHO_2022_VA",
        "PHMRC",
    ]
