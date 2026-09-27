"""Mode-aware clinical DORIS editor and stale-state frontend contracts."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DorisClinicalTemplateContractTests(unittest.TestCase):
    def _read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_coder_templates_preserve_masked_default_and_route_unmasked_directly(self):
        initial = self._read("app/templates/va_form_partials/vainitialasses.html")
        final = self._read("app/templates/va_form_partials/vafinalasses.html")

        self.assertIn("project_mode|default('masked_simple')", initial)
        self.assertIn('include "va_form_partials/vafinalasses.html"', initial)
        self.assertIn("project_mode == 'unmasked_simple'", final)
        self.assertIn("('unmasked_simple', 'unmasked_doris')", final)
        self.assertIn("data-icd-hidden=\"va_immediate_cod\"", final)
        self.assertIn("doris_role='coder'", final)
        self.assertIn("The final assessment was not saved", final)
        self.assertIn("form_error_messages", final)
        self.assertIn("form.va_finassess_remark.data", final)
        # Unmasked coding is one step, so SmartVA shows before the certificate.
        unmasked = final[: final.index("{% else %}\n{% if session_timed_out %}")]
        self.assertLess(unmasked.index("_smartva_summary.html"), unmasked.index("doris_role='coder'"))

    def test_reviewer_has_separate_unmasked_final_flow(self):
        reviewer = self._read(
            "app/templates/va_formcategory_partials/_va_cod_assessment_panel.html"
        )

        self.assertIn('id="reviewerUnmaskedFinalForm"', reviewer)
        self.assertIn("doris_role='reviewer'", reviewer)
        self.assertIn("body.immediate_cod", reviewer)
        self.assertIn("body[name] = form.querySelector", reviewer)
        self.assertIn("body[name] = JSON.parse", reviewer)
        self.assertIn("DORIS_CERTIFICATE_CHANGED", reviewer)

    def test_reviewer_read_only_reference_uses_mode_correct_coder_row(self):
        reviewer = self._read(
            "app/templates/va_formcategory_partials/_va_cod_assessment_panel.html"
        )

        self.assertIn("data-coder-masked-reference", reviewer)
        self.assertIn("data-coder-unmasked-reference", reviewer)
        self.assertIn("va_final_assess.va_immediate_cod", reviewer)
        self.assertIn("va_final_assess.va_other_conditions", reviewer)
        self.assertIn("va_final_assess.doris_result", reviewer)
        self.assertIn("va_final_assess.codedit_result", reviewer)
        self.assertIn("coder_doris_output.get('report')", reviewer)
        self.assertIn("coder_codedit_output.get('report')", reviewer)

    def test_editor_posts_all_server_bound_proof_fields(self):
        partial = self._read(
            "app/templates/va_form_partials/_doris_certificate_editor.html"
        )

        for name in (
            "doris_certificate",
            "doris_result",
            "codedit_result",
            "doris_process_token",
            "doris_result_digest",
        ):
            self.assertIn(f'name="{name}"', partial)
        self.assertIn('data-role="{{ doris_role', partial)
        self.assertIn("data-doris-add-uncoded", partial)
        self.assertIn("data-doris-fetal", partial)
        self.assertIn("data-doris-summary", partial)
        self.assertIn("data-doris-initial-processing", partial)
        self.assertLess(partial.index("Step 1: DORIS"), partial.index("Step 2: Final underlying cause of death"))
        self.assertLess(partial.index("Step 2: Final underlying cause of death"), partial.index("data-doris-final-panel"))
        self.assertLess(partial.index("data-doris-final-panel"), partial.index("data-doris-final-use"))
        self.assertLess(partial.index("data-doris-final-choice"), partial.index("data-doris-technical"))
        self.assertLess(partial.index("data-doris-part2"), partial.index("data-doris-maternal"))
        self.assertLess(partial.index("data-doris-maternal"), partial.index("data-doris-process"))
        self.assertIn("data-doris-maternal", partial)
        self.assertIn("data-postcoordination-url", partial)
        self.assertIn("data-postcoordination-options-url", partial)
        self.assertIn("data-hierarchy-url", partial)
        self.assertIn("data-doris-guided-panel", partial)
        self.assertIn("css/doris_demo.css", partial)
        self.assertIn("X-CSRFToken", self._read("app/static/js/doris_clinical.js"))
        script = self._read("app/static/js/doris_clinical.js")
        self.assertIn("JSON.stringify(doris)", script)
        self.assertIn("JSON.stringify(codedit)", script)
        picker = self._read("app/static/js/digitva_icd11_picker.js")
        self.assertIn("+ Build", picker)
        self.assertIn("See in hierarchy", picker)
        self.assertIn("data-doris-interval-value", partial)
        self.assertIn("data-doris-interval-unit", partial)
        self.assertIn("doris-search-result-main", script)

    def test_editor_loads_only_the_clinical_host_as_a_module(self):
        partial = self._read(
            "app/templates/va_form_partials/_doris_certificate_editor.html"
        )

        self.assertIn('<script type="module" src="', partial)
        self.assertIn("js/doris_clinical.js", partial)
        self.assertNotIn("doris_search_modal.js", partial)
        self.assertNotIn("doris_postcoordination.js", partial)
        self.assertNotIn("doris_interval.js", partial)


class DorisClinicalJavascriptContractTests(unittest.TestCase):
    def setUp(self):
        self.script = (ROOT / "app/static/js/doris_clinical.js").read_text(
            encoding="utf-8"
        )

    def test_any_certificate_edit_invalidates_proof_and_final_ucod(self):
        self.assertIn("function invalidate(message)", self.script)
        self.assertIn("state.processing = null", self.script)
        self.assertIn("clearFinal();", self.script)
        self.assertIn("if (save) save.disabled = true", self.script)
        self.assertIn("hidden(editor, '[data-doris-token]', '')", self.script)
        self.assertIn("FetalOrInfantDeath", self.script)
        self.assertIn("MaternalDeath", self.script)

    def test_process_is_revision_and_role_bound(self):
        self.assertIn("client_revision: state.revision", self.script)
        self.assertIn("role: editor.dataset.role", self.script)
        self.assertIn("if (sent !== state.revision) return", self.script)

    def test_blank_clinical_editor_has_three_lines_and_filters_empty_rows(self):
        self.assertIn("[{Conditions: []}, {Conditions: []}, {Conditions: []}]", self.script)
        self.assertIn("state.lines.filter(function (line) { return line.conditions.length; })", self.script)
        self.assertIn("blank lines cannot separate causes", self.script)

    def test_interval_changes_validate_and_retain_loaded_raw_values(self):
        self.assertIn("mountInterval(", self.script)
        self.assertIn("intervalError()", self.script)
        interval = (ROOT / "app/static/js/doris_interval.js").read_text(encoding="utf-8")
        self.assertIn("dirty: false", interval)
        self.assertIn("if (!state.dirty) return {value: state.raw, error: ''};", interval)
        self.assertIn("selected === 'MI' ? 'M'", interval)

    def test_changed_certificate_installs_fresh_results_but_reconfirms(self):
        self.assertIn("DORIS_CERTIFICATE_CHANGED", self.script)
        self.assertIn("renderProcessing(processing, true)", self.script)
        self.assertIn("clearFinal();", self.script)
        self.assertIn("delete save.dataset.dorisNeedsConfirmation", self.script)

    def test_delayed_final_ucod_selection_cannot_confirm_new_processing_result(self):
        # Verification now lives in the shared picker, keyed on a single
        # opaque `revision()` value. The clinical host must fold its
        # processing-revision into that value so a final-UCOD selection
        # started against one processed result cannot confirm after a
        # reprocess (e.g. a 409 conflict install) replaces it, even when
        # the certificate edit-revision itself did not change.
        self.assertIn("state.processingRevision += 1", self.script)
        self.assertIn("return state.revision + ':' + state.processingRevision", self.script)
        picker = (ROOT / "app/static/js/digitva_icd11_picker.js").read_text(encoding="utf-8")
        self.assertIn("var sentRevision = currentRevision()", picker)
        self.assertIn("if (currentRevision() !== sentRevision || !container.isConnected) return", picker)

    def test_unrelated_htmx_swap_does_not_reset_existing_ect_values(self):
        for path in (
            "app/templates/va_form_partials/vainitialasses.html",
            "app/templates/va_form_partials/vafinalasses.html",
        ):
            source = (ROOT / path).read_text(encoding="utf-8")
            self.assertIn("swapped === root || swapped.contains(root)", source)


class DorisPostcoordinationJavascriptContractTests(unittest.TestCase):
    def test_clinical_search_counter_starts_defined_and_final_related_terms_research(self):
        source = (Path(__file__).resolve().parents[2] / "app/static/js/doris_clinical.js").read_text(encoding="utf-8")
        self.assertIn("searchRequest: 0,", source)
        self.assertIn("|| finalMode) { input.value = term.code; search(line, finalMode); }", source)

    def setUp(self):
        root = Path(__file__).resolve().parents[2]
        self.script = (root / "app/static/js/digitva_icd11_picker.js").read_text(
            encoding="utf-8"
        )

    def test_guided_builder_keeps_who_axis_rules_and_lazy_children(self):
        self.assertIn("axis.required", self.script)
        self.assertIn("axis.allow_multiple", self.script)
        self.assertIn("parent_uri: option.uri", self.script)
        self.assertIn("Use complete expression", self.script)
        self.assertIn("More choices", self.script)
        self.assertIn("'▷ ' + option.title", self.script)
        self.assertIn("state.truncated", self.script)

    def test_same_block_policy_replaces_conflict_but_keeps_other_blocks(self):
        self.assertIn("policy === 'AllowAlways'", self.script)
        self.assertNotIn("policy === 'Allowed'", self.script)
        self.assertIn("AllowedExceptFromSameBlock", self.script)
        self.assertIn("block_uri: text(option && option.block_uri)", self.script)
        self.assertIn("item.block_uri === option.block_uri", self.script)
        self.assertIn("values.splice(sameBlock, 1, option)", self.script)
        self.assertIn("values.push(option)", self.script)

    def test_expression_and_hierarchy_contracts_are_explicit(self):
        self.assertIn("/^X/i.test(item.code) ? '&' : '/'", self.script)
        self.assertIn("uri += ' ' + separator + ' ' + item.uri", self.script)
        self.assertNotIn("Matching terms", self.script)
        self.assertIn("related_maternal", self.script)
        self.assertIn("related_perinatal", self.script)
        self.assertIn("openHierarchy", self.script)

    def test_open_ended_extension_pick_is_verified_against_who_codeinfo(self):
        self.assertIn("transport.post('codeinfo', {schema_version: 1, code: state.stem.code + '&' + item.code})", self.script)
        self.assertIn(
            "'WHO does not accept ' + item.code + ' as an extension of ' + state.stem.code + '.'",
            self.script,
        )


class Icd11PickerNoGlobalsContractTests(unittest.TestCase):
    def test_no_window_digitvadoris_globals_remain(self):
        picker = (ROOT / "app/static/js/digitva_icd11_picker.js").read_text(encoding="utf-8")
        clinical = (ROOT / "app/static/js/doris_clinical.js").read_text(encoding="utf-8")

        for script in (picker, clinical):
            self.assertNotIn("window.DigitvaDoris", script)
            self.assertNotIn("root.DigitvaDoris", script)

    def test_clinical_host_owns_the_htmx_close_hook(self):
        clinical = (ROOT / "app/static/js/doris_clinical.js").read_text(encoding="utf-8")
        picker = (ROOT / "app/static/js/digitva_icd11_picker.js").read_text(encoding="utf-8")

        self.assertIn("htmx:beforeSwap", clinical)
        self.assertIn("editor._dorisPicker.close()", clinical)
        self.assertNotIn("htmx:beforeSwap", picker)

    def test_side_browser_tab_follows_project_icd_classification(self):
        page = (ROOT / "app/templates/va_frontpages/va_coding.html").read_text(encoding="utf-8")
        service = (ROOT / "app/services/coding_service.py").read_text(encoding="utf-8")

        self.assertIn("icd_classification == 'icd11'", page)
        self.assertIn("icd.who.int/browse/2026-01/mms/en", page)
        self.assertIn("icd.who.int/browse10/2019/en", page)
        self.assertIn("icd_classification=", service)


class TestDorisAdminDefaults(unittest.TestCase):
    def test_interview_sex_and_whole_year_age_start_a_new_certificate(self):
        from types import SimpleNamespace

        from app.routes.va_form import _doris_admin_defaults

        def submission(gender, age):
            return SimpleNamespace(va_deceased_gender=gender, va_deceased_age=age)

        self.assertEqual(
            _doris_admin_defaults(submission("Male", 76)),
            {"AdministrativeData": {"Sex": 1, "EstimatedAge": "P76Y"}},
        )
        self.assertEqual(
            _doris_admin_defaults(submission(" female ", 30)),
            {"AdministrativeData": {"Sex": 2, "EstimatedAge": "P30Y"}},
        )
        # Under a year is left for the coder; unknown sex and odd ages are omitted.
        self.assertEqual(_doris_admin_defaults(submission("Male", 0)), {"AdministrativeData": {"Sex": 1}})
        self.assertEqual(_doris_admin_defaults(submission("Unknown", 999)), {})
        self.assertEqual(_doris_admin_defaults(None), {})
