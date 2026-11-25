"""The intake blueprint's URL map is fixed (digitva-r8nh.9).

Old APKs (0.3.15 and later) call these rules; ``url_for`` and the body-size
and refusal-log hooks name these endpoints. The list was taken from the app
before ``app/routes/api/intake.py`` became a package: any change to a rule,
endpoint name or method fails here.
"""
from tests.base import BaseTestCase

P = "/api/v1/intake"
E = "api_v1.intake_api."

EXPECTED = sorted([
    (f"{P}/cases", f"{E}list_cases", "GET"),
    (f"{P}/cases/<death_id>", f"{E}case_detail", "GET"),
    (f"{P}/cases/<death_id>/attempts", f"{E}log_attempt", "POST"),
    (f"{P}/cases/<death_id>/flags", f"{E}flag_case", "POST"),
    (f"{P}/cases/<death_id>/identifiers", f"{E}put_identifiers", "PUT"),
    (f"{P}/cases/<death_id>/pause", f"{E}pause_interview", "POST"),
    (f"{P}/cases/<death_id>/possible-duplicates", f"{E}possible_duplicates", "GET"),
    (f"{P}/cases/<death_id>/visit", f"{E}set_visit", "POST"),
    (f"{P}/consent-config", f"{E}consent_config", "GET"),
    (f"{P}/deaths", f"{E}list_deaths", "GET"),
    (f"{P}/deaths", f"{E}register_death", "POST"),
    (f"{P}/deaths/<death_id>", f"{E}update_death", "PATCH"),
    (f"{P}/drafts", f"{E}list_drafts", "GET"),
    (f"{P}/drafts", f"{E}start_draft", "POST"),
    (f"{P}/drafts/<draft_id>", f"{E}get_draft", "GET"),
    (f"{P}/drafts/<draft_id>", f"{E}save_draft", "PATCH"),
    (f"{P}/drafts/<draft_id>/attachments/<client_attachment_id>", f"{E}get_attachment", "GET"),
    (f"{P}/drafts/<draft_id>/attachments/<client_attachment_id>", f"{E}put_attachment", "PUT"),
    (f"{P}/drafts/<draft_id>/discard", f"{E}discard_draft", "POST"),
    (f"{P}/drafts/<draft_id>/submit", f"{E}submit_draft", "POST"),
    (f"{P}/drafts/sync", f"{E}sync_draft", "POST"),
    (f"{P}/identifier-types", f"{E}identifier_types", "GET"),
    (f"{P}/outstanding", f"{E}report_outstanding", "POST"),
    (f"{P}/projects/<project_id>/prefill-policy", f"{E}prefill_policy", "GET"),
    (f"{P}/refusals", f"{E}registration_refusal", "POST"),
    (f"{P}/submissions", f"{E}submit_interview", "POST"),
    (f"{P}/submissions/<va_sid>/revisions", f"{E}revise_submission", "POST"),
    (f"{P}/supervision/cases", f"{E}supervised_cases", "GET"),
    (f"{P}/supervision/cases/<death_id>", f"{E}supervised_case_detail", "GET"),
    (f"{P}/supervision/cases/<death_id>/cancel", f"{E}cancel_case", "POST"),
    (f"{P}/supervision/cases/<death_id>/choose-interview", f"{E}choose_interview", "POST"),
    (f"{P}/supervision/cases/<death_id>/consent-withdrawal", f"{E}record_consent_withdrawal", "POST"),
    (f"{P}/supervision/cases/<death_id>/consent-withdrawal/undo", f"{E}undo_consent_withdrawal", "POST"),
    (f"{P}/supervision/cases/<death_id>/duplicate", f"{E}mark_duplicate", "POST"),
    (f"{P}/supervision/cases/<death_id>/possible-duplicates", f"{E}supervised_possible_duplicates", "GET"),
    (f"{P}/supervision/cases/<death_id>/reopen", f"{E}reopen_case", "POST"),
    (f"{P}/supervision/cases/<death_id>/resolve-flag", f"{E}resolve_flag", "POST"),
    (f"{P}/supervision/submissions/<va_sid>/reopen-for-revision", f"{E}reopen_for_revision", "POST"),
])


class IntakeUrlMapTests(BaseTestCase):
    def test_the_intake_rules_endpoints_and_methods_are_unchanged(self):
        rules = sorted(
            (rule.rule, rule.endpoint, ",".join(sorted(rule.methods - {"HEAD", "OPTIONS"})))
            for rule in self.app.url_map.iter_rules()
            if rule.endpoint.startswith(E)
        )
        self.assertEqual(rules, EXPECTED)
