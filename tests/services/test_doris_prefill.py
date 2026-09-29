"""DORIS certificate prefill from the VA interview (digitva-hln).

One case per row of docs/policy/doris-cod-workflow.md, "Prefill from the
interview", plus don't know / refused / missing and the age and maternal
variants. Pure: no database.
"""

import unittest

from app.services.doris_certificate import normalize_certificate
from app.services.doris_prefill import doris_prefill_from_payload, doris_prefill_record

ADULT = {
    "Id10019": "male",
    "Id10020": "yes",
    "Id10021": "1960-05-17",
    "Id10022": "yes",
    "Id10023": "2025-08-04T00:00:00.000+05:30",
    "isNeonatal": "0",
    "isChild": "0",
    "isAdult": "1",
    "ageInMonthsByYear": 781,
}
# Born and died with both dates known, 3 days old.
NEONATE = {
    "Id10019": "female",
    "Id10020": "yes",
    "Id10021": "2025-08-01",
    "Id10022": "yes",
    "Id10023": "2025-08-04",
    "isNeonatal": "1",
    "isChild": "0",
    "ageInMonthsByYear": 0,
}
CHILD_UNDER_ONE = {**NEONATE, "Id10021": "2025-01-10", "isNeonatal": 0, "isChild": 1, "ageInMonthsByYear": 6.0}
CHILD_OVER_ONE = {**NEONATE, "Id10021": "2022-01-10", "isNeonatal": 0, "isChild": 1, "ageInMonthsByYear": 42}
WOMAN = {**ADULT, "Id10019": "female", "Id10021": "1995-03-02"}
INJURY = {**ADULT, "Id10077": "yes", "Id10079": "no", "Id10082": "no", "Id10083": "yes"}

ABSENT = object()


def prefill(payload):
    return doris_prefill_from_payload(payload)


def field(payload, path):
    certificate, _provenance = prefill(payload)
    section, name = path.split(".")
    return certificate.get(section, {}).get(name, ABSENT)


class PrefillCaseTests(unittest.TestCase):
    """(payload, "Section.Field", expected value, expected sources)."""

    CASES = [
        # Sex
        ("male", ADULT, "AdministrativeData.Sex", 1, ["Id10019"]),
        ("female", WOMAN, "AdministrativeData.Sex", 2, ["Id10019"]),
        ("undetermined", {**ADULT, "Id10019": "undetermined"}, "AdministrativeData.Sex", 9, ["Id10019"]),
        ("sex missing", {**ADULT, "Id10019": None}, "AdministrativeData.Sex", ABSENT, None),
        # DateBirth
        ("full birth date", ADULT, "AdministrativeData.DateBirth", "1960-05-17", ["Id10021"]),
        ("1 Jan at 50+ is a year", {**ADULT, "Id10021": "1960-01-01"}, "AdministrativeData.DateBirth", "1960", ["Id10021"]),
        ("1 Jan under 50 stays", {**WOMAN, "Id10021": "1990-01-01"}, "AdministrativeData.DateBirth", "1990-01-01", ["Id10021"]),
        ("1 Jan, year of death only", {**ADULT, "Id10021": "1940-01-01", "Id10022": "no", "Id10023": None, "Id10024": "2025-01-01"}, "AdministrativeData.DateBirth", "1940", ["Id10021"]),
        ("dob month-year", {**ADULT, "Id10020": "no", "Id10021": None, "dob_precision": "month_year", "dob_month_year": "1961-07-01"}, "AdministrativeData.DateBirth", "1961-07", ["dob_month_year"]),
        ("dob year", {**ADULT, "Id10020": "ref", "Id10021": None, "dob_precision": "year", "dob_year": "1961-01-01"}, "AdministrativeData.DateBirth", "1961", ["dob_year"]),
        ("dob neither", {**ADULT, "Id10020": "no", "Id10021": None, "dob_precision": "neither"}, "AdministrativeData.DateBirth", ABSENT, None),
        ("dob date not asked", {**ADULT, "Id10020": "no"}, "AdministrativeData.DateBirth", ABSENT, None),
        # DateDeath
        ("death date part, no tz shift", ADULT, "AdministrativeData.DateDeath", "2025-08-04", ["Id10023"]),
        ("death from Id10023_a", {**ADULT, "Id10023": None, "Id10023_a": "2025-08-05"}, "AdministrativeData.DateDeath", "2025-08-05", ["Id10023"]),
        ("death year only", {**ADULT, "Id10022": "no", "Id10023": None, "Id10024": "2024-01-01"}, "AdministrativeData.DateDeath", "2024", ["Id10024"]),
        ("death refused, year", {**ADULT, "Id10022": "ref", "Id10023": None, "Id10024": "2024-01-01"}, "AdministrativeData.DateDeath", "2024", ["Id10024"]),
        # EstimatedAge only when a date is missing
        ("no age when both dates", {**ADULT, "age_adult": 65}, "AdministrativeData.EstimatedAge", ABSENT, None),
        ("adult age", {**ADULT, "Id10020": "no", "Id10021": None, "age_group": "adult", "age_adult": "65"}, "AdministrativeData.EstimatedAge", "P65Y", ["age_adult"]),
        ("neonate hours", {**NEONATE, "Id10022": "no", "Id10023": None, "age_group": "neonate", "age_neonate_days": 0, "age_neonate_hours": "5"}, "AdministrativeData.EstimatedAge", "PT5H", ["age_neonate_hours"]),
        ("neonate days", {**NEONATE, "Id10020": "no", "age_group": "neonate", "age_neonate_days": "3.0"}, "AdministrativeData.EstimatedAge", "P3D", ["age_neonate_days"]),
        ("child months", {**CHILD_UNDER_ONE, "Id10020": "no", "age_group": "child", "age_child_unit": "months", "age_child_months": 8}, "AdministrativeData.EstimatedAge", "P8M", ["age_child_months"]),
        ("child years", {**CHILD_OVER_ONE, "Id10020": "no", "age_group": "child", "age_child_unit": "years", "age_child_years": 3}, "AdministrativeData.EstimatedAge", "P3Y", ["age_child_years"]),
        # Stillborn (neonates only)
        ("cried -> not stillborn", {**NEONATE, "Id10104": "yes"}, "FetalOrInfantDeath.Stillborn", 0, ["Id10104"]),
        ("moved and breathed", {**NEONATE, "Id10109": "yes", "Id10110": "yes"}, "FetalOrInfantDeath.Stillborn", 0, ["Id10109", "Id10110"]),
        ("born dead", {**NEONATE, "Id10104": "no", "Id10114": "yes"}, "FetalOrInfantDeath.Stillborn", 1, ["Id10114"]),
        ("not born dead", {**NEONATE, "Id10114": "no"}, "FetalOrInfantDeath.Stillborn", 0, ["Id10114"]),
        ("born dead dk", {**NEONATE, "Id10114": "dk"}, "FetalOrInfantDeath.Stillborn", 9, ["Id10114"]),
        ("born dead ref", {**NEONATE, "Id10114": "ref"}, "FetalOrInfantDeath.Stillborn", 9, ["Id10114"]),
        ("stillborn not for a child", {**CHILD_UNDER_ONE, "Id10114": "yes"}, "FetalOrInfantDeath.Stillborn", ABSENT, None),
        # DeathWithin24h: hours survived
        ("neonate hours survived", {**NEONATE, "age_neonate_days": 0, "age_neonate_hours": 7}, "FetalOrInfantDeath.DeathWithin24h", 7, ["age_neonate_hours"]),
        ("same-day hours", {**NEONATE, "Id10021": "2025-08-04", "doris_hours_survived": "3"}, "FetalOrInfantDeath.DeathWithin24h", 3, ["doris_hours_survived"]),
        ("days-only 0 is empty", {**NEONATE, "age_neonate_days": 0}, "FetalOrInfantDeath.DeathWithin24h", ABSENT, None),
        ("stillbirth has no hours", {**NEONATE, "Id10114": "yes", "doris_hours_survived": 0}, "FetalOrInfantDeath.DeathWithin24h", ABSENT, None),
        ("same-day hours 88 refused", {**NEONATE, "Id10021": "2025-08-04", "doris_hours_survived": 88}, "FetalOrInfantDeath.DeathWithin24h", ABSENT, None),
        ("same-day hours 99 dk", {**NEONATE, "Id10021": "2025-08-04", "doris_hours_survived": "99"}, "FetalOrInfantDeath.DeathWithin24h", ABSENT, None),
        # MultiplePregnancy
        ("twin", {**NEONATE, "Id10354": "yes"}, "FetalOrInfantDeath.MultiplePregnancy", 1, ["Id10354"]),
        ("single", {**CHILD_UNDER_ONE, "Id10354": "no"}, "FetalOrInfantDeath.MultiplePregnancy", 0, ["Id10354"]),
        ("multiple dk", {**NEONATE, "Id10354": "dk"}, "FetalOrInfantDeath.MultiplePregnancy", 9, ["Id10354"]),
        ("fetal fields over one year", {**CHILD_OVER_ONE, "Id10354": "yes"}, "FetalOrInfantDeath.MultiplePregnancy", ABSENT, None),
        ("fetal fields for adults", {**ADULT, "Id10354": "yes"}, "FetalOrInfantDeath.MultiplePregnancy", ABSENT, None),
        # BirthWeight
        ("weight float", {**NEONATE, "Id10366": 2000.0}, "FetalOrInfantDeath.BirthWeight", 2000, ["Id10366"]),
        ("weight string", {**NEONATE, "Id10366": "2450"}, "FetalOrInfantDeath.BirthWeight", 2450, ["Id10366"]),
        ("weight 0 is empty", {**NEONATE, "Id10366": 0}, "FetalOrInfantDeath.BirthWeight", ABSENT, None),
        ("weight 2 (kg) is empty", {**NEONATE, "Id10366": 2}, "FetalOrInfantDeath.BirthWeight", ABSENT, None),
        ("weight 3 (kg) is empty", {**NEONATE, "Id10366": "3"}, "FetalOrInfantDeath.BirthWeight", ABSENT, None),
        ("weight 99 is empty", {**NEONATE, "Id10366": 99}, "FetalOrInfantDeath.BirthWeight", ABSENT, None),
        ("weight 100 is the floor", {**NEONATE, "Id10366": 100}, "FetalOrInfantDeath.BirthWeight", 100, ["Id10366"]),
        ("weight 9999 is the ceiling", {**NEONATE, "Id10366": 9999}, "FetalOrInfantDeath.BirthWeight", 9999, ["Id10366"]),
        ("weight over range", {**NEONATE, "Id10366": 12000}, "FetalOrInfantDeath.BirthWeight", ABSENT, None),
        # PregnancyWeeks
        ("weeks direct", {**NEONATE, "doris_pregnancy_weeks": "38", "Id10367": 9}, "FetalOrInfantDeath.PregnancyWeeks", 38, ["doris_pregnancy_weeks"]),
        ("weeks from months", {**NEONATE, "Id10367": "9.0"}, "FetalOrInfantDeath.PregnancyWeeks", 39, ["Id10367"]),
        ("weeks 8 is the floor", {**NEONATE, "doris_pregnancy_weeks": 8}, "FetalOrInfantDeath.PregnancyWeeks", 8, ["doris_pregnancy_weeks"]),
        ("weeks 48 is the ceiling", {**NEONATE, "doris_pregnancy_weeks": 48}, "FetalOrInfantDeath.PregnancyWeeks", 48, ["doris_pregnancy_weeks"]),
        ("weeks 88 falls back to months", {**NEONATE, "doris_pregnancy_weeks": 88, "Id10367": 9}, "FetalOrInfantDeath.PregnancyWeeks", 39, ["Id10367"]),
        ("weeks 99, no months", {**NEONATE, "doris_pregnancy_weeks": "99"}, "FetalOrInfantDeath.PregnancyWeeks", ABSENT, None),
        ("months 7", {**CHILD_UNDER_ONE, "Id10367": 7}, "FetalOrInfantDeath.PregnancyWeeks", 30, ["Id10367"]),
        ("months 0 skipped", {**NEONATE, "Id10367": 0}, "FetalOrInfantDeath.PregnancyWeeks", ABSENT, None),
        ("months 88 skipped", {**NEONATE, "Id10367": 88}, "FetalOrInfantDeath.PregnancyWeeks", ABSENT, None),
        ("months 99 skipped", {**NEONATE, "Id10367": "99"}, "FetalOrInfantDeath.PregnancyWeeks", ABSENT, None),
        # AgeMother
        ("mother age", {**NEONATE, "doris_mother_age": "24"}, "FetalOrInfantDeath.AgeMother", 24, ["doris_mother_age"]),
        ("mother age out of range", {**NEONATE, "doris_mother_age": 5}, "FetalOrInfantDeath.AgeMother", ABSENT, None),
        ("mother age 60 is the ceiling", {**NEONATE, "doris_mother_age": 60}, "FetalOrInfantDeath.AgeMother", 60, ["doris_mother_age"]),
        ("mother age 88 refused", {**NEONATE, "doris_mother_age": 88}, "FetalOrInfantDeath.AgeMother", ABSENT, None),
        ("mother age 99 dk", {**NEONATE, "doris_mother_age": "99"}, "FetalOrInfantDeath.AgeMother", ABSENT, None),
        # Maternal
        ("pregnant at death", {**WOMAN, "Id10305": "yes"}, "MaternalDeath.TimeFromPregnancy", 0, ["Id10305"]),
        ("in labour", {**WOMAN, "Id10305": "no", "Id10312": "yes"}, "MaternalDeath.TimeFromPregnancy", 0, ["Id10312"]),
        ("within 24h of delivery", {**WOMAN, "Id10305": "no", "Id10312": "no", "Id10313": "yes", "Id10314": "yes"}, "MaternalDeath.TimeFromPregnancy", 1, ["Id10314"]),
        ("postpartum < 42 d", {**WOMAN, "Id10305": "no", "Id10312": "no", "Id10313": "yes", "Id10314": "no", "Id10306": "yes"}, "MaternalDeath.TimeFromPregnancy", 1, ["Id10306"]),
        ("abortion within 6 weeks", {**WOMAN, "Id10305": "no", "Id10312": "no", "Id10313": "no", "Id10334": "yes"}, "MaternalDeath.TimeFromPregnancy", 1, ["Id10334"]),
        ("43 d to 1 y", {**WOMAN, "Id10305": "no", "Id10312": "no", "Id10313": "yes", "Id10314": "no", "Id10306": "no", "Id10308": "yes"}, "MaternalDeath.TimeFromPregnancy", 2, ["Id10308"]),
        ("43 d to 1 y was pregnant", {**WOMAN, "Id10305": "no", "Id10312": "no", "Id10313": "yes", "Id10314": "no", "Id10306": "no", "Id10308": "yes"}, "MaternalDeath.WasPregnant", 1, ["Id10308"]),
        ("delivered, timing dk", {**WOMAN, "Id10305": "no", "Id10312": "no", "Id10313": "yes", "Id10314": "dk", "Id10306": "dk", "Id10308": "ref"}, "MaternalDeath.TimeFromPregnancy", 9, ["Id10313", "Id10314", "Id10306", "Id10308"]),
        ("delivered, timing dk, pregnant", {**WOMAN, "Id10305": "no", "Id10312": "no", "Id10313": "yes", "Id10314": "dk", "Id10306": "dk"}, "MaternalDeath.WasPregnant", 1, ["Id10313"]),
        ("delivered, Id10308 blank is not no", {**WOMAN, "Id10305": "no", "Id10312": "no", "Id10313": "yes", "Id10314": "no", "Id10306": "no"}, "MaternalDeath.WasPregnant", 1, ["Id10313"]),
        ("delivered, Id10308 blank: no band", {**WOMAN, "Id10305": "no", "Id10312": "no", "Id10313": "yes", "Id10314": "no", "Id10306": "no"}, "MaternalDeath.TimeFromPregnancy", ABSENT, None),
        ("birth over a year ago: no band", {**WOMAN, "Id10305": "no", "Id10312": "no", "Id10313": "yes", "Id10314": "no", "Id10306": "no", "Id10308": "no", "Id10310": "yes"}, "MaternalDeath.TimeFromPregnancy", ABSENT, None),
        ("birth over a year ago: Id10310", {**WOMAN, "Id10305": "no", "Id10312": "no", "Id10313": "yes", "Id10314": "no", "Id10306": "no", "Id10308": "no", "Id10310": "yes"}, "MaternalDeath.WasPregnant", 0, ["Id10310"]),
        ("confirmed not pregnant", {**WOMAN, "Id10305": "no", "Id10312": "no", "Id10313": "no", "Id10334": "no", "Id10308": "no", "Id10310": "yes"}, "MaternalDeath.WasPregnant", 0, ["Id10310"]),
        ("confirmed, no band", {**WOMAN, "Id10305": "no", "Id10310": "yes"}, "MaternalDeath.TimeFromPregnancy", ABSENT, None),
        ("all dk", {**WOMAN, "Id10305": "dk", "Id10312": "dk", "Id10313": "ref", "Id10334": "dk"}, "MaternalDeath.WasPregnant", 9, ["Id10305", "Id10312", "Id10313", "Id10334"]),
        ("mixed no/dk is empty", {**WOMAN, "Id10305": "no", "Id10312": "dk"}, "MaternalDeath.WasPregnant", ABSENT, None),
        ("nothing asked", ADULT, "MaternalDeath.WasPregnant", ABSENT, None),
        # Manner of death
        ("not an injury", {**ADULT, "Id10077": "no"}, "MannerOfDeath.MannerOfDeath", 0, ["Id10077"]),
        ("injury dk", {**ADULT, "Id10077": "dk"}, "MannerOfDeath.MannerOfDeath", 9, ["Id10077"]),
        ("accident", {**INJURY, "Id10098": "yes"}, "MannerOfDeath.MannerOfDeath", 1, ["Id10098"]),
        ("self-inflicted", {**INJURY, "Id10098": "no", "Id10099": "yes"}, "MannerOfDeath.MannerOfDeath", 2, ["Id10099"]),
        ("assault", {**INJURY, "Id10098": "no", "Id10099": "no", "Id10100": "yes"}, "MannerOfDeath.MannerOfDeath", 3, ["Id10100"]),
        ("legal intervention wins", {**INJURY, "Id10098": "no", "Id10099": "no", "Id10100": "yes", "doris_injury_legal_war": "legal"}, "MannerOfDeath.MannerOfDeath", 4, ["doris_injury_legal_war"]),
        ("war wins", {**INJURY, "Id10098": "yes", "doris_injury_legal_war": "war"}, "MannerOfDeath.MannerOfDeath", 5, ["doris_injury_legal_war"]),
        ("neither falls through", {**INJURY, "Id10098": "yes", "doris_injury_legal_war": "neither"}, "MannerOfDeath.MannerOfDeath", 1, ["Id10098"]),
        ("force of nature", {**INJURY, "Id10095": "yes"}, "MannerOfDeath.MannerOfDeath", 1, ["Id10095"]),
        ("all intent no -> 6", {**INJURY, "Id10098": "no", "Id10099": "no", "Id10100": "no"}, "MannerOfDeath.MannerOfDeath", 6, ["Id10098", "Id10099", "Id10100"]),
        ("intent dk -> 9", {**INJURY, "Id10098": "no", "Id10099": "dk", "Id10100": "ref"}, "MannerOfDeath.MannerOfDeath", 9, ["Id10098", "Id10099", "Id10100"]),
        ("all intent dk -> 9", {**INJURY, "Id10098": "dk", "Id10100": "dk"}, "MannerOfDeath.MannerOfDeath", 9, ["Id10098", "Id10100"]),
        ("intent none answered -> 6", INJURY, "MannerOfDeath.MannerOfDeath", 6, ["Id10077"]),
        ("injury description", {**INJURY, "Id10098": "yes"}, "MannerOfDeath.DescriptionExternalCause", "Fall", ["Id10083"]),
        ("injury date", {**INJURY, "doris_injury_date_known": "full", "doris_injury_date": "2025-08-01"}, "MannerOfDeath.DateOfExternalCauseOrPoisoning", "2025-08-01", ["doris_injury_date"]),
        ("injury month-year", {**INJURY, "doris_injury_date_known": "month_year", "doris_injury_month_year": "2025-07-01"}, "MannerOfDeath.DateOfExternalCauseOrPoisoning", "2025-07", ["doris_injury_month_year"]),
        ("injury date unknown", {**INJURY, "doris_injury_date_known": "unknown"}, "MannerOfDeath.DateOfExternalCauseOrPoisoning", ABSENT, None),
        ("injury date without its answer", {**INJURY, "doris_injury_date": "2025-08-01"}, "MannerOfDeath.DateOfExternalCauseOrPoisoning", ABSENT, None),
        ("injury full date blank", {**INJURY, "doris_injury_date_known": "full"}, "MannerOfDeath.DateOfExternalCauseOrPoisoning", ABSENT, None),
        ("injury place", {**INJURY, "doris_injury_place": "4"}, "MannerOfDeath.PlaceOfOccuranceExternalCause", 4, ["doris_injury_place"]),
        ("injury place unknown", {**INJURY, "doris_injury_place": "9"}, "MannerOfDeath.PlaceOfOccuranceExternalCause", 9, ["doris_injury_place"]),
        ("injury place refused", {**INJURY, "doris_injury_place": "ref"}, "MannerOfDeath.PlaceOfOccuranceExternalCause", ABSENT, None),
        ("no injury, no place", {**ADULT, "Id10077": "no", "doris_injury_place": "4"}, "MannerOfDeath.PlaceOfOccuranceExternalCause", ABSENT, None),
        # Surgery
        ("no operation", {**ADULT, "doris_surgery_performed": "no"}, "Surgery.WasPerformed", 0, ["doris_surgery_performed"]),
        ("operation dk", {**ADULT, "doris_surgery_performed": "dk"}, "Surgery.WasPerformed", 9, ["doris_surgery_performed"]),
        ("within 28 days", {**ADULT, "doris_surgery_performed": "yes", "doris_surgery_when_unit": "days", "doris_surgery_when": "28"}, "Surgery.WasPerformed", 1, ["doris_surgery_performed", "doris_surgery_when"]),
        ("4 weeks", {**ADULT, "doris_surgery_performed": "yes", "doris_surgery_when_unit": "weeks", "doris_surgery_when": 4}, "Surgery.WasPerformed", 1, ["doris_surgery_performed", "doris_surgery_when"]),
        ("29 days", {**ADULT, "doris_surgery_performed": "yes", "doris_surgery_when_unit": "days", "doris_surgery_when": 29}, "Surgery.WasPerformed", 0, ["doris_surgery_performed", "doris_surgery_when"]),
        ("2 months", {**ADULT, "doris_surgery_performed": "yes", "doris_surgery_when_unit": "months", "doris_surgery_when": 2}, "Surgery.WasPerformed", 0, ["doris_surgery_performed", "doris_surgery_when"]),
        ("when 99 dk", {**ADULT, "doris_surgery_performed": "yes", "doris_surgery_when": 99}, "Surgery.WasPerformed", 9, ["doris_surgery_performed", "doris_surgery_when"]),
        ("when 88 refused", {**ADULT, "doris_surgery_performed": "yes", "doris_surgery_when": "88"}, "Surgery.WasPerformed", 9, ["doris_surgery_performed", "doris_surgery_when"]),
        ("when 99 without yes", {**ADULT, "doris_surgery_performed": "no", "doris_surgery_when": 99}, "Surgery.WasPerformed", 0, ["doris_surgery_performed"]),
        ("when 99 with a stale unit", {**ADULT, "doris_surgery_performed": "yes", "doris_surgery_when": 99, "doris_surgery_when_unit": "days"}, "Surgery.WasPerformed", 9, ["doris_surgery_performed", "doris_surgery_when"]),
        ("120 days", {**ADULT, "doris_surgery_performed": "yes", "doris_surgery_when_unit": "days", "doris_surgery_when": 120}, "Surgery.WasPerformed", 0, ["doris_surgery_performed", "doris_surgery_when"]),
        ("when blank, unit only", {**ADULT, "doris_surgery_performed": "yes", "doris_surgery_when_unit": "days"}, "Surgery.WasPerformed", ABSENT, None),
        ("when blank", {**ADULT, "doris_surgery_performed": "yes"}, "Surgery.WasPerformed", ABSENT, None),
        ("direct wins over Id10426", {**ADULT, "doris_surgery_performed": "no", "Id10426": "yes"}, "Surgery.WasPerformed", 0, ["doris_surgery_performed"]),
        ("reason composed", {**ADULT, "doris_surgery_performed": "yes", "doris_surgery_when_unit": "days", "doris_surgery_when": 3, "doris_surgery_type": " Laparotomy ", "doris_surgery_reason": "perforated ulcer"}, "Surgery.Reason", "Laparotomy for perforated ulcer", ["doris_surgery_type", "doris_surgery_reason"]),
        ("no reason beyond 28 days", {**ADULT, "doris_surgery_performed": "yes", "doris_surgery_when_unit": "years", "doris_surgery_when": 2, "doris_surgery_type": "Appendicectomy"}, "Surgery.Reason", ABSENT, None),
        ("Id10426 yes", {**ADULT, "Id10426": "yes"}, "Surgery.WasPerformed", 1, ["Id10426"]),
        ("Id10426 no", {**ADULT, "Id10426": "no"}, "Surgery.WasPerformed", 0, ["Id10426"]),
        ("hysterectomy with pregnancy event", {**WOMAN, "Id10312": "yes", "Id10340": "yes", "Id10426": "no"}, "Surgery.WasPerformed", 1, ["Id10340"]),
        ("hysterectomy reason", {**WOMAN, "Id10312": "yes", "Id10340": "yes"}, "Surgery.Reason", "Hysterectomy", ["Id10340"]),
        ("hysterectomy alone ignored", {**WOMAN, "Id10299": "yes", "Id10310": "yes", "Id10340": "yes", "Id10426": "no"}, "Surgery.WasPerformed", 0, ["Id10426"]),
        ("hysterectomy alone, nothing else", {**WOMAN, "Id10310": "yes", "Id10340": "yes"}, "Surgery.WasPerformed", ABSENT, None),
        ("neonate without direct answer", {**NEONATE, "Id10425": "yes"}, "Surgery.WasPerformed", ABSENT, None),
        ("neonate direct answer", {**NEONATE, "doris_surgery_performed": "yes", "doris_surgery_when_unit": "days", "doris_surgery_when": 1}, "Surgery.WasPerformed", 1, ["doris_surgery_performed", "doris_surgery_when"]),
        # Autopsy
        ("autopsy requested", {**ADULT, "doris_autopsy_requested": "yes", "doris_autopsy_findings": "no"}, "Autopsy.WasRequested", 1, ["doris_autopsy_requested"]),
        ("autopsy findings", {**ADULT, "doris_autopsy_requested": "yes", "doris_autopsy_findings": "yes"}, "Autopsy.Findings", 1, ["doris_autopsy_findings"]),
        ("findings only when requested", {**ADULT, "doris_autopsy_requested": "no", "doris_autopsy_findings": "yes"}, "Autopsy.Findings", ABSENT, None),
        ("autopsy refused", {**ADULT, "doris_autopsy_requested": "ref"}, "Autopsy.WasRequested", 9, ["doris_autopsy_requested"]),
    ]

    def test_each_mapping_row(self):
        for name, payload, path, expected, sources in self.CASES:
            with self.subTest(name):
                certificate, provenance = prefill(payload)
                section, key = path.split(".")
                self.assertEqual(certificate.get(section, {}).get(key, ABSENT), expected)
                if expected is ABSENT:
                    self.assertNotIn(path, provenance)
                else:
                    self.assertEqual(provenance[path]["sources"], sources)

    def test_every_case_passes_normalize_certificate(self):
        for name, payload, _path, _expected, _sources in self.CASES:
            with self.subTest(name):
                certificate, _provenance = prefill(payload)
                wrapped = {
                    "ICDVersion": "ICD11",
                    "Part1": [{"Conditions": [{"Text": "Cause"}]}],
                    **certificate,
                }
                normalized = normalize_certificate(wrapped)
                for section, values in certificate.items():
                    self.assertEqual(normalized[section], values)


class PrefillShapeTests(unittest.TestCase):
    def test_empty_and_non_dict_payloads_prefill_nothing(self):
        for payload in (None, {}, [], "x"):
            with self.subTest(payload=payload):
                self.assertEqual(prefill(payload), ({}, {}))

    def test_causes_and_coder_fields_are_never_prefilled(self):
        everything = {
            **WOMAN,
            "Id10305": "yes",
            "Id10077": "yes",
            "Id10098": "yes",
            "doris_surgery_performed": "yes",
            "doris_surgery_when_unit": "days",
            "doris_surgery_when": 2,
            "doris_surgery_type": "Caesarean section",
        }
        certificate, _provenance = prefill(everything)
        self.assertIn("MaternalDeath", certificate)
        self.assertIn("Surgery", certificate)
        self.assertNotIn("Part1", certificate)
        self.assertNotIn("Part2", certificate)
        self.assertNotIn("PregnancyContribute", certificate["MaternalDeath"])
        self.assertNotIn("Date", certificate["Surgery"])

    def test_converted_weeks_carry_a_note(self):
        _certificate, provenance = prefill({**NEONATE, "Id10367": 9})
        self.assertEqual(provenance["FetalOrInfantDeath.PregnancyWeeks"]["note"], "converted from months")

    def test_numbers_as_strings_or_floats_agree(self):
        as_text = {**NEONATE, "Id10354": "yes", "Id10366": "2000", "Id10367": "9", "doris_mother_age": "30"}
        as_number = {**NEONATE, "isNeonatal": 1.0, "Id10354": "yes", "Id10366": 2000.0, "Id10367": 9.0, "doris_mother_age": 30}
        self.assertEqual(prefill(as_text)[0], prefill(as_number)[0])
        self.assertEqual(prefill(as_text)[0]["FetalOrInfantDeath"]["BirthWeight"], 2000)

    def test_non_integer_and_garbage_values_are_left_out(self):
        certificate, _provenance = prefill({**NEONATE, "Id10366": "2.5kg", "doris_mother_age": 24.5, "Id10021": "not a date"})
        self.assertNotIn("BirthWeight", certificate.get("FetalOrInfantDeath", {}))
        self.assertNotIn("AgeMother", certificate.get("FetalOrInfantDeath", {}))
        self.assertIn("DateDeath", certificate["AdministrativeData"])
        self.assertNotIn("DateBirth", certificate["AdministrativeData"])


class PrefillRecordTests(unittest.TestCase):
    PAYLOAD = {**INJURY, "Id10098": "yes", "doris_injury_place": "4"}

    def _saved(self, **changes):
        certificate, _provenance = prefill(self.PAYLOAD)
        saved = normalize_certificate(
            {"ICDVersion": "ICD11", "Part1": [{"Conditions": [{"Text": "Fall"}]}], **certificate}
        )
        for path, value in changes.items():
            section, key = path.split("__")
            saved[section][key] = value
        return saved

    def test_unchanged_certificate_records_every_field_unchanged(self):
        record = doris_prefill_record(self.PAYLOAD, self._saved())
        self.assertEqual(record["version"], 1)
        self.assertIn("MannerOfDeath.MannerOfDeath", record["fields"])
        self.assertTrue(record["fields"])
        self.assertTrue(all(entry["changed"] is False for entry in record["fields"].values()))

    def test_one_edit_flips_exactly_that_field(self):
        record = doris_prefill_record(self.PAYLOAD, self._saved(MannerOfDeath__MannerOfDeath=3))
        changed = [path for path, entry in record["fields"].items() if entry["changed"]]
        self.assertEqual(changed, ["MannerOfDeath.MannerOfDeath"])

    def test_a_removed_field_counts_as_changed(self):
        saved = self._saved()
        del saved["MannerOfDeath"]["PlaceOfOccuranceExternalCause"]
        record = doris_prefill_record(self.PAYLOAD, saved)
        self.assertTrue(record["fields"]["MannerOfDeath.PlaceOfOccuranceExternalCause"]["changed"])

    def test_the_record_carries_no_answer_values(self):
        payload = {**self.PAYLOAD, "Id10021": "1960-05-17"}
        record = doris_prefill_record(payload, self._saved())
        self.assertIn("AdministrativeData.DateBirth", record["fields"])
        self.assertEqual(set(record["fields"]["AdministrativeData.DateBirth"]), {"sources", "changed"})
        self.assertNotIn("1960", repr(record))

    def test_nothing_prefilled_records_nothing(self):
        self.assertEqual(doris_prefill_record({}, {"ICDVersion": "ICD11"}), {"version": 1, "fields": {}})


if __name__ == "__main__":
    unittest.main()
