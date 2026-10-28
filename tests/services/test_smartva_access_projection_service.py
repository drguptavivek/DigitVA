import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import mock

from app.services import smartva_access_projection_service as projection


def _form(**changes):
    values = {
        "form_id": "FORM001",
        "project_id": "P1",
        "site_id": "S1",
        "form_updated_at": datetime(2026, 10, 28, tzinfo=UTC),
        "form_smartvahiv": "False",
        "form_smartvamalaria": "True",
        "form_smartvahce": "True",
        "form_smartvafreetext": "False",
    }
    return SimpleNamespace(**(values | changes))


def test_options_use_each_area_preset_and_fallback_only_the_missing_field():
    options = projection._form_options(
        _form(), "KEN", {"hiv_mortality": {"value": "high"}},
    )

    assert options == {"country": "KEN", "hiv": True, "malaria": True, "hce": True, "freetext": False}


def test_malformed_form_flags_and_presets_fail_closed():
    try:
        projection._form_options(_form(form_smartvahce="TRUE"), "IND", {})
    except ValueError:
        pass
    else:
        raise AssertionError("malformed HCE flag was accepted")

    try:
        projection._form_options(_form(), "IND", {"hiv_mortality": {"value": "medium"}})
    except ValueError:
        pass
    else:
        raise AssertionError("malformed area preset was accepted")


def test_digest_is_deterministic_and_binds_form_revision():
    options = {"country": "IND", "hiv": True, "malaria": False, "hce": True, "freetext": False}
    timestamp = "2026-10-28T00:00:00Z"

    first = projection._options_digest("FORM001", timestamp, options)
    assert first == projection._options_digest("FORM001", timestamp, dict(reversed(list(options.items()))))
    assert first.startswith("sha256:")
    assert first != projection._options_digest("FORM001", "2026-10-29T00:00:00Z", options)


def test_batch_resolves_unit_presets_once_and_omits_missing_or_ambiguous_forms():
    unit_id = uuid.uuid4()
    second_unit_id = uuid.uuid4()
    form = _form()
    second_form = _form(form_id="FORM002", site_id="S2")
    project = SimpleNamespace(project_id="P1")
    form_rows = mock.Mock()
    form_rows.all.return_value = [form, second_form]
    project_rows = mock.Mock()
    project_rows.all.return_value = [project]
    with mock.patch.object(projection.db.session, "scalars", side_effect=[form_rows, project_rows]) as queries, \
            mock.patch.object(projection, "resolve_unit_va_presets", return_value={unit_id: {}, second_unit_id: {}}) as presets, \
            mock.patch("app.utils.va_smartva.va_smartva_03_runsmartva.smartva_country", return_value="IND"):
        resolved = projection.build_smartva_targets([
            ("P1", "S1", str(unit_id)), ("P1", "S2", str(second_unit_id)),
        ])

    presets.assert_called_once_with(sorted([unit_id, second_unit_id]))
    assert queries.call_count == 2
    target = resolved[("P1", "S1", str(unit_id))]
    assert target["form_id"] == "FORM001"
    assert target["org_unit_id"] == str(unit_id)
    assert resolved[("P1", "S2", str(second_unit_id))]["form_id"] == "FORM002"

    for rows in ([], [form, form]):
        form_rows = mock.Mock()
        form_rows.all.return_value = rows
        with mock.patch.object(projection.db.session, "scalars", return_value=form_rows), \
                mock.patch.object(projection, "resolve_unit_va_presets") as resolve_presets:
            assert projection.build_smartva_targets([("P1", "S1", str(unit_id))]) == {}
        resolve_presets.assert_not_called()
