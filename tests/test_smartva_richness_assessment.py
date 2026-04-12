from unittest import TestCase

from scripts.smartva_richness_assessment import (
    AGE_GROUPS,
    build_determination_summary,
    build_vendor_field_scopes,
    field_is_positive,
    score_submission,
    signal_is_positive,
)


class SmartvaRichnessAssessmentTests(TestCase):
    def test_vendor_scope_includes_keywords_by_age_group(self):
        scopes = build_vendor_field_scopes()

        self.assertEqual(set(scopes.keys()), set(AGE_GROUPS))
        self.assertIn("Id10477", scopes["adult"])
        self.assertIn("Id10478", scopes["child"])
        self.assertIn("Id10479", scopes["neonate"])
        self.assertIn("Fever", scopes["adult"]["Id10477"]["positive_values"])
        self.assertIn("fever", scopes["child"]["Id10478"]["positive_values"])
        self.assertIn("asphyxia", scopes["neonate"]["Id10479"]["positive_values"])

    def test_signal_is_positive_handles_supported_rule_types(self):
        self.assertTrue(
            signal_is_positive("yes", {"signal_type": "yes_only", "positive_values": ["yes"]})
        )
        self.assertFalse(
            signal_is_positive("no", {"signal_type": "yes_only", "positive_values": ["yes"]})
        )

        self.assertTrue(
            signal_is_positive(
                "moderate",
                {
                    "signal_type": "mapped_choice_positive",
                    "positive_values": ["mild", "moderate", "severe"],
                },
            )
        )
        self.assertFalse(
            signal_is_positive(
                "DK",
                {
                    "signal_type": "mapped_choice_positive",
                    "positive_values": ["mild", "moderate", "severe"],
                },
            )
        )

        self.assertTrue(
            signal_is_positive(
                "Fever Suicide",
                {
                    "signal_type": "multiselect_any_positive",
                    "positive_values": ["Fever", "Suicide"],
                },
            )
        )
        self.assertFalse(
            signal_is_positive(
                "",
                {
                    "signal_type": "multiselect_any_positive",
                    "positive_values": ["Fever", "Suicide"],
                },
            )
        )

        self.assertTrue(
            signal_is_positive(
                "3",
                {
                    "signal_type": "numeric_positive",
                    "positive_values": [],
                },
            )
        )
        self.assertFalse(
            signal_is_positive(
                "0",
                {
                    "signal_type": "numeric_positive",
                    "positive_values": [],
                },
            )
        )

        self.assertTrue(
            signal_is_positive(
                "free text",
                {
                    "signal_type": "informative_value",
                    "positive_values": [],
                },
            )
        )
        self.assertFalse(
            signal_is_positive(
                "",
                {
                    "signal_type": "informative_value",
                    "positive_values": [],
                },
            )
        )

    def test_field_is_positive_matches_any_rule(self):
        field_scope = {
            "field_id": "Id10477",
            "rules": [
                {
                    "signal_type": "multiselect_any_positive",
                    "positive_values": ["Fever", "Suicide"],
                }
            ],
        }

        self.assertTrue(field_is_positive({"Id10477": "Fever"}, field_scope))
        self.assertFalse(field_is_positive({"Id10477": "Malaria"}, field_scope))

    def test_score_submission_computes_domain_ratios_and_total(self):
        age_scope = {
            "domain_expected_counts": {
                "injury": 2,
                "symptoms": 4,
                "keywords": 1,
                "narration": 1,
            },
            "fields": [
                {
                    "field_id": "Id10077",
                    "domain": "injury",
                    "included_in_score": True,
                    "rules": [{"signal_type": "yes_only", "positive_values": ["yes"]}],
                },
                {
                    "field_id": "Id10099",
                    "domain": "injury",
                    "included_in_score": True,
                    "rules": [{"signal_type": "yes_only", "positive_values": ["yes"]}],
                },
                {
                    "field_id": "Id10135",
                    "domain": "symptoms",
                    "included_in_score": True,
                    "rules": [{"signal_type": "yes_only", "positive_values": ["yes"]}],
                },
                {
                    "field_id": "Id10137",
                    "domain": "symptoms",
                    "included_in_score": True,
                    "rules": [{"signal_type": "yes_only", "positive_values": ["yes"]}],
                },
                {
                    "field_id": "Id10464",
                    "domain": "symptoms",
                    "included_in_score": True,
                    "rules": [{"signal_type": "informative_value", "positive_values": []}],
                },
                {
                    "field_id": "Id10466",
                    "domain": "symptoms",
                    "included_in_score": True,
                    "rules": [{"signal_type": "informative_value", "positive_values": []}],
                },
                {
                    "field_id": "Id10477",
                    "domain": "keywords",
                    "included_in_score": True,
                    "rules": [
                        {
                            "signal_type": "multiselect_any_positive",
                            "positive_values": ["Fever", "Suicide"],
                        }
                    ],
                },
                {
                    "field_id": "Id10476",
                    "domain": "narration",
                    "included_in_score": True,
                    "rules": [{"signal_type": "informative_value", "positive_values": []}],
                },
            ],
        }
        payload = {
            "Id10077": "yes",
            "Id10099": "no",
            "Id10135": "yes",
            "Id10137": "no",
            "Id10464": "cause text",
            "Id10466": "",
            "Id10477": "Fever",
            "Id10476": "Narrative",
        }

        result = score_submission(payload, "adult", age_scope)

        self.assertEqual(result["counts"]["injury"], 1)
        self.assertEqual(result["counts"]["symptoms"], 2)
        self.assertEqual(result["counts"]["keywords"], 1)
        self.assertEqual(result["counts"]["narration"], 1)
        self.assertEqual(result["ratios"]["injury"], 0.5)
        self.assertEqual(result["ratios"]["symptoms"], 0.5)
        self.assertEqual(result["ratios"]["keywords"], 1.0)
        self.assertEqual(result["ratios"]["narration"], 1.0)
        self.assertEqual(result["total_score"], 65.0)

    def test_build_determination_summary_splits_determined_vs_undetermined(self):
        rows = [
            {
                "age_group": "adult",
                "determination": "determined",
                "total_score": 70.0,
                "injury_ratio": 0.5,
                "symptoms_ratio": 0.6,
                "keywords_ratio": 0.5,
                "narration_ratio": 1.0,
                "injury_weighted_score": 10.0,
                "symptoms_weighted_score": 30.0,
                "keywords_weighted_score": 10.0,
                "narration_weighted_score": 10.0,
            },
            {
                "age_group": "adult",
                "determination": "undetermined",
                "total_score": 50.0,
                "injury_ratio": 0.0,
                "symptoms_ratio": 0.5,
                "keywords_ratio": 0.5,
                "narration_ratio": 1.0,
                "injury_weighted_score": 0.0,
                "symptoms_weighted_score": 25.0,
                "keywords_weighted_score": 10.0,
                "narration_weighted_score": 10.0,
            },
        ]

        result = build_determination_summary(rows)

        self.assertEqual(result["summary"]["overall"]["determined"]["count"], 1)
        self.assertEqual(result["summary"]["overall"]["undetermined"]["count"], 1)
        self.assertEqual(result["summary"]["by_age_group"]["adult"]["determined"]["mean_total_score"], 70.0)
        self.assertEqual(result["summary"]["by_age_group"]["adult"]["undetermined"]["mean_total_score"], 50.0)
        self.assertEqual(len(result["comparison_rows"]), 8)
