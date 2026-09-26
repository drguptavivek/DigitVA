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
        self.assertIn("data-doris-maternal", partial)
        self.assertIn("data-postcoordination-url", partial)
        self.assertIn("data-postcoordination-options-url", partial)
        self.assertIn("data-hierarchy-url", partial)
        self.assertIn("data-doris-final-guided-panel", partial)
        self.assertIn("doris_postcoordination.js", partial)
        self.assertIn("css/doris_demo.css", partial)
        self.assertIn("X-CSRFToken", self._read("app/static/js/doris_clinical.js"))
        script = self._read("app/static/js/doris_clinical.js")
        self.assertIn("JSON.stringify(doris)", script)
        self.assertIn("JSON.stringify(codedit)", script)
        self.assertIn("Build expression", script)
        self.assertIn("See in hierarchy", script)
        self.assertIn("selectionRevision !== state.revision", script)


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

    def test_changed_certificate_installs_fresh_results_but_reconfirms(self):
        self.assertIn("DORIS_CERTIFICATE_CHANGED", self.script)
        self.assertIn("renderProcessing(processing, true)", self.script)
        self.assertIn("clearFinal();", self.script)
        self.assertIn("delete save.dataset.dorisNeedsConfirmation", self.script)

    def test_delayed_final_ucod_selection_cannot_confirm_new_processing_result(self):
        self.assertIn("var selectionRevision = state.revision", self.script)
        self.assertIn("var selectionProcessing = state.processing", self.script)
        self.assertIn("selectionRevision !== state.revision", self.script)
        self.assertIn("selectionProcessing !== state.processing", self.script)
        self.assertIn("!state.processing", self.script)
        stale_guard = self.script.index("selectionProcessing !== state.processing")
        enable_save = self.script.index("save.disabled = false")
        self.assertLess(stale_guard, enable_save)

    def test_unrelated_htmx_swap_does_not_reset_existing_ect_values(self):
        for path in (
            "app/templates/va_form_partials/vainitialasses.html",
            "app/templates/va_form_partials/vafinalasses.html",
        ):
            source = (ROOT / path).read_text(encoding="utf-8")
            self.assertIn("swapped === root || swapped.contains(root)", source)


class DorisPostcoordinationJavascriptContractTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2]
        self.script = (root / "app/static/js/doris_postcoordination.js").read_text(
            encoding="utf-8"
        )

    def test_guided_builder_keeps_who_axis_rules_and_lazy_children(self):
        self.assertIn("axis.required", self.script)
        self.assertIn("axis.allow_multiple", self.script)
        self.assertIn("parent_uri: option.uri", self.script)
        self.assertIn("Use complete expression", self.script)
        self.assertIn("More choices", self.script)
        self.assertIn("choose a coded child", self.script)
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
        self.assertIn("matching_terms", self.script)
        self.assertIn("related_maternal", self.script)
        self.assertIn("related_perinatal", self.script)
        self.assertIn("openHierarchy", self.script)
