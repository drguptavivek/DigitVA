"""Pseudonymise one questionnaire payload for the Training & demo project.

Pure functions, no database. Names, addresses and phone-like identifiers are
replaced by random synthetic values, consistently within the payload: the same
original value becomes the same fake value in every field and inside free text
(the narrative Id10476 and any other string answer), matched case-insensitively
as a whole word. Free text is also scrubbed of place-name tokens taken from the
address fields and of Indian phone numbers. Devanagari (and other Indic) marks
count as part of a word. Every other answer, date and age is kept.

Policy: docs/policy/training-demo-project.md, "Pseudonymisation". Nothing here
logs or returns a value: callers get counts only.
"""

from __future__ import annotations

import copy
import random
import re
from collections import Counter

from app.services.pii_field_registry import PII_FIELDS

FIRST_NAMES = (
    "Aarav", "Aditya", "Akash", "Amit", "Anil", "Arjun", "Deepak", "Dinesh", "Ganesh", "Gopal",
    "Harish", "Imran", "Jagdish", "Kiran", "Lokesh", "Mahesh", "Manoj", "Naveen", "Prakash",
    "Rajesh", "Ramesh", "Rohit", "Sanjay", "Suresh", "Vijay", "Anita", "Asha", "Deepa", "Geeta",
    "Kavita", "Lakshmi", "Meena", "Nisha", "Pooja", "Priya", "Radha", "Rekha", "Savita", "Seema",
    "Sunita", "Usha", "Zainab",
)
LAST_NAMES = (
    "Agarwal", "Bhat", "Chauhan", "Das", "Gupta", "Iyer", "Joshi", "Kapoor", "Khan", "Kumar",
    "Mehta", "Mishra", "Nair", "Pandey", "Patel", "Pillai", "Rao", "Reddy", "Saxena", "Shah",
    "Sharma", "Singh", "Thakur", "Tiwari", "Verma", "Yadav",
)

DEV_FIRST_NAMES = (
    "राजेश", "सुरेश", "रमेश", "महेश", "अनिल", "सुनील", "विजय", "संजय", "मनोज", "दीपक",
    "सीमा", "सुनीता", "गीता", "कविता", "रेखा", "मीना", "पूजा", "प्रिया", "आशा", "उषा",
)
DEV_LAST_NAMES = (
    "शर्मा", "वर्मा", "गुप्ता", "यादव", "पटेल", "सिंह", "कुमार", "मिश्रा", "तिवारी", "पांडेय", "जोशी", "चौहान",
)
DEV_INITIALS = "अकगमरसहब"
PLACE_NAMES = (
    "Rampur", "Sitapur", "Ganeshpur", "Lalganj", "Devgaon", "Nayagaon", "Shivpur", "Chandpur",
    "Kishanpur", "Madhopur", "Bhawanipur", "Keshavgarh",
)
DEV_PLACE_NAMES = ("रामपुर", "सीतापुर", "गणेशपुर", "लालगंज", "देवगांव", "नयागांव", "शिवपुर", "चंदपुर")

# Processed in this order so a given name and a surname claim their pools
# before the free-form full names that repeat them.
NAME_FIELDS = ("Id10017", "Id10018", "Id10007", "Id10061", "Id10062", "Id10010")
ADDRESS_FIELDS = ("Id10055", "Id10057", "visit_address", "visit_remarks")
IDENTIFIER_FIELDS = (
    "Id10010a", "Id10010b", "Id10010c", "Id10070", "Id10071", "Id10072", "Id10073",
    "abha_number", "abha_address",
)
# A test asserts this equals PII_FIELDS, so a field added to the registry
# cannot silently skip pseudonymisation.
HANDLED_FIELDS = frozenset(NAME_FIELDS + ADDRESS_FIELDS + IDENTIFIER_FIELDS)
# Honorifics are not part of a name and stay as written.
TITLES = frozenset({
    "dr", "mr", "mrs", "ms", "miss", "shri", "smt", "sri", "late", "kumari",
    "श्री", "श्रीमती", "स्व", "स्वर्गीय", "डॉ", "कुमारी",
})
# Generic address words that are not place names and stay as written. A
# judgement call kept deliberately small: "nagar" and "colony" are in, a
# place name is anything else of four letters or more taken from an address
# field. Ordinary English words are listed so a remark such as "family lives
# at ..." does not turn them into fake places everywhere.
ADDRESS_STOP = frozenset((
    "house home ward block road village district near nearby gali nagar colony street lane main cross "
    "post tehsil tahsil taluk city town mandal opposite behind beside side next front back stand market "
    "temple school hospital chowk bazar bazaar sector gram panchayat thana police station tola mohalla "
    "family lives living live with from this that have which where there their address area residence "
    "resident house flat floor plot number "
    "ग्राम गांव गाँव मोहल्ला वार्ड जिला तहसील पास रोड गली नगर कॉलोनी मकान पंचायत थाना बाजार मंदिर स्कूल अस्पताल"
).split())

# Keys the service overwrites itself; never rewritten as free text.
PROTECTED_KEYS = frozenset({
    "sid", "form_def", "instanceID", "KEY", "unique_id", "unique_id2", "instanceName",
    "SubmissionDate", "updatedAt", "SubmitterName", "SubmitterID", "DeviceID", "FormVersion",
})
_MEDIA_SUFFIXES = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".amr", ".mp3", ".m4a", ".wav", ".mp4", ".csv",
)
# Python's \w misses Devanagari vowel signs and other Indic combining marks,
# which would cut a Hindi word in pieces. These ranges (combining diacritics,
# Devanagari to Sinhala without the danda and the digits, ZWJ/ZWNJ) count as
# word characters.
_MARKS = "\u0300-\u036f\u0900-\u0963\u0970-\u0dff\u200c\u200d"
_LETTER = rf"(?:[^\W\d_]|[{_MARKS}])"
_WCHAR = rf"[\w{_MARKS}]"
_WORD = re.compile(rf"{_LETTER}+(?:['’-]{_LETTER}+)*")
_PLAIN_WORD = re.compile(rf"{_LETTER}+")
_DEVANAGARI = re.compile(r"[\u0900-\u097f]")
# Indian phone number: optional +91 / 91 / 0 prefix, 10 digits starting 6-9
# (ASCII or Devanagari), single spaces or hyphens allowed between digits.
_PHONE = r"(?:(?:\+\s?91|91|0)[\s-]*)?[6-9६-९](?:[\s-]?\d){9}"
_PHONE_RE = re.compile(rf"(?<!{_WCHAR}){_PHONE}(?!{_WCHAR})")
_MIN_PLACE_TOKEN = 4
_MIN_TEXT_TOKEN = 3
_MIN_TEXT_PHRASE = 5


def _is_media_name(value: str) -> bool:
    return value.strip().lower().endswith(_MEDIA_SUFFIXES)


def _scramble(rng: random.Random, value: str) -> str:
    """Same shape: digits stay digits, letters keep their case, the rest stays."""
    out = []
    for ch in value:
        if ch.isascii() and ch.isdigit():
            out.append(str(rng.randrange(10)))
        elif ch.isascii() and ch.isalpha():
            letter = rng.choice("abcdefghijklmnopqrstuvwxyz")
            out.append(letter.upper() if ch.isupper() else letter)
        else:
            out.append(ch)
    return "".join(out)


class _Case:
    """The replacement tables of one payload."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.tokens: dict[str, str] = {}   # lower name word -> fake word
        self.places: dict[str, str] = {}   # lower address word -> fake place
        self.phrases: dict[str, str] = {}  # lower address / identifier -> fake
        self.phones: dict[str, str] = {}   # last 10 digits -> fake number
        self.avoid: set[str] = set()       # original name words: never used as a fake
        self.counts: Counter = Counter()

    # -- names ---------------------------------------------------------
    def _fake_word(self, key: str, pool: tuple[str, ...]) -> str:
        if key not in self.tokens:
            options = [n for n in pool if n.lower() != key and n.lower() not in self.avoid]
            self.tokens[key] = self.rng.choice(options)
        return self.tokens[key]

    def name(self, value: str, field: str) -> str:
        words = list(_WORD.finditer(value))
        last = len(words) - 1
        pieces, cursor = [], 0
        for index, match in enumerate(words):
            pieces.append(value[cursor:match.start()])
            word = match.group(0)
            key = word.lower()
            dev = bool(_DEVANAGARI.search(word))
            if key in TITLES:
                fake = word
            elif len(key) == 1:  # an initial
                fake = self.rng.choice(DEV_INITIALS if dev else "ABCDEFGHJKLMNPRSTV")
            else:
                surname = field == "Id10018" or (index == last and last > 0)
                if dev:
                    pool = DEV_LAST_NAMES if surname else DEV_FIRST_NAMES
                else:
                    pool = LAST_NAMES if surname else FIRST_NAMES
                fake = self._fake_word(key, pool)
            pieces.append(fake)
            cursor = match.end()
        pieces.append(value[cursor:])
        return "".join(pieces)

    def register_places(self, value: str) -> None:
        """Every place-name word of a real address gets one fake place, for free text."""
        for match in _PLAIN_WORD.finditer(value):
            key = match.group(0).lower()
            if len(key) < _MIN_PLACE_TOKEN or key in ADDRESS_STOP or key in self.tokens or key in self.places:
                continue
            pool = DEV_PLACE_NAMES if _DEVANAGARI.search(key) else PLACE_NAMES
            self.places[key] = self.rng.choice([p for p in pool if p.lower() != key])

    def phone(self, digits: str) -> str:
        if digits not in self.phones:
            self.phones[digits] = self.rng.choice("6789") + "".join(
                str(self.rng.randrange(10)) for _ in range(9)
            )
        return self.phones[digits]

    # -- addresses and identifiers -------------------------------------
    def phrase(self, value: str, make) -> str:
        key = value.strip().lower()
        if key not in self.phrases:
            self.phrases[key] = make()
        return self.phrases[key]

    def address(self, value: str) -> str:
        return self.phrase(value, lambda: (
            f"House {self.rng.randint(1, 150)}, Ward {self.rng.randint(1, 20)}, "
            f"Synthetic Village {self.rng.randint(1, 50)}"
        ))

    def identifier(self, field: str, value):
        rng = self.rng
        if isinstance(value, dict):  # Id10073 as stored: {"last3": "123", "present": true}
            fake = dict(value)
            if isinstance(fake.get("last3"), str) and fake["last3"]:
                fake["last3"] = _scramble(rng, fake["last3"])
            return fake
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, (int, float)):
            if field == "Id10010a":
                return rng.randint(25, 55)
            digits = len(str(abs(int(value))))
            return rng.randrange(10 ** (digits - 1), 10 ** digits) if digits > 1 else rng.randrange(10)
        text = str(value)
        if not text.strip():
            return value
        if field == "Id10010a":
            return str(rng.randint(25, 55))
        if field == "Id10010b":
            if text.strip().lower() in ("male", "female"):
                return rng.choice(("male", "female"))
            return value
        if field == "Id10071" and re.match(r"\d{4}-\d{2}-\d{2}", text):
            return f"{rng.randint(2012, 2024)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}" + text[10:]
        if field == "Id10072":
            return self.phrase(text, lambda: f"Synthetic Registration Office {rng.randint(1, 50)}")
        if field == "abha_address":
            domain = text.rsplit("@", 1)[1] if "@" in text else None
            local = f"user{rng.randint(100000, 999999)}"
            return f"{local}@{domain}" if domain else local
        return self.phrase(text, lambda: _scramble(rng, text.strip()))


def _free_text_pattern(replacements: dict[str, str]):
    """One pass over a string: known names/places/phrases first, then phone numbers."""
    alts = []
    if replacements:
        keys = sorted(replacements, key=len, reverse=True)
        alts.append("(?P<k>" + "|".join(re.escape(key) for key in keys) + ")")
    alts.append(f"(?P<p>{_PHONE})")
    return re.compile(rf"(?<!{_WCHAR})(?:{'|'.join(alts)})(?!{_WCHAR})", re.IGNORECASE)


def _digits(text: str) -> str:
    """The last ten digits of a phone-like run, Devanagari digits included."""
    return "".join(str(int(ch)) for ch in text if ch.isdigit())[-10:]


def _rewrite(value, pattern, replacements, case):
    if isinstance(value, str):
        if _is_media_name(value):
            return value

        def swap(match):
            if match.lastgroup == "p":
                case.counts["phone_replacements"] += 1
                return case.phone(_digits(match.group(0)))
            fake = replacements.get(match.group(0).lower())
            if fake is None:
                return match.group(0)
            case.counts["text_replacements"] += 1
            return fake.upper() if len(fake) > 1 and match.group(0).isupper() else fake

        return pattern.sub(swap, value)
    if isinstance(value, list):
        return [_rewrite(item, pattern, replacements, case) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite(item, pattern, replacements, case) for key, item in value.items()}
    return value


COUNT_KEYS = ("names", "addresses", "identifiers", "text_replacements", "phone_replacements")


def pseudonymise_payload(payload: dict, seed: str) -> tuple[dict, dict[str, int]]:
    """A pseudonymised copy of *payload* and the replacement counts.

    *seed* makes the fakes repeatable (the service passes the session code and
    case number). The input is not changed. The counts are ``COUNT_KEYS``:
    ``names`` / ``addresses`` / ``identifiers`` (fields rewritten) and
    ``text_replacements`` / ``phone_replacements`` (occurrences rewritten
    inside other answers).
    """
    case = _Case(random.Random(seed))
    out = copy.deepcopy(payload)

    for field in NAME_FIELDS:
        value = out.get(field)
        if isinstance(value, str) and value.strip():
            case.avoid.update(m.group(0).lower() for m in _WORD.finditer(value))
    for field in NAME_FIELDS:
        value = out.get(field)
        if isinstance(value, str) and value.strip():
            out[field] = case.name(value, field)
            case.counts["names"] += 1
    for field in ADDRESS_FIELDS:
        value = out.get(field)
        if isinstance(value, str) and value.strip():
            case.register_places(value)
            out[field] = case.address(value)
            case.counts["addresses"] += 1
    for field in IDENTIFIER_FIELDS:
        if field in out and out[field] not in (None, "", {}):
            out[field] = case.identifier(field, out[field])
            case.counts["identifiers"] += 1

    replacements = {key: fake for key, fake in case.tokens.items() if len(key) >= _MIN_TEXT_TOKEN}
    replacements.update(case.places)
    replacements.update({
        key: fake for key, fake in case.phrases.items() if len(key) >= _MIN_TEXT_PHRASE
    })
    pattern = _free_text_pattern(replacements)
    skip = HANDLED_FIELDS | PROTECTED_KEYS | frozenset(PII_FIELDS)
    for key, value in list(out.items()):
        if key not in skip:
            out[key] = _rewrite(value, pattern, replacements, case)
    return out, {name: case.counts[name] for name in COUNT_KEYS}


# -- read-only check ---------------------------------------------------------

def _strings(value):
    if isinstance(value, str):
        if not _is_media_name(value):
            yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _found(needles: set[str], text: str) -> bool:
    if not needles:
        return False
    keys = sorted(needles, key=len, reverse=True)
    pattern = rf"(?<!{_WCHAR})(?:{'|'.join(re.escape(k) for k in keys)})(?!{_WCHAR})"
    return re.search(pattern, text, re.IGNORECASE) is not None


def residual_categories(source: dict, output: dict) -> set[str]:
    """Which kinds of original personal data still occur in *output*.

    Returns a subset of ``names`` (a name word of 3+ letters from a name
    field), ``addresses`` (a whole address, or a place word of 4+ letters not
    in ``ADDRESS_STOP``), ``identifiers`` (a whole identifier value of 5+
    characters) and ``phones`` (an original phone-like run, from any answer).
    Pure; returns categories only, never values.
    """
    text = "\n".join(_strings(output))
    names, addresses, identifiers, phones = set(), set(), set(), set()
    for field in NAME_FIELDS:
        value = source.get(field)
        if isinstance(value, str):
            names.update(
                m.group(0).lower() for m in _WORD.finditer(value)
                if len(m.group(0)) >= _MIN_TEXT_TOKEN and m.group(0).lower() not in TITLES
            )
    for field in ADDRESS_FIELDS:
        value = source.get(field)
        if isinstance(value, str) and value.strip():
            if len(value.strip()) >= _MIN_TEXT_PHRASE:
                addresses.add(value.strip().lower())
            addresses.update(
                m.group(0).lower() for m in _PLAIN_WORD.finditer(value)
                if len(m.group(0)) >= _MIN_PLACE_TOKEN and m.group(0).lower() not in ADDRESS_STOP
            )
    for field in ("Id10010c", "Id10070", "Id10072", "abha_number", "abha_address"):
        value = source.get(field)
        if isinstance(value, str) and len(value.strip()) >= _MIN_TEXT_PHRASE:
            identifiers.add(value.strip().lower())
    for original in _strings(source):
        phones.update(_digits(m.group(0)) for m in _PHONE_RE.finditer(original))
    found = set()
    if _found(names, text):
        found.add("names")
    if _found(addresses, text):
        found.add("addresses")
    if _found(identifiers, text):
        found.add("identifiers")
    if phones and any(_digits(m.group(0)) in phones for m in _PHONE_RE.finditer(text)):
        found.add("phones")
    return found
