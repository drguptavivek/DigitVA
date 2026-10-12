"""Server guard for the DORIS certificate rules V1-V6
(docs/policy/doris-certificate-rules.md). Pure: no database."""

import copy
import unittest

from app.services.doris_certificate import _age_days, drop_inapplicable_sections, normalize_certificate
from app.services.doris_prefill import doris_prefill_from_payload

LINE = {"Conditions": [{"Text": "Fall"}]}
FETAL = {"Stillborn": 0, "DeathWithin24h": 5, "BirthWeight": 2000}
EXTERNAL = {"DateOfExternalCauseOrPoisoning": "2025-01-02", "DescriptionExternalCause": "fell", "PlaceOfOccuranceExternalCause": 4}


def cert(age="P65Y", sex=1, **sections):
    admin = {"EstimatedAge": age}
    if sex is not None:
        admin["Sex"] = sex
    return normalize_certificate({"ICDVersion": "ICD11", "Part1": [LINE], "AdministrativeData": admin, **copy.deepcopy(sections)})


class DropTests(unittest.TestCase):
    def test_adult_loses_fetal_section(self):
        self.assertNotIn("FetalOrInfantDeath", cert(FetalOrInfantDeath=FETAL))

    def test_infant_keeps_fetal_section_and_hours_under_a_week(self):
        out = cert(age="P3D", FetalOrInfantDeath=FETAL)
        self.assertEqual(out["FetalOrInfantDeath"], FETAL)
        self.assertEqual(cert(age="PT5H", FetalOrInfantDeath=FETAL)["FetalOrInfantDeath"], FETAL)

    def test_age_boundaries(self):
        self.assertIn("DeathWithin24h", cert(age="P6D", FetalOrInfantDeath=FETAL)["FetalOrInfantDeath"])
        self.assertNotIn("DeathWithin24h", cert(age="P7D", FetalOrInfantDeath=FETAL)["FetalOrInfantDeath"])
        self.assertIn("FetalOrInfantDeath", cert(age="P11M", FetalOrInfantDeath=FETAL))
        self.assertNotIn("FetalOrInfantDeath", cert(age="P12M", FetalOrInfantDeath=FETAL))
        self.assertNotIn("FetalOrInfantDeath", cert(age="P1Y", FetalOrInfantDeath=FETAL))

    def test_stillborn_yes_drops_hours(self):
        out = cert(age="P1D", FetalOrInfantDeath={"Stillborn": 1, "DeathWithin24h": 3})
        self.assertEqual(out["FetalOrInfantDeath"], {"Stillborn": 1})

    def test_unknown_age_hides_nothing_by_age(self):
        out = normalize_certificate({"ICDVersion": "ICD11", "Part1": [LINE], "FetalOrInfantDeath": FETAL})
        self.assertEqual(out["FetalOrInfantDeath"], FETAL)

    def test_maternal_only_for_female(self):
        maternal = {"WasPregnant": 1, "TimeFromPregnancy": 1}
        for sex in (1, 9, None):
            self.assertNotIn("MaternalDeath", cert(sex=sex, MaternalDeath=maternal))
        self.assertEqual(cert(sex=2, MaternalDeath=maternal)["MaternalDeath"], maternal)

    def test_pregnancy_followups_need_was_pregnant_yes(self):
        both = {"TimeFromPregnancy": 1, "PregnancyContribute": 1}
        self.assertEqual(cert(sex=2, MaternalDeath={"WasPregnant": 1, **both})["MaternalDeath"], {"WasPregnant": 1, **both})
        for answer in (0, 9):
            self.assertEqual(cert(sex=2, MaternalDeath={"WasPregnant": answer, **both})["MaternalDeath"], {"WasPregnant": answer})
        self.assertNotIn("MaternalDeath", cert(sex=2, MaternalDeath=both))

    def test_surgery_details_need_yes(self):
        detail = {"Date": "2025-01-02", "Reason": "appendix"}
        self.assertEqual(cert(Surgery={"WasPerformed": 1, **detail})["Surgery"], {"WasPerformed": 1, **detail})
        for answer in (0, 9):
            self.assertEqual(cert(Surgery={"WasPerformed": answer, **detail})["Surgery"], {"WasPerformed": answer})
        self.assertNotIn("Surgery", cert(Surgery=detail))

    def test_autopsy_findings_need_requested_yes(self):
        self.assertEqual(cert(Autopsy={"WasRequested": 0, "Findings": 1})["Autopsy"], {"WasRequested": 0})
        self.assertEqual(cert(Autopsy={"WasRequested": 1, "Findings": 1})["Autopsy"], {"WasRequested": 1, "Findings": 1})

    def test_external_cause_follows_the_stored_manner_codes(self):
        for manner in (1, 2, 3, 4, 5, 6, 7):
            self.assertEqual(cert(MannerOfDeath={"MannerOfDeath": manner, **EXTERNAL})["MannerOfDeath"], {"MannerOfDeath": manner, **EXTERNAL})
        for manner in (0, 9):
            self.assertEqual(cert(MannerOfDeath={"MannerOfDeath": manner, **EXTERNAL})["MannerOfDeath"], {"MannerOfDeath": manner})
        self.assertNotIn("MannerOfDeath", cert(MannerOfDeath=EXTERNAL))

    def test_reports_what_it_dropped_and_is_idempotent(self):
        certificate = {"AdministrativeData": {"Sex": 1, "EstimatedAge": "P40Y"}, "FetalOrInfantDeath": dict(FETAL)}
        self.assertEqual(drop_inapplicable_sections(certificate), ["FetalOrInfantDeath.Stillborn", "FetalOrInfantDeath.DeathWithin24h", "FetalOrInfantDeath.BirthWeight"])
        self.assertEqual(drop_inapplicable_sections(certificate), [])


class PrefillHonoursRulesTests(unittest.TestCase):
    def test_injury_details_are_not_prefilled_for_unknown_manner(self):
        payload = {
            "Id10019": "male", "Id10077": "yes", "Id10083": "yes", "Id10079": "no", "Id10082": "no",
            "doris_injury_place": "4", "doris_injury_date_known": "month_year", "doris_injury_month_year": "2025-03-01",
        }
        certificate, provenance = doris_prefill_from_payload(payload)
        self.assertEqual(certificate["MannerOfDeath"]["MannerOfDeath"], 6)  # unclassified intent, details shown
        self.assertIn("MannerOfDeath.PlaceOfOccuranceExternalCause", provenance)
        certificate, provenance = doris_prefill_from_payload({**payload, "Id10098": "dk"})
        self.assertEqual(certificate["MannerOfDeath"]["MannerOfDeath"], 9)
        self.assertEqual(set(certificate["MannerOfDeath"]), {"MannerOfDeath"})
        self.assertNotIn("MannerOfDeath.PlaceOfOccuranceExternalCause", provenance)


if __name__ == "__main__":
    unittest.main()


class AgeDaysMatchesEditorTests(unittest.TestCase):
    # Same table as tests/js/doris_rules_check.mjs (durationDays): keep both in step.
    def test_age_days_equals_the_editor_durationDays(self):
        for iso, days in (
            ("PT30M", 30 / 1440), ("PT90S", 90 / 86400), ("PT23H", 23 / 24), ("P6D", 6), ("P7D", 7),
            ("P364D", 364), ("P1Y", 365.25), ("PT", None), ("P1H", None), ("abc", None), ("", None),
        ):
            with self.subTest(iso=iso):
                got = _age_days(iso)
                if days is None:
                    self.assertIsNone(got)
                else:
                    self.assertIsNotNone(got)
                    self.assertAlmostEqual(got, days, places=12)
