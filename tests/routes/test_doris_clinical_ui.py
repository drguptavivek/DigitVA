"""Mode-aware clinical DORIS editor and stale-state frontend contracts."""

import re
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
        unmasked = final[: final.index("{% else %}\n{% if step1_resaved %}")]
        reviewer = (ROOT / "app/templates/va_formcategory_partials/_va_cod_assessment_panel.html").read_text(encoding="utf-8")
        reviewer_form = reviewer[reviewer.index('id="reviewerUnmaskedFinalForm"'):]
        self.assertLess(reviewer_form.index("_smartva_summary.html"), reviewer_form.index("doris_role='reviewer'"))
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

    def test_reviewer_icd11_saves_retry_on_age_restriction(self):
        reviewer = self._read(
            "app/templates/va_formcategory_partials/_va_cod_assessment_panel.html"
        )
        self.assertEqual(reviewer.count("window.digitvaAgeRetry("), 3)
        self.assertEqual(reviewer.count("body.age_restriction_confirmed = true"), 3)
        self.assertEqual(reviewer.count("body.causing_condition_unknown = true"), 2)
        base = self._read("app/static/js/base.js")
        self.assertIn("window.digitvaAgeRetry = function", base)
        self.assertIn("AGE_RESTRICTION_CONFIRMATION_REQUIRED", base)
        clinical = self._read("app/static/js/doris_clinical.js")
        self.assertIn("setUnknownCause(choice.causing_condition_unknown === true)", clinical)

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
        # WHO wording and order: Administrative Data, Part 1, Part 2, then the WHO cards.
        headings = ["Administrative Data", "Part 1: Cause of death",
                    "Part 2: Other significant conditions contributing to death",
                    "Manner of death", "Fetal or infant death *", "Information on pregnancy",
                    "Surgery</h5>", "Autopsy</h5>", "*fields are not mandatory"]
        positions = [partial.index(h) for h in headings]
        self.assertEqual(positions, sorted(positions))
        # Part I/II lines read "Onset to death [Interval] [Units]"; age keeps Age / Age unit.
        self.assertIn(">Onset to death</label>", partial)
        self.assertIn('placeholder="Interval"', partial)
        self.assertIn('data-blank-label="Age unit"', partial)
        self.assertIn("data-doris-add-below", partial)
        self.assertIn("doris-section-heading", partial)
        self.assertEqual(partial.count('type="date"'), 2)  # the precision macro (three fields) and the plain date of death
        self.assertIn("data-doris-line-letter", partial)
        self.assertIn('aria-label="Time unit"', partial)
        self.assertIn("data-postcoordination-url", partial)
        self.assertIn("data-postcoordination-options-url", partial)
        self.assertIn("data-hierarchy-url", partial)
        self.assertIn("data-doris-guided-panel", partial)
        self.assertIn("css/doris_demo.css", partial)
        self.assertIn('class="doris-editor-heading"><h2', partial)
        self.assertIn('class="doris-actions-separator"', partial)
        self.assertIn("X-CSRFToken", self._read("app/static/js/doris_clinical.js"))
        script = self._read("app/static/js/doris_clinical.js")
        self.assertIn("JSON.stringify(doris)", script)
        self.assertIn("JSON.stringify(codedit)", script)
        picker = self._read("app/static/js/digitva_icd11_picker.js")
        self.assertIn("+ Build", picker)
        self.assertIn("See in hierarchy", picker)
        self.assertIn("data-doris-interval-value", partial)
        self.assertIn("data-doris-interval-unit", partial)
        self.assertIn("doris-search-result-main", self._read("app/static/js/digitva_icd11_picker.js"))

    def test_whole_cards_keep_their_title_and_show_a_not_applicable_note(self):
        partial = self._read("app/templates/va_form_partials/_doris_certificate_editor.html")
        script = self._read("app/static/js/doris_clinical.js")
        rules = self._read("app/static/js/doris_rules.js")
        for card, rule in (("Fetal or infant death *", "fetal"), ("Information on pregnancy", "maternal")):
            self.assertIn(f"<h5 class=\"h6\">{card}</h5><div class=\"alert alert-warning", partial)
            self.assertIn(f'data-doris-na="{rule}"', partial)
            self.assertIn(f'<div class="row g-2" data-doris-rule="{rule}"', partial)
        self.assertNotIn('data-doris-fetal data-doris-rule', partial)
        self.assertIn("This section is not applicable when it is not a fetal or infant death", rules)
        self.assertIn("This section is not applicable when the selected sex is male", rules)
        self.assertIn("This section is not applicable when the selected sex is not female", rules)
        self.assertIn("data-doris-na", script)
        # Single follow-ups stay hidden with no note.
        self.assertEqual(partial.count("data-doris-na="), 2)

    def test_partial_dates_use_a_precision_dropdown_and_death_is_a_plain_date(self):
        partial = self._read("app/templates/va_form_partials/_doris_certificate_editor.html")
        fields = self._read("app/static/js/doris_fields.js")
        self.assertNotIn("Year or month only", partial)
        self.assertNotIn("data-doris-date-mode", partial + fields + self._read("app/static/js/doris_clinical.js"))
        self.assertIn('<option value="date" selected>Date</option><option value="month">Year-Month</option><option value="year">Year</option>', partial)
        # Exactly three dropdown fields, one per macro call; none for the date of death.
        for hook, label in (("data-doris-date-birth", "Date of birth"), ("data-doris-external-date", "Date of injury"), ("data-doris-surgery-date", "Date of surgery")):
            self.assertRegex(partial, r"doris_date\('%s[^']*', '%s'" % (hook, label))
        self.assertEqual(partial.count("{{ doris_date("), 3)
        self.assertIn('aria-label="{{ label }} precision"', partial)
        death = re.search(r"<input[^>]*data-doris-date-death[^>]*>", partial).group(0)
        self.assertIn('type="date"', death)
        self.assertNotIn("data-doris-date ", death + " ")
        self.assertNotIn("precision", death)
        # Native validation would block Save in the htmx form: no max/min/pattern on any date control.
        for tag in re.findall(r"<input[^>]*type=\"date\"[^>]*>", partial):
            self.assertNotRegex(tag, r"\b(max|min|pattern)=")
        self.assertNotRegex(fields, r"\.(max|min)\s*=|setAttribute\('(max|min|pattern)'")

    def test_every_certificate_question_gets_a_clear_button_and_the_search_waits_for_three_characters(self):
        fields = self._read("app/static/js/doris_fields.js")
        script = self._read("app/static/js/doris_clinical.js")
        css = self._read("app/static/css/doris_demo.css")
        self.assertIn("data-doris-clear", fields)
        self.assertIn("'Clear ' + label", fields)
        self.assertIn("data-doris-prefill-marker", fields)
        self.assertIn(".doris-clear", css)
        self.assertIn("min-width: 2.75rem; min-height: 2.75rem", css)
        self.assertIn("Fields.mountClear(editor)", script)
        self.assertIn("clearButtons.refresh()", script)
        picker = self._read("app/static/js/digitva_icd11_picker.js")
        self.assertIn("export function attachAutoSearch", picker)
        self.assertEqual(script.count("attachAutoSearch("), 2)  # line box + final box
        self.assertIn("attachAutoSearch(input, search)", self._read("app/static/js/doris_final_cod.js"))

    def test_add_line_below_inserts_after_its_line(self):
        script = self._read("app/static/js/doris_clinical.js")
        self.assertIn("state.lines.splice(index + 1, 0, added)", script)
        self.assertIn("[data-doris-add-below]').disabled = state.lines.length >= MAX_LINES", script)

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
        picker = (Path(__file__).resolve().parents[2] / "app/static/js/digitva_icd11_picker.js").read_text(encoding="utf-8")
        self.assertIn("|| finalMode) { input.value = term.code; onRequery(); }", picker)

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


class TestDorisInitialCertificate(unittest.TestCase):
    """The editor's starting certificate: saved as-is, else the prefill."""

    def test_a_saved_certificate_is_copied_without_prefill_markers(self):
        from app.services.doris_context_service import doris_initial

        saved = {"ICDVersion": "ICD11", "AdministrativeData": {"Sex": 2}}
        # A viewer entitled to personal data (a redacting viewer's copy
        # drops AdministrativeData: test_doris_context_service).
        certificate, provenance = doris_initial(saved, None, "masked_doris", False)
        self.assertEqual(certificate, saved)
        self.assertIsNot(certificate, saved)
        self.assertEqual(provenance, {})

    def test_no_prefill_outside_doris_or_without_a_submission(self):
        from types import SimpleNamespace

        from app.services.doris_context_service import doris_initial

        self.assertEqual(doris_initial(None, None, "unmasked_doris", False), ({}, {}))
        submission = SimpleNamespace(va_sid="uuid:not-read")
        self.assertEqual(doris_initial(None, submission, "masked_simple", False), ({}, {}))


class TestDorisPrefillEditorContract(unittest.TestCase):
    def _read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_every_prefillable_field_has_a_control_and_is_serialized(self):
        template = self._read("app/templates/va_form_partials/_doris_certificate_editor.html")
        script = self._read("app/static/js/doris_clinical.js")
        self.assertIn("data-doris-prefill", template)
        for path in (
            "AdministrativeData.Sex", "AdministrativeData.EstimatedAge",
            "AdministrativeData.DateBirth", "AdministrativeData.DateDeath",
            "FetalOrInfantDeath.Stillborn", "FetalOrInfantDeath.DeathWithin24h",
            "FetalOrInfantDeath.MultiplePregnancy", "FetalOrInfantDeath.BirthWeight",
            "FetalOrInfantDeath.PregnancyWeeks", "FetalOrInfantDeath.AgeMother",
            "MaternalDeath.WasPregnant", "MaternalDeath.TimeFromPregnancy",
            "MannerOfDeath.MannerOfDeath", "MannerOfDeath.DateOfExternalCauseOrPoisoning",
            "MannerOfDeath.DescriptionExternalCause", "MannerOfDeath.PlaceOfOccuranceExternalCause",
            "Surgery.WasPerformed", "Surgery.Reason",
            "Autopsy.WasRequested", "Autopsy.Findings",
        ):
            self.assertIn(f'data-doris-field="{path}"', template)
        for key in ("DateBirth", "DateDeath", "MannerOfDeath", "Surgery", "Autopsy",
                    "PlaceOfOccuranceExternalCause", "WasRequested"):
            self.assertIn(f"'{key}'", script)
        # Markers are text, never markup, and every new control invalidates.
        self.assertIn("'from interview ('", script)
        self.assertIn("marker.textContent", script)
        self.assertIn("[data-doris-extra]", script)


class DorisIcd11WiringContractTests(unittest.TestCase):
    """digitva-u6e1 / digitva-wy34 / digitva-ra3y: the ICD-11 DORIS screens' wiring, read from the sources."""

    def _read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_doris_editor_and_masked_step2_each_offer_the_va_definitions_modal(self):
        editor = self._read("app/templates/va_form_partials/_doris_certificate_editor.html")
        masked = self._read("app/templates/va_form_partials/_masked_doris_final_cod.html")
        # One modal per editor or form, so pages with several editors and the ICD-10 modal keep unique ids.
        self.assertIn("{% with modal_id=_doris_id ~ '-va-definitions' %}", editor)
        self.assertIn("va_form_partials/_va_definitions_modal.html", editor)
        self.assertIn("data-bs-target=\"#{{ _doris_id }}-va-definitions\"", editor)
        self.assertIn("va_form_partials/_va_definitions_modal.html", masked)
        self.assertIn("-va-definitions' %}", masked)

    def test_picked_and_confirmed_icd11_causes_open_the_floating_definition_as_icd11(self):
        clinical = self._read("app/static/js/doris_clinical.js")
        final = self._read("app/static/js/doris_final_cod.js")
        self.assertIn("showDefinition(choice.code, 'Final underlying cause');", clinical)
        self.assertIn("showDefinition(choice.code, 'Certificate line');", clinical)
        self.assertIn("'icd11'", clinical)
        self.assertIn("window.DigitVADefinitionPanel.lookup(code, 'Final underlying cause', 'icd11')", final)

    def test_masked_step2_final_search_uses_the_shared_picker_rows_in_final_mode(self):
        final = self._read("app/static/js/doris_final_cod.js")
        self.assertIn("picker.renderResults(panel, items, {input: input, statusEl: message, resultList: results, finalMode: true", final)
        self.assertIn("attachAutoSearch(input, search)", final)
        self.assertNotIn("list-group-item d-flex", final)
        self.assertNotIn("picker.showDetails", final)

    def test_warning_catalogue_is_generated_and_read_by_both_runtimes(self):
        summary = self._read("app/static/js/doris_result_summary.js")
        self.assertIn("from './doris_warnings.js?v=1'", summary)
        warnings = self._read("app/static/js/doris_warnings.js")
        self.assertIn("from './doris_messages.js?v=1'", warnings)
        self.assertIn("Generated by scripts/generate_doris_messages.py", self._read("app/static/js/doris_messages.js"))
        expo = self._read("mobile/digitva-collect/src/workspace/doris/dorisWarnings.ts")
        self.assertIn('from "./dorisMessages"', expo)
