"""Registration identifier rules: normalisation, value validation, type checks.

Policy: docs/policy/death-registration-identifiers.md ("Normalisation",
"Pattern safety", "Validation and error shape"). Pure functions; no database,
no logging. Validation always sees the plaintext, before encryption, and no
message ever echoes the submitted value.

Pattern safety has two guards. First a safe subset checked at save time
(Python's own regular expression parser): it bounds backtracking by
construction, with at most ``MAX_VARIABLE_PARTS`` variable-length parts in the
whole pattern and no two adjacent variable parts that can match the same
character. Second, ``google-re2`` (linear time, no backtracking) does the
matching, so a gap in the subset checker cannot become a ReDoS. A pattern must
compile under both Python ``re`` (ASCII) and re2 on save; the stored pattern is
matched with ``re2.fullmatch`` only. Differences between the engines on the
allowed subset are listed in the policy "Pattern safety" section.
"""

from __future__ import annotations

import re
import unicodedata
import warnings
from functools import lru_cache
from re import _constants as _c
from re import _parser

import re2

CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
MAX_VALUE_LENGTH = 64
MAX_PATTERN_LENGTH = 200
MAX_REPEAT_COUNT = 64
MAX_VARIABLE_PARTS = 3

CHAR_TYPE_REGEX = {
    "digits": re.compile(r"[0-9]+", re.ASCII),
    "letters": re.compile(r"[A-Z]+", re.ASCII),
    "letters_digits": re.compile(r"[A-Z0-9]+", re.ASCII),
    "letters_digits_hyphen_slash": re.compile(r"[A-Z0-9/-]+", re.ASCII),
}
CHAR_TYPE_TEXT = {
    "digits": "digits",
    "letters": "letters",
    "letters_digits": "letters and digits",
    "letters_digits_hyphen_slash": "letters, digits, hyphen and slash",
}
UNIQUENESS_SCOPES = ("none", "project")

# re2 logs every parse failure to stderr by default; a refused pattern is an
# expected outcome here, and the log would carry the pattern text.
_RE2_OPTIONS = re2.Options()
_RE2_OPTIONS.log_errors = False


class IdentifierRuleError(ValueError):
    """A refusal whose message is safe to show: it never contains a value."""


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def normalise(raw) -> str | None:
    """NFKC, trim, collapse whitespace, upper-case; empty is ``None`` (no
    value). ``None`` stays ``None``. Non-text raises ``IdentifierRuleError``."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise IdentifierRuleError("Identifier values must be text.")
    text = " ".join(unicodedata.normalize("NFKC", raw).split()).upper()
    return text or None


# ---------------------------------------------------------------------------
# Pattern safety
# ---------------------------------------------------------------------------

def _strip_anchors(pattern: str) -> str:
    if pattern.startswith("^"):
        pattern = pattern[1:]
    if pattern.endswith("$"):
        backslashes = len(pattern) - 1 - len(pattern[:-1].rstrip("\\"))
        if backslashes % 2 == 0:
            pattern = pattern[:-1]
    return pattern


def _scan_group_openers(pattern: str) -> None:
    """Refuse every ``(?`` construct except ``(?:``: inline flags, lookaround,
    named groups, conditionals, atomic groups and comments."""
    escaped = in_class = False
    for i, ch in enumerate(pattern):
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif in_class:
            in_class = ch != "]"
        elif ch == "[":
            in_class = True
        elif ch == "(" and pattern[i + 1:i + 2] == "?" and pattern[i + 2:i + 3] != ":":
            raise IdentifierRuleError(
                "The pattern may not use lookaround, named groups, conditionals, inline flags or atomic groups."
            )


def _contains(items, ops) -> bool:
    """Whether the parsed tree holds any op in *ops*, at any depth."""
    for op, av in items:
        if op in ops:
            return True
        if op is _c.SUBPATTERN and _contains(av[3], ops):
            return True
        if op is _c.BRANCH and any(_contains(branch, ops) for branch in av[1]):
            return True
        if op in (_c.MAX_REPEAT, _c.MIN_REPEAT, _c.POSSESSIVE_REPEAT) and _contains(av[2], ops):
            return True
    return False


def _check_tree(items) -> None:
    for op, av in items:
        if op in (_c.GROUPREF, _c.GROUPREF_EXISTS):
            raise IdentifierRuleError("The pattern may not use backreferences or conditionals.")
        if op in (_c.ASSERT, _c.ASSERT_NOT):
            raise IdentifierRuleError("The pattern may not use lookahead or lookbehind.")
        if op is _c.ATOMIC_GROUP:
            raise IdentifierRuleError("The pattern may not use atomic groups.")
        if op in (_c.MIN_REPEAT, _c.POSSESSIVE_REPEAT):
            raise IdentifierRuleError("The pattern may not use lazy or possessive quantifiers.")
        if op is _c.AT:
            raise IdentifierRuleError("The pattern may not use anchors or word boundaries inside it.")
        if op is _c.SUBPATTERN:
            _, add_flags, del_flags, body = av
            if add_flags or del_flags:
                raise IdentifierRuleError("The pattern may not use inline flags.")
            _check_tree(body)
        elif op is _c.BRANCH:
            for branch in av[1]:
                _check_tree(branch)
        elif op is _c.MAX_REPEAT:
            low, high, body = av
            if low > MAX_REPEAT_COUNT or (high != _c.MAXREPEAT and high > MAX_REPEAT_COUNT):
                raise IdentifierRuleError(f"A repeat count may not exceed {MAX_REPEAT_COUNT}.")
            if _contains(body, (_c.MAX_REPEAT, _c.MIN_REPEAT, _c.POSSESSIVE_REPEAT, _c.BRANCH)):
                raise IdentifierRuleError(
                    "A repeated group may not itself contain a repeat or an alternation."
                )
            _check_tree(body)


# Character sets, as (ASCII code points, may match beyond ASCII). Conservative:
# anything not understood is "every character".
_ASCII = frozenset(range(128))
_DIGITS = frozenset(map(ord, "0123456789"))
_WORD = frozenset(map(ord, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"))
_SPACE = frozenset(map(ord, " \t\n\r\f\v"))
_ANYTHING = (_ASCII, True)
_CATEGORY_CHARS = {
    _c.CATEGORY_DIGIT: (_DIGITS, False),
    _c.CATEGORY_NOT_DIGIT: (_ASCII - _DIGITS, True),
    _c.CATEGORY_WORD: (_WORD, False),
    _c.CATEGORY_NOT_WORD: (_ASCII - _WORD, True),
    _c.CATEGORY_SPACE: (_SPACE, False),
    _c.CATEGORY_NOT_SPACE: (_ASCII - _SPACE, True),
}


def _union(sets):
    ascii_part, wide = frozenset(), False
    for chars, beyond in sets:
        ascii_part |= chars
        wide = wide or beyond
    return ascii_part, wide


def _chars(items):
    """The characters the parsed *items* can match (a superset)."""
    found = []
    for op, av in items:
        if op is _c.LITERAL:
            found.append((frozenset([av]) if av < 128 else frozenset(), av >= 128))
        elif op is _c.NOT_LITERAL:
            found.append((_ASCII - {av}, True))
        elif op is _c.ANY:
            found.append(_ANYTHING)
        elif op is _c.IN:
            members, negate = [], False
            for member_op, member in av:
                if member_op is _c.NEGATE:
                    negate = True
                elif member_op is _c.LITERAL:
                    members.append(_chars([(member_op, member)]))
                elif member_op is _c.RANGE:
                    low, high = member
                    members.append((frozenset(range(low, min(high, 127) + 1)), high >= 128))
                else:
                    members.append(_CATEGORY_CHARS.get(member, _ANYTHING))
            chars, wide = _union(members)
            found.append((_ASCII - chars, True) if negate else (chars, wide))
        elif op is _c.SUBPATTERN:
            found.append(_chars(av[3]))
        elif op is _c.BRANCH:
            found.extend(_chars(branch) for branch in av[1])
        elif op is _c.MAX_REPEAT:
            found.append(_chars(av[2]))
        else:
            found.append(_ANYTHING)
    return _union(found)


def _overlap(a, b) -> bool:
    return bool(a[0] & b[0]) or (a[1] and b[1])


def _flatten(items):
    """The items with plain groups opened, so adjacency crosses group edges."""
    for op, av in items:
        if op is _c.SUBPATTERN:
            yield from _flatten(av[3])
        else:
            yield op, av


def _check_variable_parts(items, count: list) -> None:
    """Bound backtracking: at most ``MAX_VARIABLE_PARTS`` variable-length parts
    (``* + ?``, ``{m,n}`` with m != n, alternation) in the whole pattern, and no
    variable part that can match a character an earlier variable part in the
    same sequence can, with only optional parts between them. A literal or
    fixed part between two (the ``-`` in ``[A-Z]+-[A-Z]+``) breaks the run."""
    run = []
    for op, av in _flatten(items):
        variable = op is _c.BRANCH or (op is _c.MAX_REPEAT and av[0] != av[1])
        if not variable:
            if not (op is _c.MAX_REPEAT and av[0] == 0):
                run = []
            continue
        count[0] += 1
        if count[0] > MAX_VARIABLE_PARTS:
            raise IdentifierRuleError(
                f"The pattern may have at most {MAX_VARIABLE_PARTS} variable-length parts "
                "(* + ? {m,n} or alternation)."
            )
        chars = _chars([(op, av)])
        if any(_overlap(chars, earlier) for earlier in run):
            raise IdentifierRuleError(
                "Two neighbouring variable-length parts of the pattern can match the same "
                "characters; put a fixed character between them."
            )
        if op is _c.BRANCH:
            for branch in av[1]:
                _check_variable_parts(branch, count)
        run = [*run, chars] if op is _c.BRANCH or av[0] == 0 else [chars]


def check_pattern(pattern: str) -> str:
    """The safe-subset check run when a type is saved. Returns the pattern to
    store (a leading ``^`` and a trailing ``$`` removed); raises
    ``IdentifierRuleError`` naming the reason, never storing a bad pattern."""
    if not isinstance(pattern, str):
        raise IdentifierRuleError("The pattern must be text.")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise IdentifierRuleError(f"The pattern may be at most {MAX_PATTERN_LENGTH} characters.")
    stripped = _strip_anchors(pattern)
    if not stripped:
        raise IdentifierRuleError("The pattern is empty.")
    _scan_group_openers(stripped)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            parsed = _parser.parse(stripped, re.ASCII)
            re.compile(stripped, re.ASCII)
    except (re.error, RecursionError, OverflowError, Warning):
        raise IdentifierRuleError("The pattern is not a valid regular expression.") from None
    if parsed.state.groupdict:
        raise IdentifierRuleError("The pattern may not use named groups.")
    _check_tree(parsed)
    _check_variable_parts(parsed, [0])
    # Python reads "{,n}" as a repeat and re2 as literal text; refuse the
    # ambiguity rather than let the engines disagree.
    if re.search(r"(?<!\\)(?:\\\\)*\{,", stripped):
        raise IdentifierRuleError("Write a repeat as {n} or {m,n}; {,n} is not allowed.")
    try:
        re2.compile(stripped, _RE2_OPTIONS)
    except re2.error:
        raise IdentifierRuleError("The pattern is not supported by the matching engine.") from None
    return stripped


@lru_cache(maxsize=256)
def _compiled(pattern: str):
    return re2.compile(pattern, _RE2_OPTIONS)


# ---------------------------------------------------------------------------
# Value validation
# ---------------------------------------------------------------------------

def _hint(identifier_type) -> str:
    return f" (for example {identifier_type.example})" if identifier_type.example else ""


def validate_value(identifier_type, normalised: str) -> None:
    """Check a normalised value against an active type, in the policy order:
    type active, length, character type, then pattern. Raises
    ``IdentifierRuleError``; the message names the type label and the example,
    never the value."""
    label = identifier_type.label
    if not identifier_type.is_active:
        raise IdentifierRuleError(f"{label} is not in use for this project.")
    low, high = identifier_type.min_length, identifier_type.max_length
    if not low <= len(normalised) <= high:
        size = f"exactly {low}" if low == high else f"between {low} and {high}"
        raise IdentifierRuleError(f"{label} must be {size} characters{_hint(identifier_type)}.")
    char_type = identifier_type.char_type
    if char_type and not CHAR_TYPE_REGEX[char_type].fullmatch(normalised):
        raise IdentifierRuleError(
            f"{label} may contain only {CHAR_TYPE_TEXT[char_type]}{_hint(identifier_type)}."
        )
    if identifier_type.pattern:
        try:
            matched = _compiled(identifier_type.pattern).fullmatch(normalised)
        except re2.error:
            raise IdentifierRuleError(f"{label} cannot be checked: its pattern is not supported.") from None
    else:
        matched = True
    if not matched:
        if identifier_type.example:
            raise IdentifierRuleError(f"{label} must look like {identifier_type.example}.")
        raise IdentifierRuleError(f"{label} does not match the required format.")


# ---------------------------------------------------------------------------
# Type save checks
# ---------------------------------------------------------------------------

def _int_in(fields: dict, name: str, default: int, low: int, high: int) -> int:
    value = fields.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise IdentifierRuleError(f"{name} must be a whole number from {low} to {high}.")
    return value


def _bool(fields: dict, name: str, default: bool) -> bool:
    value = fields.get(name, default)
    if not isinstance(value, bool):
        raise IdentifierRuleError(f"{name} must be true or false.")
    return value


def _text(fields: dict, name: str, limit: int, *, required: bool) -> str | None:
    value = fields.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise IdentifierRuleError(f"{name} is required.")
        return None
    if not isinstance(value, str):
        raise IdentifierRuleError(f"{name} must be text.")
    value = value.strip()
    if len(value) > limit:
        raise IdentifierRuleError(f"{name} may be at most {limit} characters.")
    return value


class _Probe:
    """A type-shaped record, so the example is checked by ``validate_value``."""

    def __init__(self, cleaned: dict):
        self.__dict__.update(cleaned)


def clean_type_fields(fields: dict, current: dict | None = None) -> dict:
    """The validated, normalised columns of an identifier type.

    *fields* is the request body; *current* the stored columns on an update
    (an update body is merged over it, so every rule is checked on the whole
    resulting type). Raises ``IdentifierRuleError``. ``code`` is checked here
    for shape only; immutability once values exist is the service's check.
    """
    merged = {**(current or {}), **fields}
    cleaned: dict = {}
    code = merged.get("code")
    if not isinstance(code, str) or not CODE_RE.fullmatch(code):
        raise IdentifierRuleError("code must be lower-case letters, digits and underscores, starting with a letter (2 to 32 characters).")
    cleaned["code"] = code
    cleaned["label"] = _text(merged, "label", 128, required=True)
    cleaned["min_length"] = _int_in(merged, "min_length", 1, 1, MAX_VALUE_LENGTH)
    cleaned["max_length"] = _int_in(merged, "max_length", MAX_VALUE_LENGTH, 1, MAX_VALUE_LENGTH)
    if cleaned["min_length"] > cleaned["max_length"]:
        raise IdentifierRuleError("min_length may not exceed max_length.")
    char_type = merged.get("char_type")
    if char_type is not None and (not isinstance(char_type, str) or char_type not in CHAR_TYPE_REGEX):
        raise IdentifierRuleError(f"char_type must be one of {', '.join(CHAR_TYPE_REGEX)}.")
    cleaned["char_type"] = char_type
    pattern = _text(merged, "pattern", MAX_PATTERN_LENGTH, required=False)
    cleaned["pattern"] = check_pattern(pattern) if pattern else None
    scope = merged.get("uniqueness_scope", "project")
    if scope not in UNIQUENESS_SCOPES:
        raise IdentifierRuleError("uniqueness_scope must be none or project.")
    cleaned["uniqueness_scope"] = scope
    cleaned["required_at_report"] = _bool(merged, "required_at_report", False)
    cleaned["sort_order"] = _int_in(merged, "sort_order", 0, 0, 10_000)
    cleaned["is_active"] = _bool(merged, "is_active", True)
    example = _text(merged, "example", MAX_VALUE_LENGTH, required=False)
    cleaned["example"] = normalise(example)
    if cleaned["example"]:
        probe = _Probe({**cleaned, "label": "The example", "example": None, "is_active": True})
        try:
            validate_value(probe, cleaned["example"])
        except IdentifierRuleError as exc:
            raise IdentifierRuleError(f"{exc} It must satisfy every rule set on the type.") from None
    return cleaned
