from unittest import TestCase

from scripts.smartva_richness_assessment import (
    AGE_GROUPS,
    _is_generic_only_field,
    _map_dest_to_effective_features,
    build_determination_summary,
    build_field_differentiator_rows,
    build_field_differentiator_summary,
    build_field_endorsement_rows,
    build_field_endorsement_summary,
    build_who_to_tariff_markdown,
    build_vendor_field_scopes,
    field_is_positive,
    score_submission,
    signal_is_positive,
)


class SmartvaRichnessAssessmentTests(TestCase):
    def test_map_dest_to_effective_features_handles_duration_collapse(self):
        features = _map_dest_to_effective_features("adult", "adult_2_1")
        self.assertIn("s15", features)

    def test_map_dest_to_effective_features_handles_binary_derivations(self):
        features = _map_dest_to_effective_features("adult", "adult_2_19")
        self.assertIn("s36", features)
        self.assertIn("s36991", features)
        self.assertIn("s36992", features)

    def test_is_generic_only_field_detects_gen_targets(self):
        self.assertTrue(_is_generic_only_field(["gen_5_0", "interviewdate"]))
        self.assertFalse(_is_generic_only_field(["adult_2_1"]))

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

    def test_build_field_differentiator_rows_computes_rate_deltas(self):
        inventory = {
            "adult": {
                "fields": [
                    {
                        "field_id": "Id10477",
                        "field_label": "Narration keywords",
                        "short_label": "Narration keywords",
                        "domain": "keywords",
                        "included_in_score": True,
                        "rules": [
                            {
                                "signal_type": "multiselect_any_positive",
                                "positive_values": ["Fever"],
                            }
                        ],
                    }
                ]
            },
            "child": {"fields": []},
            "neonate": {"fields": []},
        }
        submission_rows = [
            {
                "payload_data": {"Id10477": "Fever"},
                "va_smartva_outcome": "success",
                "va_smartva_resultfor": "adult",
                "va_smartva_cause1": "TB",
            },
            {
                "payload_data": {"Id10477": ""},
                "va_smartva_outcome": "success",
                "va_smartva_resultfor": "adult",
                "va_smartva_cause1": "Undetermined",
            },
        ]

        rows = build_field_differentiator_rows(submission_rows, inventory)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["field_id"], "Id10477")
        self.assertEqual(rows[0]["field_label"], "Narration keywords")
        self.assertEqual(rows[0]["determined_positive_rate"], 1.0)
        self.assertEqual(rows[0]["undetermined_positive_rate"], 0.0)
        self.assertEqual(rows[0]["rate_delta"], 1.0)
        self.assertEqual(rows[0]["abs_rate_delta"], 1.0)

    def test_build_field_differentiator_summary_returns_top_rows(self):
        differentiators = [
            {
                "age_group": "adult",
                "field_id": "Id10477",
                "field_label": "Keywords",
                "domain": "keywords",
                "abs_rate_delta": 0.8,
            },
            {
                "age_group": "adult",
                "field_id": "Id10135",
                "field_label": "Asthma",
                "domain": "symptoms",
                "abs_rate_delta": 0.2,
            },
            {
                "age_group": "child",
                "field_id": "Id10478",
                "field_label": "Child keywords",
                "domain": "keywords",
                "abs_rate_delta": 0.6,
            },
        ]

        summary = build_field_differentiator_summary(differentiators, top_n=1)

        self.assertEqual(summary["overall_top_fields"][0]["field_id"], "Id10477")
        self.assertEqual(summary["by_age_group"]["adult"][0]["field_id"], "Id10477")
        self.assertEqual(summary["by_age_group"]["child"][0]["field_id"], "Id10478")

    def test_build_field_endorsement_rows_ranks_positive_rate(self):
        inventory = {
            "adult": {
                "fields": [
                    {
                        "field_id": "Id10477",
                        "field_label": "Narration keywords",
                        "short_label": "Narration keywords",
                        "domain": "keywords",
                        "included_in_score": True,
                        "rules": [
                            {
                                "signal_type": "multiselect_any_positive",
                                "positive_values": ["Fever"],
                            }
                        ],
                    },
                    {
                        "field_id": "Id10135",
                        "field_label": "Asthma",
                        "short_label": "Asthma",
                        "domain": "symptoms",
                        "included_in_score": True,
                        "rules": [{"signal_type": "yes_only", "positive_values": ["yes"]}],
                    },
                ]
            },
            "child": {"fields": []},
            "neonate": {"fields": []},
        }
        submission_rows = [
            {
                "payload_data": {"Id10477": "Fever", "Id10135": "yes"},
                "va_smartva_outcome": "success",
                "va_smartva_resultfor": "adult",
                "va_smartva_cause1": "TB",
            },
            {
                "payload_data": {"Id10477": "Fever", "Id10135": "no"},
                "va_smartva_outcome": "success",
                "va_smartva_resultfor": "adult",
                "va_smartva_cause1": "Undetermined",
            },
        ]

        rows = build_field_endorsement_rows(submission_rows, inventory)
        adult_all = [row for row in rows if row["age_group"] == "adult" and row["scope"] == "all"]

        self.assertEqual(adult_all[0]["field_id"], "Id10477")
        self.assertEqual(adult_all[0]["field_label"], "Narration keywords")
        self.assertEqual(adult_all[0]["positive_rate"], 1.0)
        self.assertEqual(adult_all[1]["field_id"], "Id10135")
        self.assertEqual(adult_all[1]["positive_rate"], 0.5)

    def test_build_field_endorsement_summary_returns_top_rows(self):
        endorsement_rows = [
            {
                "age_group": "adult",
                "scope": "all",
                "field_id": "Id10477",
                "field_label": "Keywords",
                "positive_rate": 0.9,
            },
            {
                "age_group": "adult",
                "scope": "all",
                "field_id": "Id10135",
                "field_label": "Asthma",
                "positive_rate": 0.5,
            },
            {
                "age_group": "child",
                "scope": "all",
                "field_id": "Id10478",
                "field_label": "Child keywords",
                "positive_rate": 0.8,
            },
            {
                "age_group": "adult",
                "scope": "determined",
                "field_id": "Id99999",
                "field_label": "Ignored for overall",
                "positive_rate": 1.0,
            },
        ]

        summary = build_field_endorsement_summary(endorsement_rows, top_n=1)

        self.assertEqual(summary["overall_top_fields"][0]["field_id"], "Id10477")
        self.assertEqual(summary["by_age_group"]["adult"][0]["field_id"], "Id10477")
        self.assertEqual(summary["by_age_group"]["child"][0]["field_id"], "Id10478")

    def test_build_who_to_tariff_markdown_includes_bottom_writeup(self):
        markdown = build_who_to_tariff_markdown(
            [
                {
                    "age_group": "adult",
                    "field_id": "Id10134",
                    "field_label": "Diabetes",
                    "short_label": "Diabetes",
                    "smartva_parameter": "s7",
                    "smartva_parameter_label": "Previous diagnosis of Diabetes",
                    "positive_count": 10,
                    "total_count": 100,
                    "positive_rate": 0.1,
                }
            ],
            filters={"project_code": "ICMR01", "site_id": None, "form_id": None, "limit": None},
        )

        self.assertIn("## Adult", markdown)
        self.assertIn("### HCE Option", markdown)
        self.assertIn("### Free-Text Option", markdown)
