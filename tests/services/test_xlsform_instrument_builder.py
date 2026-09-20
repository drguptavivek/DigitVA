"""Conformance of the XLSForm -> instrument converter.

The WHO 2022 workbook ships alongside the hand-audited instrument JSON built
from it, so conversion accuracy can be measured rather than asserted: rebuild
the instrument from the workbook and compare it field by field to the package's
own.

Everything that still differs is the package deliberately departing from its
source workbook. Those departures are enumerated in DEVIATIONS below, which
doubles as the record of what the vendored instrument changed and why — and as
a tripwire: if a future vendor merge changes one, this test says so.

`ast` is excluded from the comparison. The package precomputes an expression
AST next to each expression's source; the converter emits source only, which
the runtime parses on demand (it verifies a supplied AST against its source
anyway). Same semantics, less to keep in step.
"""

import json
from pathlib import Path

from app.services.xlsform_instrument_builder import (
    XlsFormConversionError,
    build_instrument_from_xlsform,
)
from tests.base import BaseTestCase


REPO_ROOT = Path(__file__).resolve().parents[2]
XLSFORM = REPO_ROOT / "vendor/who-va-2022/2022whova_xls_form_for_odk_multilingual.xlsx"
INSTRUMENT = REPO_ROOT / "vendor/who-va-2022/src/generated/who-va-2022.instrument.json"

# The instrument moved to this workbook (V2.0, English only) 2026-09-20;
# see docs/policy/va-form-project-configuration.md, "The curated reference
# form moves to V2.0, English only" (digitva-13x).
LOCALES = {"en"}

# question name -> the field paths where the package departs from the workbook.
# Every entry predates digitva-13x except the last two (see
# vendor/who-va-2022/README.md, "Deliberate departures from the WHO
# XLSForm"); none are resolved by the move to V2.0 -- the raw V2.0 workbook
# still carries the same issue each one works around. Kept in step with
# tooling/who-va-2022/build-instrument-from-xlsform.py, which applies them.
DEVIATIONS = {
    # Documented in the package README.
    "Id10365": {"constraint", "validation.constraint", "constraintMessage.en",
                "validation.constraintMessage.en"},  # source constraint dropped: it
                                                     # rejects a valid birth weight
    "Id10382": {"constraint.source", "validation.constraint.source",
                "constraintMessage.en", "validation.constraintMessage.en"},  # 99 = "do not know"
    "Id10023_a": {"constraintMessage.en", "validation.constraintMessage.en"},  # clearer message
    "Id10023_b": {"constraintMessage.en", "validation.constraintMessage.en"},  # clearer message
    "nmh": {"sectionPath"},  # moved under injuries_accidents so the guidance
                             # appears with that section
    "language": {"choices", "validation.choiceValues"},  # package ships English only
    # Not documented in the README — surfaced by this comparison.
    "Id10007": {"constraint", "validation.constraint", "constraintMessage.en",
                "validation.constraintMessage.en"},  # app-added name regex
    "Id10010": {"constraint", "validation.constraint", "constraintMessage.en",
                "validation.constraintMessage.en"},  # app-added name regex
    "Id10477": {"choices", "validation.choiceValues"},  # package choice list differs
    "Id10478": {"choices", "validation.choiceValues"},
    "Id10479": {"choices", "validation.choiceValues"},
    # digitva-13x, decided in docs/policy/va-form-project-configuration.md:
    # V2.0's relevant is unsatisfiable (id10304a-v2-relevance-defect.md).
    "Id10304_a": {"relevant.source"},
    # digitva-13x: V2.0 narrows this to adult-only 'a'; kept wider deliberately.
    "Id10230": {"ageGroup"},
}

SECTION_DEVIATIONS = {
    "consented": {"label.en"},  # relabelled "Interview completion"
}


def _differences(built, target, path=""):
    """Yield dotted paths where two instrument fragments differ, ignoring ast."""
    if path.endswith(".ast") or path == "ast":
        return
    if isinstance(built, dict) and isinstance(target, dict):
        for key in sorted(set(built) | set(target)):
            child = f"{path}.{key}" if path else key
            yield from _differences(built.get(key), target.get(key), child)
    elif isinstance(built, list) and isinstance(target, list):
        if len(built) != len(target):
            yield path
        else:
            for index, (a, b) in enumerate(zip(built, target)):
                yield from _differences(a, b, path)
    elif built != target:
        yield path


def _allowed(name, path, table):
    """True when `path` is at or below a recorded deviation for `name`."""
    for deviation in table.get(name, ()):
        if path == deviation or path.startswith(deviation + "."):
            return True
    return False


class WhoVa2022ConformanceTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.built = build_instrument_from_xlsform(XLSFORM, locales=LOCALES)
        cls.target = json.loads(INSTRUMENT.read_text())

    def test_metadata_matches(self):
        for key in ("id", "title", "version", "defaultLanguage", "sourceFile"):
            self.assertEqual(self.built[key], self.target[key], f"metadata: {key}")

    def test_every_question_and_section_is_present_exactly_once(self):
        built_names = [q["name"] for q in self.built["questions"]]
        target_names = [q["name"] for q in self.target["questions"]]
        self.assertEqual(len(built_names), len(set(built_names)), "duplicate question names")
        self.assertEqual(sorted(built_names), sorted(target_names))
        self.assertEqual(
            [s["name"] for s in self.built["sections"]],
            [s["name"] for s in self.target["sections"]],
        )

    def test_questions_match_apart_from_recorded_deviations(self):
        target_by_name = {q["name"]: q for q in self.target["questions"]}
        unexpected = []
        for question in self.built["questions"]:
            name = question["name"]
            for path in _differences(question, target_by_name[name]):
                if not _allowed(name, path, DEVIATIONS):
                    unexpected.append(f"{name}: {path}")
        self.assertEqual(unexpected, [], f"unexpected conversion differences: {unexpected}")

    def test_sections_match_apart_from_recorded_deviations(self):
        target_by_name = {s["name"]: s for s in self.target["sections"]}
        unexpected = []
        for section in self.built["sections"]:
            name = section["name"]
            for path in _differences(section, target_by_name[name]):
                if not _allowed(name, path, SECTION_DEVIATIONS):
                    unexpected.append(f"{name}: {path}")
        self.assertEqual(unexpected, [], f"unexpected section differences: {unexpected}")

    def test_every_recorded_deviation_still_applies(self):
        """A deviation that stopped happening means the record is stale."""
        target_by_name = {q["name"]: q for q in self.target["questions"]}
        for name, paths in DEVIATIONS.items():
            question = next(q for q in self.built["questions"] if q["name"] == name)
            actual = set(_differences(question, target_by_name[name]))
            for path in paths:
                self.assertTrue(
                    any(a == path or a.startswith(path + ".") or path.startswith(a) for a in actual),
                    f"{name}: recorded deviation '{path}' no longer differs — update DEVIATIONS",
                )

    def test_expressions_are_carried_as_xlsform_source(self):
        by_name = {q["name"]: q for q in self.built["questions"]}
        self.assertEqual(
            by_name["Id10021"]["relevant"]["source"], "selected(${Id10020}, 'yes')"
        )
        self.assertEqual(by_name["Id10021"]["constraint"]["source"], ". <= today()")
        self.assertTrue(by_name["Id10023"]["calculation"]["source"].startswith("if(selected("))

    def test_choice_lists_are_inlined(self):
        sex = next(q for q in self.built["questions"] if q["name"] == "Id10019")
        self.assertEqual(sex["listName"], "select_2")
        self.assertEqual(sex["choices"][0]["value"], "female")
        self.assertEqual(sex["choices"][0]["label"]["en"], "Female")
        self.assertIn("female", sex["validation"]["choiceValues"])

    def test_locales_defaults_to_every_language_the_workbook_carries(self):
        """`locales=None` (the default) must not change existing callers' output."""
        unrestricted = build_instrument_from_xlsform(XLSFORM)
        sex = next(q for q in unrestricted["questions"] if q["name"] == "Id10019")
        self.assertIn("fr", sex["choices"][0]["label"])
        self.assertIn("es", sex["choices"][0]["label"])

    def test_locales_restricts_labels_hints_and_choices_to_the_given_set(self):
        restricted = build_instrument_from_xlsform(XLSFORM, locales={"en"})
        sex = next(q for q in restricted["questions"] if q["name"] == "Id10019")
        self.assertLessEqual(set(sex["label"].keys()), {"en"})
        self.assertEqual(set(sex["choices"][0]["label"].keys()), {"en"})

    def test_shipped_instrument_carries_no_locale_but_english(self):
        """digitva-13x: the reference instrument is English only; every other
        locale comes from the translation engine, not the instrument itself."""
        allowed = {"en"}

        def locale_keys(node):
            if isinstance(node, dict):
                for field in ("label", "hint", "guidance", "constraintMessage"):
                    value = node.get(field)
                    if isinstance(value, dict):
                        yield from value.keys()
                for value in node.values():
                    yield from locale_keys(value)
            elif isinstance(node, list):
                for item in node:
                    yield from locale_keys(item)

        found = set(locale_keys(self.target))
        self.assertLessEqual(found, allowed, f"unexpected locales in shipped instrument: {found - allowed}")


class TypeCoverageTests(BaseTestCase):
    """The converter's type map must match the engine's QuestionControl union.

    A type the engine cannot render must raise rather than be mapped onto a
    near-enough control: turning a decimal into an integer or a geopoint into
    text silently discards what the interviewer entered.
    """

    def _build(self, rows):
        import pandas as pd
        import tempfile

        survey = pd.DataFrame(
            [{"type": t, "name": n, "label::English (en)": n} for t, n in rows]
        )
        choices = pd.DataFrame(
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}]
        )
        settings = pd.DataFrame(
            [{"form_id": "t", "form_title": "T", "version": "1",
              "default_language": "English (en)"}]
        )
        handle = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        handle.close()
        with pd.ExcelWriter(handle.name) as writer:
            survey.to_excel(writer, sheet_name="survey", index=False)
            choices.to_excel(writer, sheet_name="choices", index=False)
            settings.to_excel(writer, sheet_name="settings", index=False)
        return build_instrument_from_xlsform(handle.name)

    def test_maps_every_supported_odk_type_to_an_engine_control(self):
        expected = {
            "text": ("text", "string"),
            "integer": ("integer", "number"),
            "decimal": ("decimal", "decimal"),
            "date": ("date", "date"),
            "time": ("time", "time"),
            "datetime": ("datetime", "dateTime"),
            "barcode": ("barcode", "string"),
            "range": ("range", "number"),
            "geopoint": ("geopoint", "geopoint"),
            "note": ("note", "none"),
            "calculate": ("calculated", "calculated"),
            "acknowledge": ("confirm", "boolean"),
            "image": ("image", "attachment"),
            "audio": ("audio", "attachment"),
            "file": ("file", "attachment"),
            "hidden": ("calculated", "calculated"),
            "deviceid": ("system", "string"),
            "username": ("system", "string"),
            "phonenumber": ("system", "string"),
            "email": ("system", "string"),
        }
        instrument = self._build(
            [("begin group", "g")]
            + [(odk_type, f"q_{odk_type}") for odk_type in expected]
            + [("end group", None)]
        )
        built = {q["name"]: q for q in instrument["questions"]}
        for odk_type, (control, data_type) in expected.items():
            question = built[f"q_{odk_type}"]
            self.assertEqual(question["control"], control, f"{odk_type} control")
            self.assertEqual(question["dataType"], data_type, f"{odk_type} dataType")

    def test_selection_types_carry_their_choice_list(self):
        instrument = self._build(
            [("begin group", "g"), ("select_one yes_no", "one"),
             ("select_multiple yes_no", "many"), ("end group", None)]
        )
        built = {q["name"]: q for q in instrument["questions"]}
        self.assertEqual(built["one"]["control"], "singleChoice")
        self.assertEqual(built["many"]["control"], "multipleChoice")
        self.assertEqual(built["many"]["dataType"], "string[]")
        self.assertEqual(built["one"]["validation"]["choiceValues"], ["yes"])

    def test_a_type_the_engine_cannot_render_names_the_missing_work(self):
        with self.assertRaises(XlsFormConversionError) as caught:
            self._build([("begin group", "g"), ("geotrace", "path"), ("end group", None)])
        message = str(caught.exception)
        self.assertIn("geotrace", message)
        self.assertIn("geotrace control", message)


class UnsupportedConstructTests(BaseTestCase):
    def test_repeat_groups_are_refused_rather_than_flattened(self):
        """The engine has no repeat model; silently flattening would lose answers."""
        import pandas as pd
        import tempfile

        survey = pd.DataFrame(
            [
                {"type": "begin repeat", "name": "children", "label::English (en)": "Children"},
                {"type": "text", "name": "child_name", "label::English (en)": "Name"},
                {"type": "end repeat", "name": None, "label::English (en)": None},
            ]
        )
        choices = pd.DataFrame([{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}])
        settings = pd.DataFrame(
            [{"form_id": "t", "form_title": "T", "version": "1", "default_language": "English (en)"}]
        )
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as handle:
            with pd.ExcelWriter(handle.name) as writer:
                survey.to_excel(writer, sheet_name="survey", index=False)
                choices.to_excel(writer, sheet_name="choices", index=False)
                settings.to_excel(writer, sheet_name="settings", index=False)

            with self.assertRaises(XlsFormConversionError) as caught:
                build_instrument_from_xlsform(handle.name)
        self.assertIn("repeat", str(caught.exception).lower())
