"""app/services/web_form_relevance_service.py re-derives relevance and
constraint server-side over the composed instrument (beads digitva-cal.2 and
digitva-aiy.1). No database is needed here -- everything reads the generated
``who-va-2022.server-instrument.json`` artifact and evaluates in-process.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.services.web_form_relevance_service import (
    derive_validation_errors,
    strip_irrelevant_answers,
)

NOW = datetime(2024, 6, 15, 9, 0, 0, tzinfo=timezone.utc)


class StripIrrelevantAnswersTests(unittest.TestCase):
    def test_a_single_pass_is_not_enough_for_the_md_available_cascade(self):
        """md_im1's own ``relevant`` expression (``${md_count} >= 1``) reads
        md_count's raw submitted value, not whether md_count is itself
        relevant. Only stripping md_count (because md_available is "no")
        changes what md_im1 sees on the next pass -- this is the fixed point
        digitva-aiy.1 was filed over."""
        data = {
            "Id10013": "yes",
            "md_available": "no",
            "md_count": "4",
            "md_im1": "who-va-attachment:slot1",
            "md_im4": "who-va-attachment:slot4",
        }
        stripped, removed = strip_irrelevant_answers(data, now=NOW)

        self.assertNotIn("md_count", stripped)
        self.assertNotIn("md_im1", stripped)
        self.assertNotIn("md_im4", stripped)
        self.assertEqual(removed, {"md_count", "md_im1", "md_im4"})
        # md_available itself is never gated -- it survives.
        self.assertEqual(stripped["md_available"], "no")

    def test_relevant_answers_are_left_alone(self):
        data = {
            "Id10013": "yes",
            "md_available": "yes",
            "md_count": "2",
            "md_im1": "who-va-attachment:slot1",
            "md_im2": "who-va-attachment:slot2",
        }
        stripped, removed = strip_irrelevant_answers(data, now=NOW)

        self.assertEqual(removed, set())
        self.assertEqual(stripped, data)

    def test_doris_support_answers_survive_when_relevant_and_go_when_not(self):
        """doris_support_whova_2022 (digitva-hln): the server instrument knows
        the added questions, so relevant answers reach the payload and
        irrelevant ones are stripped like any other."""
        injury_adult = {
            "Id10013": "yes",
            "Id10020": "no",
            "Id10022": "yes",
            "Id10023_b": "2024-05-01",
            "dob_precision": "year",
            "dob_year": "1950-01-01",
            "age_group": "adult",
            "age_adult": 74,
            "Id10077": "yes",
            "Id10077_a": "less",
            "doris_injury_date_known": "full",
            "doris_injury_date": "2024-04-30",
            "doris_injury_place": "4",
            "doris_injury_legal_war": "neither",
            "doris_surgery_performed": "yes",
            "doris_surgery_when": 3,
            "doris_surgery_when_unit": "days",
            "doris_surgery_type": "Laparotomy",
            "doris_surgery_reason": "Abdominal injury",
            "doris_autopsy_requested": "yes",
            "doris_autopsy_findings": "no",
        }
        stripped, removed = strip_irrelevant_answers(injury_adult, now=NOW)
        self.assertEqual(removed, set())
        self.assertEqual(stripped, injury_adult)

        changed = {
            **injury_adult,
            "Id10077": "no",
            "dob_precision": "month_year",
            "doris_surgery_performed": "no",
            "Id10077_a": "less",
            "doris_autopsy_requested": "no",
        }
        stripped, removed = strip_irrelevant_answers(changed, now=NOW)
        self.assertIn("dob_precision", stripped)
        self.assertEqual(
            removed,
            {
                "dob_year",
                "Id10077_a",
                "doris_injury_date_known",
                "doris_injury_date",
                "doris_injury_place",
                "doris_injury_legal_war",
                "doris_surgery_when",
                "doris_surgery_when_unit",
                "doris_surgery_type",
                "doris_surgery_reason",
                "doris_autopsy_findings",
            },
        )

    def test_the_newborn_same_day_and_birth_weight_questions_follow_their_gates(self):
        same_day = {
            "Id10013": "yes",
            "Id10020": "yes",
            "Id10021": "2024-05-01",
            "Id10022": "yes",
            "Id10023_a": "2024-05-01",
            "doris_hours_survived": 4,
            "Id10366_check": "yes",
            "Id10366": 450,
            "Id10366_confirm": True,
            "doris_mother_age": 22,
        }
        stripped, removed = strip_irrelevant_answers(same_day, now=NOW)
        self.assertEqual(removed, set())
        self.assertEqual(stripped["doris_hours_survived"], 4)

        three_days = {**same_day, "Id10021": "2024-04-28", "Id10366": 2800}
        stripped, removed = strip_irrelevant_answers(three_days, now=NOW)
        self.assertEqual(removed, {"doris_hours_survived", "Id10366_confirm"})
        self.assertEqual(stripped["doris_mother_age"], 22)

    def test_surgery_follows_its_own_gates(self):
        """A7: asked outside health_service_utilization, so an injury death
        within 7 days keeps it; the unit goes when the time is 88/99; a
        stillbirth never has it."""
        operated = {
            "Id10013": "yes",
            "Id10077": "yes",
            "Id10077_a": "less",
            "doris_surgery_performed": "yes",
            "doris_surgery_when": 99,
            "doris_surgery_when_unit": "days",
        }
        stripped, removed = strip_irrelevant_answers(operated, now=NOW)
        self.assertEqual(stripped["doris_surgery_performed"], "yes")
        self.assertEqual(removed, {"doris_surgery_when_unit"})

        # A real amount of 88 or more (e.g. 120 days) keeps its unit; only
        # the 88/99 codes drop it.
        long_ago = {**operated, "doris_surgery_when": 120}
        stripped, removed = strip_irrelevant_answers(long_ago, now=NOW)
        self.assertEqual(stripped["doris_surgery_when_unit"], "days")
        self.assertNotIn("doris_surgery_when_unit", removed)

        stillbirth = {
            "Id10013": "yes",
            "Id10020": "yes",
            "Id10021": "2024-05-01",
            "Id10022": "yes",
            "Id10023_a": "2024-05-01",
            "Id10114": "yes",
            "doris_surgery_performed": "no",
        }
        stripped, removed = strip_irrelevant_answers(stillbirth, now=NOW)
        self.assertEqual(stripped["Id10114"], "yes")
        self.assertEqual(removed, {"doris_surgery_performed"})

    def test_id10340_keeps_who_relevance_for_every_project(self):
        """The server artifact carries WHO's Id10340 relevance, not the DORIS
        extension's (A10): a non-DORIS form asks it of a post-menopausal
        woman with no pregnancy, and the answer must survive the strip."""
        menopause = {
            "Id10013": "yes",
            "Id10019": "female",
            "Id10020": "yes",
            "Id10021": "1960-03-02",
            "Id10022": "yes",
            "Id10023_a": "2024-05-01",
            "Id10296": "yes",
            "Id10299": "yes",
            "Id10340": "no",
        }
        stripped, removed = strip_irrelevant_answers(menopause, now=NOW)
        self.assertEqual(removed, set())
        self.assertEqual(stripped["Id10340"], "no")

    def test_toggling_the_gate_back_would_restore_answers_because_the_draft_is_never_touched(self):
        # strip_irrelevant_answers only ever returns a new dict; it never
        # mutates its input, which is what lets a caller keep the original
        # (the draft) untouched while submitting a stripped copy.
        data = {"Id10013": "yes", "md_available": "no", "md_count": "1"}
        stripped, _ = strip_irrelevant_answers(data, now=NOW)
        self.assertEqual(data["md_count"], "1")
        self.assertNotIn("md_count", stripped)


class DeriveValidationErrorsTests(unittest.TestCase):
    def test_no_disagreement_on_a_clean_submission(self):
        data = {"Id10013": "yes", "Id10019": "female", "finalAgeInYears": "62", "narr_language": "english"}
        self.assertEqual(derive_validation_errors(data, now=NOW), [])

    def test_constraint_violation_is_reported_without_the_answer_value(self):
        data = {
            "Id10013": "yes",
            "Id10020": "yes",
            "Id10021": "2099-01-01",  # violates ". <= today()"
        }
        entries = derive_validation_errors(data, now=NOW)
        self.assertIn({"question": "Id10021", "rule": "constraint"}, entries)
        self.assertNotIn("2099-01-01", str(entries))

    def test_answering_a_question_the_server_considers_irrelevant_is_reported_as_relevant(self):
        # Id10021 (date of birth) is only relevant once Id10020='yes'; here
        # it is answered without that gate.
        data = {"Id10013": "yes", "Id10021": "2020-01-01"}
        entries = derive_validation_errors(data, now=NOW)
        self.assertIn({"question": "Id10021", "rule": "relevant"}, entries)

    def test_never_raises_and_never_leaks_a_value_for_a_large_realistic_submission(self):
        # A submission with nothing filled in beyond consent should not
        # explode walking the ~500-question instrument, and no entry may
        # carry a value under any key other than "question"/"rule".
        entries = derive_validation_errors({"Id10013": "yes"}, now=NOW)
        for entry in entries:
            self.assertEqual(set(entry.keys()), {"question", "rule"})
            self.assertIn(entry["rule"], ("relevant", "constraint"))


if __name__ == "__main__":
    unittest.main()


class EvaluationFailureIsRecordedTests(unittest.TestCase):
    """A failure to evaluate must not read as agreement.

    digitva-cal.2 collects how often the two engines disagree. An empty
    ``validation_err`` means "checked, agreed"; if a crash produced one, the
    data this release exists to gather would be quietly wrong. Review flagged
    the original broad ``except`` that returned ``[]``.
    """

    def test_a_failure_to_apply_calculations_is_recorded_not_swallowed(self):
        import app.services.web_form_relevance_service as svc

        def boom(*_args, **_kwargs):
            raise RuntimeError("evaluator exploded")

        original = svc.apply_calculations
        svc.apply_calculations = boom
        try:
            entries = svc.derive_validation_errors({"Id10019": "female"}, now=NOW)
        finally:
            svc.apply_calculations = original

        self.assertEqual(entries, [{"question": "*", "rule": "evaluation_error"}])

    def test_a_clean_submission_still_records_nothing(self):
        """Present-before-absent: the sentinel must not fire on a healthy path."""
        import app.services.web_form_relevance_service as svc

        entries = svc.derive_validation_errors({"Id10019": "female"}, now=NOW)
        self.assertNotIn(
            {"question": "*", "rule": "evaluation_error"},
            entries,
            "the sentinel fired on a submission that evaluates cleanly",
        )


class InstrumentAssumptionsThisServiceRestsOnTests(unittest.TestCase):
    """Two properties of the instrument that make this service safe today.

    Neither is guaranteed by anything else, and both fail silently if a future
    instrument change breaks them -- which is why they are pinned here rather
    than left as review notes.
    """

    def _questions(self):
        import json
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / "vendor/who-va-2022/src/generated/who-va-2022.server-instrument.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        questions = data.get("questions", data)
        return list(questions.values()) if isinstance(questions, dict) else list(questions)

    def test_no_regex_call_takes_its_pattern_from_an_answer(self):
        """A dynamic regex pattern would put a submitted answer into an
        exception message, and from there into a log -- these are mortality
        records. Every ``regex()`` in the instrument must pass a literal.
        """
        import re

        offenders = []
        for question in self._questions():
            for field in ("relevant", "constraint", "calculation"):
                source = question.get(field)
                source = source.get("source") if isinstance(source, dict) else source
                if not source:
                    continue
                for call in re.findall(r"regex\s*\(([^)]*)\)", str(source)):
                    parts = call.split(",")
                    if len(parts) >= 2 and "${" in parts[1]:
                        offenders.append((question.get("name"), field, str(source)))

        self.assertEqual(
            offenders,
            [],
            "regex() must take a literal pattern; a ${...} pattern can carry a "
            "submitted answer into an exception message and then into a log",
        )

    def test_no_system_control_question_carries_relevance_or_constraint(self):
        """``_NON_ANSWER_CONTROLS_FOR_VALIDATION`` excludes ``system``, which is
        a no-op only while no system-control question has a rule to check. If
        one ever gains a constraint it would go silently unchecked.
        """
        system = [q for q in self._questions() if q.get("control") == "system"]
        self.assertTrue(system, "expected some system-control questions to exist")

        with_rules = [
            q.get("name")
            for q in system
            if q.get("relevant") or q.get("constraint")
        ]
        self.assertEqual(
            with_rules,
            [],
            "a system-control question gained a relevant/constraint rule; the "
            "validation exclusion would now skip it without anyone noticing",
        )
