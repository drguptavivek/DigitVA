"""Prefill a DORIS death certificate's non-cause fields from the VA interview.

The mapping is docs/policy/doris-cod-workflow.md, "Prefill from the
interview" (bead ``digitva-hln``; evidence in
docs/kb/DORIS/who-va-2022-to-doris.md). One pure function serves web and ODK
cases alike: it reads the flat payload of the active payload version, where
ODK cases simply lack the ``doris_*`` answers and fall back to the WHO
questions. Causes, intervals, ``PregnancyContribute``,
``PerinatalDescription`` and ``Surgery\\Date`` are never prefilled.

Rules the code keeps: don't know / refused give DORIS ``9`` only where DORIS
has that code and the question was asked; blank or unasked answers leave the
field out (a blank optional answer is not "no"); every value is range-checked
against ``normalize_certificate`` so an odd interview answer is dropped rather
than making the coder's first Process fail. Payload values may arrive as
strings or numbers (``"9.0"``, ``2000.0``, ``"1"`` or ``1``); dates take the
calendar date as recorded, without a time-zone shift.
"""

from __future__ import annotations

import math

from app.services.doris_certificate import MAX_TEXT_LENGTH
from app.services.who_va_answers import age_field, birth_answer
from app.services.who_va_answers import calendar_date as _date
from app.services.who_va_answers import choice as _choice
from app.services.who_va_answers import number as _number
from app.services.who_va_answers import text as _text
from app.services.who_va_answers import whole as _whole

PREFILL_RECORD_VERSION = 1

_ANSWER_CODES = {"yes": 1, "no": 0, "dk": 9, "ref": 9}
_UNKNOWN = ("dk", "ref")
_REFUSED_OR_UNKNOWN = (88, 99)  # the form's integer codes
_DURATION_DESIGNATORS = {"days": "D", "months": "M", "years": "Y"}
_SEX = {"male": 1, "female": 2, "undetermined": 9, "other": 9}

# Maternal chain: the first "yes" decides the band (0 at death, 1 within 42
# days, 2 from 43 days to one year). Id10308 is asked only after the
# six-week answers are no, so its "yes" means 43 days to a year.
_MATERNAL_BANDS = (
    ("Id10305", 0),
    ("Id10312", 0),
    ("Id10314", 1),
    ("Id10306", 1),
    ("Id10334", 1),
    ("Id10308", 2),
)
_MATERNAL_CHAIN = (
    "Id10305", "Id10312", "Id10313", "Id10314",
    "Id10306", "Id10334", "Id10308", "Id10310",
)
# A pregnancy event: any "yes" in the chain except the Id10310 confirmation.
_PREGNANCY_EVENTS = tuple(key for key in _MATERNAL_CHAIN if key != "Id10310")

_INTENT = (("Id10098", 1), ("Id10099", 2), ("Id10100", 3))
_INJURY_TYPES = (
    ("Id10079", "Road traffic injury"),
    ("Id10082", "Non-road transport injury"),
    ("Id10083", "Fall"),
    ("Id10084", "Poisoning"),
    ("Id10085", "Drowning"),
    ("Id10086", "Venomous bite or sting"),
    ("Id10087", "Injury by an animal or insect (non-venomous)"),
    ("Id10089", "Burns or fire"),
    ("Id10091", "Firearm injury"),
    ("Id10092", "Stabbed, cut or pierced"),
    ("Id10093", "Strangulation"),
    ("Id10096", "Electrocution"),
    ("Id10094", "Blunt force"),
    ("Id10095", "Force of nature"),
    ("Id10097", "Other injury"),
)
_DAYS_PER_UNIT = {"days": 1, "weeks": 7, "months": 30.4375, "years": 365.25}


# --- payload readers ---------------------------------------------------------


def _yes(payload: dict, key: str) -> bool:
    return _choice(payload, key) == "yes"


def _coded(payload: dict, key: str) -> int | None:
    """yes 1, no 0, dk/ref 9; anything else (blank, unasked) ``None``."""
    return _ANSWER_CODES.get(_choice(payload, key))


# --- sections ------------------------------------------------------------------


def _death(payload: dict) -> tuple[str, list[str], int] | None:
    """``(DateDeath, sources, year of death)`` or ``None``."""
    known = _choice(payload, "Id10022")
    if known == "yes":
        for key in ("Id10023", "Id10023_a", "Id10023_b"):
            died = _date(payload, key)
            if died is not None:
                return died.isoformat(), ["Id10023"], died.year
        return None
    if known in ("no", "ref"):
        year = _date(payload, "Id10024")
        if year is not None:
            return f"{year.year:04d}", ["Id10024"], year.year
    return None


def _birth(payload: dict, death_year: int | None) -> tuple[str, list[str]] | None:
    answer = birth_answer(payload)
    if answer is None:
        return None
    precision, key, born = answer
    if precision == "exact":
        # Interviewers key a year-only answer as 1 January (owner, 2026-09-29):
        # at age 50 or more, send the year only. Born on 1 January, the age at
        # death is exactly the difference in years.
        if (born.month, born.day) == (1, 1) and death_year is not None and death_year - born.year >= 50:
            return f"{born.year:04d}", [key]
        return born.isoformat(), [key]
    if precision == "month_year":
        return f"{born.year:04d}-{born.month:02d}", [key]
    return f"{born.year:04d}", [key]


def _estimated_age(payload: dict) -> tuple[str, list[str]] | None:
    field = age_field(payload)
    if field is None:
        return None
    group, unit, key = field
    if group == "neonate":
        days = _whole(payload, "age_neonate_days", 0, 27)
        hours = _whole(payload, "age_neonate_hours", 0, 23)
        if days == 0 and hours is not None:
            return f"PT{hours}H", ["age_neonate_hours"]
        if days is not None:
            return f"P{days}D", [key]
        return None
    value = _whole(payload, key, 1, 150 if group == "adult" else 999)
    if value is None:
        return None
    return f"P{value}{_DURATION_DESIGNATORS[unit]}", [key]


def _under_one_year(payload: dict) -> bool:
    if _whole(payload, "isNeonatal", 0, 1) == 1:
        return True
    months = _number(payload, "ageInMonthsByYear")
    return _whole(payload, "isChild", 0, 1) == 1 and months is not None and months < 12


def _fetal(payload: dict, put) -> None:
    neonate = _whole(payload, "isNeonatal", 0, 1) == 1
    stillborn = None
    if neonate:
        signs = [key for key in ("Id10104", "Id10109", "Id10110") if _yes(payload, key)]
        if signs:
            stillborn = 0
            put("FetalOrInfantDeath", "Stillborn", 0, signs)
        else:
            stillborn = _coded(payload, "Id10114")
            if stillborn is not None:
                put("FetalOrInfantDeath", "Stillborn", stillborn, ["Id10114"])
    if neonate and stillborn != 1:
        # Hours survived, not a flag (DORIS tabular spec). age_neonate_hours is
        # asked only when a date is missing; same-day dates ask
        # doris_hours_survived instead.
        for key in ("age_neonate_hours", "doris_hours_survived"):
            hours = _whole(payload, key, 0, 23)
            if hours is not None and (key != "age_neonate_hours" or _whole(payload, "age_neonate_days", 0, 0) == 0):
                put("FetalOrInfantDeath", "DeathWithin24h", hours, [key])
                break
    multiple = _coded(payload, "Id10354")
    if multiple is not None:
        put("FetalOrInfantDeath", "MultiplePregnancy", multiple, ["Id10354"])
    # Grammes. Below 100 is blank (0) or kilogrammes keyed as grammes (2, 3):
    # the forms now reject both, older answers are left for the coder.
    weight = _whole(payload, "Id10366", 100, 9999)
    if weight is not None:
        put("FetalOrInfantDeath", "BirthWeight", weight, ["Id10366"])
    weeks = _whole(payload, "doris_pregnancy_weeks", 8, 48)  # 88/99 refused/don't know
    if weeks is not None:
        put("FetalOrInfantDeath", "PregnancyWeeks", weeks, ["doris_pregnancy_weeks"])
    else:
        months = _number(payload, "Id10367")  # 88 refused, 99 don't know
        if months is not None and 0 < months <= 11:
            converted = math.floor(months * 4.345)
            if 1 <= converted <= 50:
                put(
                    "FetalOrInfantDeath", "PregnancyWeeks", converted, ["Id10367"],
                    note="converted from months",
                )
    mother = _whole(payload, "doris_mother_age", 10, 60)  # 88/99 refused/don't know
    if mother is not None:
        put("FetalOrInfantDeath", "AgeMother", mother, ["doris_mother_age"])


def _maternal(payload: dict, put) -> None:
    answers = {key: _choice(payload, key) for key in _MATERNAL_CHAIN}
    for key, band in _MATERNAL_BANDS:
        if answers[key] == "yes":
            put("MaternalDeath", "WasPregnant", 1, [key])
            put("MaternalDeath", "TimeFromPregnancy", band, [key])
            return
    # Died after a delivery with no timing "yes". Id10308 = no means the
    # birth was over a year before: no bearing (owner, 2026-09-29), so fall
    # through to Id10310. Band 3 is never derived.
    if answers["Id10313"] == "yes" and answers["Id10308"] != "no":
        put("MaternalDeath", "WasPregnant", 1, ["Id10313"])
        unknown = [key for key in ("Id10314", "Id10306", "Id10308") if answers[key] in _UNKNOWN]
        if unknown:
            put("MaternalDeath", "TimeFromPregnancy", 9, ["Id10313", *unknown])
        return
    if answers["Id10310"] == "yes":
        put("MaternalDeath", "WasPregnant", 0, ["Id10310"])
        return
    asked = [key for key, answer in answers.items() if answer]
    if asked and all(answers[key] in _UNKNOWN for key in asked):
        put("MaternalDeath", "WasPregnant", 9, asked)


def _manner(payload: dict, put) -> None:
    injury = _choice(payload, "Id10077")
    if injury == "no":
        put("MannerOfDeath", "MannerOfDeath", 0, ["Id10077"])
        return
    if injury in _UNKNOWN:
        put("MannerOfDeath", "MannerOfDeath", 9, ["Id10077"])
        return
    if injury != "yes":
        return

    legal_war = {"legal": 4, "war": 5}.get(_choice(payload, "doris_injury_legal_war"))
    if legal_war is not None:
        put("MannerOfDeath", "MannerOfDeath", legal_war, ["doris_injury_legal_war"])
    elif _yes(payload, "Id10095"):  # force of nature: intent questions are skipped
        put("MannerOfDeath", "MannerOfDeath", 1, ["Id10095"])
    else:
        intent = next(((key, code) for key, code in _INTENT if _yes(payload, key)), None)
        if intent is not None:
            put("MannerOfDeath", "MannerOfDeath", intent[1], [intent[0]])
        else:
            asked = [key for key, _code in _INTENT if _choice(payload, key)]
            unknown = any(_choice(payload, key) in _UNKNOWN for key in asked)
            put("MannerOfDeath", "MannerOfDeath", 9 if unknown else 6, asked or ["Id10077"])

    injured = _injury_date(payload)
    if injured is not None:
        put("MannerOfDeath", "DateOfExternalCauseOrPoisoning", injured[0], [injured[1]])
    place = _whole(payload, "doris_injury_place", 0, 9)
    if place is not None:
        put("MannerOfDeath", "PlaceOfOccuranceExternalCause", place, ["doris_injury_place"])
    kinds = [(key, label) for key, label in _INJURY_TYPES if _yes(payload, key)]
    description = "; ".join(label for _key, label in kinds)
    if kinds and len(description) <= MAX_TEXT_LENGTH:
        put("MannerOfDeath", "DescriptionExternalCause", description, [key for key, _label in kinds])


def _injury_date(payload: dict) -> tuple[str, str] | None:
    """``(DateOfExternalCauseOrPoisoning, source)``; "unknown" gives ``None``."""
    known = _choice(payload, "doris_injury_date_known")
    if known == "full":
        injured = _date(payload, "doris_injury_date")
        if injured is not None:
            return injured.isoformat(), "doris_injury_date"
    if known == "month_year":
        injured = _date(payload, "doris_injury_month_year")
        if injured is not None:
            return f"{injured.year:04d}-{injured.month:02d}", "doris_injury_month_year"
    return None


def _surgery_days(payload: dict) -> float | None:
    per_unit = _DAYS_PER_UNIT.get(_choice(payload, "doris_surgery_when_unit"))
    amount = _whole(payload, "doris_surgery_when", 0, 99999)
    if per_unit is None or amount is None or amount in _REFUSED_OR_UNKNOWN:
        return None
    return amount * per_unit


def _surgery(payload: dict, put) -> None:
    direct = _choice(payload, "doris_surgery_performed")
    if direct == "no":
        put("Surgery", "WasPerformed", 0, ["doris_surgery_performed"])
        return
    if direct in _UNKNOWN:
        put("Surgery", "WasPerformed", 9, ["doris_surgery_performed"])
        return
    if direct == "yes":
        days = _surgery_days(payload)
        if days is None:
            if _whole(payload, "doris_surgery_when", 88, 99) in _REFUSED_OR_UNKNOWN:
                put("Surgery", "WasPerformed", 9, ["doris_surgery_performed", "doris_surgery_when"])
            return
        if days > 28:  # DORIS asks about the last 4 weeks
            put("Surgery", "WasPerformed", 0, ["doris_surgery_performed", "doris_surgery_when"])
            return
        put("Surgery", "WasPerformed", 1, ["doris_surgery_performed", "doris_surgery_when"])
        kind = _text(payload, "doris_surgery_type")
        reason = _text(payload, "doris_surgery_reason")
        text = f"{kind} for {reason}" if kind and reason else kind or reason
        sources = [key for key, value in (("doris_surgery_type", kind), ("doris_surgery_reason", reason)) if value]
        if text and len(text) <= MAX_TEXT_LENGTH:
            put("Surgery", "Reason", text, sources)
        return
    # No direct answer (ODK cases). Id10340 is asked of every post-menopausal
    # woman, so it counts only with a pregnancy event.
    if _yes(payload, "Id10340") and any(_yes(payload, key) for key in _PREGNANCY_EVENTS):
        put("Surgery", "WasPerformed", 1, ["Id10340"])
        put("Surgery", "Reason", "Hysterectomy", ["Id10340"])
        return
    within_month = _coded(payload, "Id10426")
    if within_month is not None:
        put("Surgery", "WasPerformed", within_month, ["Id10426"])


def _autopsy(payload: dict, put) -> None:
    requested = _coded(payload, "doris_autopsy_requested")
    if requested is None:
        return
    put("Autopsy", "WasRequested", requested, ["doris_autopsy_requested"])
    if requested == 1:
        findings = _coded(payload, "doris_autopsy_findings")
        if findings is not None:
            put("Autopsy", "Findings", findings, ["doris_autopsy_findings"])


# --- public API ----------------------------------------------------------------


def doris_prefill_from_payload(payload: dict | None) -> tuple[dict, dict]:
    """Return ``(partial_certificate, provenance)`` for one interview payload.

    ``partial_certificate`` holds only the certificate sections the interview
    answers (no ``ICDVersion`` or Part I); wrapped with those it passes
    ``normalize_certificate``. ``provenance`` maps each prefilled field, as
    ``"Section.Field"``, to ``{"sources": [question ids]}`` plus an optional
    ``"note"``. Never raises on odd values: they are left out.
    """
    payload = payload if isinstance(payload, dict) else {}
    certificate: dict = {}
    provenance: dict = {}

    def put(section: str, field: str, value, sources: list[str], note: str | None = None) -> None:
        certificate.setdefault(section, {})[field] = value
        provenance[f"{section}.{field}"] = {"sources": list(sources), **({"note": note} if note else {})}

    sex = _SEX.get(_choice(payload, "Id10019"))
    if sex is not None:
        put("AdministrativeData", "Sex", sex, ["Id10019"])
    death = _death(payload)
    birth = _birth(payload, death[2] if death else None)
    if birth is not None:
        put("AdministrativeData", "DateBirth", birth[0], birth[1])
    if death is not None:
        put("AdministrativeData", "DateDeath", death[0], death[1])
    if birth is None or death is None:
        age = _estimated_age(payload)
        if age is not None:
            put("AdministrativeData", "EstimatedAge", age[0], age[1])

    if _under_one_year(payload):
        _fetal(payload, put)
    _maternal(payload, put)
    _manner(payload, put)
    _surgery(payload, put)
    _autopsy(payload, put)
    return certificate, provenance


def doris_prefill_record(payload: dict | None, certificate: dict | None) -> dict:
    """What the saved envelope records about the prefill, PII-free.

    Recomputed server-side from the same payload the certificate was coded
    against, never taken from the client: for each field the interview
    prefilled, its source question ids and whether the saved certificate
    differs from the prefilled value. No values are copied.
    """
    prefill, provenance = doris_prefill_from_payload(payload)
    saved = certificate if isinstance(certificate, dict) else {}
    fields = {}
    for path, entry in provenance.items():
        section, field = path.split(".", 1)
        saved_section = saved.get(section)
        saved_value = saved_section.get(field) if isinstance(saved_section, dict) else None
        fields[path] = {
            "sources": entry["sources"],
            "changed": saved_value != prefill[section][field],
        }
    return {"version": PREFILL_RECORD_VERSION, "fields": fields}
