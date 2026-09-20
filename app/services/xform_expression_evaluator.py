"""Python port of the XLSForm expression subset the WHO VA 2022 instrument
uses, ported line-for-line from
``vendor/who-va-2022/src/engine/expression.ts`` (tokenize / parseExpression /
evaluateExpression and the coercion helpers ``isEmpty``, ``asBoolean``,
``asNumber``, ``equal``, ``dateNumber``).

Why this exists: no Python code could previously evaluate an XLSForm
``relevant``/``constraint``/``calculation`` expression, so
``app/services/web_intake_service.py`` accepted the browser's own computed
``valid`` boolean as-is. That JS engine is still the single source of truth
for the client; this module is a second, independent implementation that a
server-side re-derivation of submission validity (beads digitva-cal.2) can
call, and it does not itself change any intake behaviour.

Two evaluators drifting apart is the real risk here — see beads digitva-cal.1
and docs/policy/xform-expression-evaluator.md. What keeps this port honest is
``tests/services/test_xform_expression_evaluator.py`` reading
``vendor/who-va-2022/src/generated/expression-conformance-corpus.json``,
golden results the real TypeScript engine produced
(``tooling/who-va-2022/build-expression-corpus.mjs``), and requiring this
module to reproduce every one. Do not "improve" a coercion rule here without
regenerating that corpus and re-checking it fails first — a Python-idiomatic
rewrite (e.g. reaching for truthiness instead of ``as_boolean``) is exactly
the kind of change that would diverge silently.

Known divergences from naive Python, and why the code below avoids them:

* Python's ``re`` matches Unicode digits with ``\\d`` by default;
  JavaScript's ``RegExp`` does not. ``regex()`` compiles with ``re.ASCII`` so
  a Devanagari digit does not pass a pattern like
  ``^(?!0{1,3}$)\\d{1,3}$`` that a JS-side ``\\d`` would reject.
* XPath 1.0 string literals have no backslash-escape mechanism at all — a
  backslash is an ordinary character, and the only escape is the doubled
  quote (``''``/``""``). ``_tokenize`` mirrors ``expression.ts``'s tokenizer
  exactly (see commit 78757d4, which fixed a bug where the tokenizer
  silently ate a literal ``\\d``).
* ``today()`` and date arithmetic are timezone-sensitive.
  ``evaluate_expression``'s ``now`` argument must be a timezone-aware
  ``datetime``; ``today()`` reads its date components directly off it (the
  caller decides what "local" means, the same way the browser's
  ``formatLocalDate`` reads a JS ``Date``'s *local* getters). There is no
  implicit "the server's local time" default.
* Coercion: ``is_empty``/``as_boolean``/``as_number``/``equal``/
  ``date_number`` are ported literally rather than reached for with Python
  truthiness, which would diverge on ``0``, ``""``, ``"0"`` and ``None``.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

AnswerValue = Any  # str | float | bool | list[str] | None, mirroring SubmissionData
SubmissionData = dict[str, AnswerValue]

_EPOCH = date(1970, 1, 1)

_BINARY_PRECEDENCE: dict[str, int] = {
    "or": 1,
    "and": 2,
    "=": 3,
    "!=": 3,
    ">": 3,
    ">=": 3,
    "<": 3,
    "<=": 3,
    "+": 4,
    "-": 4,
    "*": 5,
    "div": 5,
    "mod": 5,
}

_SUPPORTED_FUNCTIONS = {
    "selected",
    "regex",
    "count-selected",
    "string-length",
    "int",
    "if",
    "today",
    "date",
}

_ASCII_DIGIT_RE = re.compile(r"[0-9]")
_NUMBER_RE = re.compile(r"^\d*\.?\d+(?:[eE][+-]?\d+)?", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*")
_WHITESPACE_RE = re.compile(r"\s")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T.*)?$", re.ASCII)
_ISO_DATE_ONLY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$", re.ASCII)
_JS_NUMBER_LITERAL_RE = re.compile(
    r"^[+-]?(Infinity|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)$"
)


class ExpressionError(ValueError):
    """A source string is not a valid expression in the supported subset."""


@dataclass(frozen=True)
class Token:
    type: str
    value: str


def _tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    index = 0
    length = len(source)
    while index < length:
        character = source[index]
        if _WHITESPACE_RE.match(character):
            index += 1
            continue
        if source.startswith("${", index):
            end = source.find("}", index + 2)
            if end < 0:
                raise ExpressionError(f"Unclosed reference at character {index}")
            tokens.append(Token("reference", source[index + 2 : end]))
            index = end + 1
            continue
        if character in ("'", '"'):
            quote = character
            value_chars: list[str] = []
            index += 1
            while index < length:
                next_char = source[index]
                if next_char == quote:
                    if index + 1 < length and source[index + 1] == quote:
                        value_chars.append(quote)
                        index += 2
                        continue
                    index += 1
                    break
                # XPath 1.0 string literals have no backslash escape at all
                # -- a backslash is an ordinary literal character. Do not
                # special-case `\'`/`\"` here: that reading of the backslash
                # would consume the closing quote of a literal ending in a
                # backslash, running it into the rest of the expression (the
                # bug fixed in commit 78757d4). This matters because the
                # main source of backslashes in these expressions is
                # `regex()` patterns such as `\d`, which must survive intact.
                value_chars.append(next_char)
                index += 1
            tokens.append(Token("string", "".join(value_chars)))
            continue
        # ASCII-only digit test: `character.isdigit()` would also accept a
        # Unicode digit (e.g. Devanagari), but JavaScript's `/\d/.test()`
        # here does not -- see the module docstring's regex() divergence
        # note, which is the same underlying JS/Python `\d` gap.
        if _ASCII_DIGIT_RE.match(character) or (
            character == "." and index + 1 < length and _ASCII_DIGIT_RE.match(source[index + 1])
        ):
            match = _NUMBER_RE.match(source[index:])
            if not match:
                raise ExpressionError(f"Invalid number at character {index}")
            tokens.append(Token("number", match.group(0)))
            index += len(match.group(0))
            continue
        double_operator = source[index : index + 2]
        if double_operator in ("!=", ">=", "<="):
            tokens.append(Token("operator", double_operator))
            index += 2
            continue
        if character in ("=", ">", "<", "+", "-", "*"):
            tokens.append(Token("operator", character))
            index += 1
            continue
        if character == ".":
            tokens.append(Token("dot", character))
            index += 1
            continue
        if character == "(":
            tokens.append(Token("left", character))
            index += 1
            continue
        if character == ")":
            tokens.append(Token("right", character))
            index += 1
            continue
        if character == ",":
            tokens.append(Token("comma", character))
            index += 1
            continue
        identifier_match = _IDENTIFIER_RE.match(source[index:])
        if identifier_match:
            value = identifier_match.group(0)
            token_type = "operator" if value in _BINARY_PRECEDENCE else "identifier"
            tokens.append(Token(token_type, value))
            index += len(value)
            continue
        raise ExpressionError(f"Unsupported character '{character}' at character {index}")
    tokens.append(Token("eof", ""))
    return tokens


@dataclass
class _Parser:
    tokens: list[Token]
    index: int = 0

    def parse(self) -> dict[str, Any]:
        result = self._parse_binary(1)
        if self._peek().type != "eof":
            raise ExpressionError(f"Unexpected token '{self._peek().value}'")
        return result

    def _peek(self) -> Token:
        return self.tokens[self.index] if self.index < len(self.tokens) else Token("eof", "")

    def _consume(self, token_type: str | None = None, value: str | None = None) -> Token:
        token = self._peek()
        if token_type and token.type != token_type:
            raise ExpressionError(f"Expected {token_type}, found '{token.value}'")
        if value and token.value != value:
            raise ExpressionError(f"Expected '{value}', found '{token.value}'")
        self.index += 1
        return token

    def _parse_binary(self, minimum_precedence: int) -> dict[str, Any]:
        left = self._parse_unary()
        while True:
            token = self._peek()
            precedence = _BINARY_PRECEDENCE.get(token.value) if token.type == "operator" else None
            if precedence is None or precedence < minimum_precedence:
                break
            self._consume("operator")
            right = self._parse_binary(precedence + 1)
            left = {"type": "binary", "operator": token.value, "left": left, "right": right}
        return left

    def _parse_unary(self) -> dict[str, Any]:
        if self._peek().type == "operator" and self._peek().value == "-":
            self._consume("operator", "-")
            return {"type": "unary", "operator": "negative", "operand": self._parse_unary()}
        return self._parse_primary()

    def _parse_primary(self) -> dict[str, Any]:
        token = self._peek()
        if token.type == "number":
            self._consume()
            return {"type": "literal", "value": float(token.value)}
        if token.type == "string":
            self._consume()
            return {"type": "literal", "value": token.value}
        if token.type == "reference":
            self._consume()
            return {"type": "reference", "name": token.value}
        if token.type == "dot":
            self._consume()
            return {"type": "current"}
        if token.type == "left":
            self._consume("left")
            nested = self._parse_binary(1)
            self._consume("right")
            return nested
        if token.type == "identifier":
            self._consume("identifier")
            if token.value == "true" or token.value == "false":
                return {"type": "literal", "value": token.value == "true"}
            if token.value == "null":
                return {"type": "literal", "value": None}
            self._consume("left")
            arguments: list[dict[str, Any]] = []
            if self._peek().type != "right":
                while True:
                    arguments.append(self._parse_binary(1))
                    if self._peek().type != "comma":
                        break
                    self._consume("comma")
            self._consume("right")
            if token.value == "not":
                if len(arguments) != 1:
                    raise ExpressionError("not() requires one argument")
                return {"type": "unary", "operator": "not", "operand": arguments[0]}
            if token.value not in _SUPPORTED_FUNCTIONS:
                raise ExpressionError(f"Unsupported function '{token.value}'")
            return _call_node(token.value, arguments)
        raise ExpressionError(f"Unexpected token '{token.value}'")


def _call_node(name: str, arguments: list[dict[str, Any]]) -> dict[str, Any]:
    expected = 2 if name in ("selected", "regex") else 3 if name == "if" else 0 if name == "today" else 1
    if len(arguments) != expected:
        raise ExpressionError(f"{name}() requires {expected} arguments")
    return {"type": "call", "name": name, "arguments": arguments}


def parse_expression(source: str) -> dict[str, Any]:
    """Parse a supported XLSForm expression into an AST dict, as
    ``parseExpression`` does in ``expression.ts`` (same node shapes:
    ``literal``/``reference``/``current``/``unary``/``binary``/``call``)."""
    return _Parser(_tokenize(source.strip())).parse()


def is_empty(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, list) and len(value) == 0)


def as_boolean(value: Any) -> bool:
    if is_empty(value) or value is False or value == 0 or value == "0" or value == "false":
        return False
    return True


def is_iso_date(value: Any) -> bool:
    return isinstance(value, str) and _ISO_DATE_RE.match(value) is not None


def date_number(value: str) -> float:
    """Days (not ms) since the Unix epoch, mirroring ``Date.parse(value) /
    86_400_000``. Only ever called on a string ``is_iso_date`` accepted
    (date-only, or date with a ``T``-prefixed suffix)."""
    date_only = _ISO_DATE_ONLY_RE.match(value)
    if date_only:
        # A date-only ISO string is parsed as UTC midnight by Date.parse.
        try:
            parsed = date(int(date_only.group(1)), int(date_only.group(2)), int(date_only.group(3)))
        except ValueError:
            return math.nan
        return float((parsed - _EPOCH).days)
    try:
        parsed_dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return math.nan
    if parsed_dt.tzinfo is None:
        # No offset in the source string: Date.parse reads this as the
        # runtime's local time. This evaluator has no ambient "local"
        # timezone (see the module docstring), so an offset-less date-time
        # value is undefined behaviour here; treat it as UTC rather than
        # raising, which is the safer of the two silent choices (it will
        # not go unnoticed since no expression in the instrument produces
        # this shape today).
        parsed_dt = parsed_dt.replace(tzinfo=UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    return (parsed_dt - epoch).total_seconds() / 86_400


def _js_number(value: str) -> float:
    """``Number(value)`` for the string shapes that can appear here (JS's
    hex/octal/binary literal forms are not ported: nothing in this
    instrument's expressions or answers produces them)."""
    stripped = value.strip()
    if _JS_NUMBER_LITERAL_RE.match(stripped):
        if stripped in ("Infinity", "+Infinity"):
            return math.inf
        if stripped == "-Infinity":
            return -math.inf
        return float(stripped)
    return math.nan


def as_number(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if is_iso_date(value):
        return date_number(value)
    if isinstance(value, str) and value.strip() != "":
        return _js_number(value)
    return math.nan


def equal(left: Any, right: Any) -> bool:
    if is_empty(left) and is_empty(right):
        return True
    left_is_number = isinstance(left, (int, float)) and not isinstance(left, bool)
    right_is_number = isinstance(right, (int, float)) and not isinstance(right, bool)
    if left_is_number or right_is_number:
        left_number = as_number(left)
        right_number = as_number(right)
        if not math.isnan(left_number) and not math.isnan(right_number):
            return left_number == right_number
    return _js_string(left) == _js_string(right)


def _js_string(value: Any) -> str:
    """``String(value)``, for the coercions ``equal()`` falls back to."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if value == int(value) and math.isfinite(value):
            return str(int(value))
        return str(value)
    if isinstance(value, list):
        return ",".join(_js_string(item) for item in value)
    return str(value)


@dataclass(frozen=True)
class ExpressionEvaluationOptions:
    current_value: AnswerValue = None
    now: datetime | None = None


def evaluate_expression(
    node: dict[str, Any],
    data: SubmissionData,
    options: ExpressionEvaluationOptions | None = None,
) -> Any:
    """Evaluate an AST from :func:`parse_expression`, mirroring
    ``evaluateExpression`` in ``expression.ts`` node for node. ``options.now``
    must be timezone-aware when a ``today()``/date expression is reachable;
    see the module docstring."""
    options = options or ExpressionEvaluationOptions()
    node_type = node["type"]

    if node_type == "literal":
        return node["value"]
    if node_type == "reference":
        return data.get(node["name"])
    if node_type == "current":
        return options.current_value
    if node_type == "unary":
        value = evaluate_expression(node["operand"], data, options)
        if node["operator"] == "not":
            return not as_boolean(value)
        return -as_number(value)
    if node_type == "binary":
        operator = node["operator"]
        if operator == "and":
            return as_boolean(evaluate_expression(node["left"], data, options)) and as_boolean(
                evaluate_expression(node["right"], data, options)
            )
        if operator == "or":
            return as_boolean(evaluate_expression(node["left"], data, options)) or as_boolean(
                evaluate_expression(node["right"], data, options)
            )
        left = evaluate_expression(node["left"], data, options)
        right = evaluate_expression(node["right"], data, options)
        if operator == "=":
            return equal(left, right)
        if operator == "!=":
            return not equal(left, right)
        if operator == ">":
            return as_number(left) > as_number(right)
        if operator == ">=":
            return as_number(left) >= as_number(right)
        if operator == "<":
            return as_number(left) < as_number(right)
        if operator == "<=":
            return as_number(left) <= as_number(right)
        if operator == "+":
            return as_number(left) + as_number(right)
        if operator == "-":
            return as_number(left) - as_number(right)
        if operator == "*":
            return as_number(left) * as_number(right)
        if operator == "div":
            return _js_divide(as_number(left), as_number(right))
        if operator == "mod":
            return _js_mod(as_number(left), as_number(right))
        return None
    if node_type == "call":
        return _evaluate_call(node, data, options)
    raise ExpressionError(f"Unknown node type '{node_type}'")


def _js_divide(left: float, right: float) -> float:
    if right == 0:
        if math.isnan(left) or left == 0:
            return math.nan
        return math.inf if (left > 0) == (math.copysign(1.0, right) > 0) else -math.inf
    return left / right


def _js_mod(left: float, right: float) -> float:
    if math.isnan(left) or math.isnan(right) or math.isinf(left) or right == 0:
        return math.nan
    if math.isinf(right):
        return left
    result = math.fmod(left, right)
    return result


def _evaluate_call(node: dict[str, Any], data: SubmissionData, options: ExpressionEvaluationOptions) -> Any:
    name = node["name"]
    if name == "if":
        condition = node["arguments"][0]
        branch = node["arguments"][1] if as_boolean(evaluate_expression(condition, data, options)) else node["arguments"][2]
        return evaluate_expression(branch, data, options)

    arguments = [evaluate_expression(argument, data, options) for argument in node["arguments"]]
    if name == "selected":
        value, wanted = arguments
        if isinstance(value, list):
            return any(equal(item, wanted) for item in value)
        return equal(value, wanted)
    if name == "regex":
        value, pattern = arguments
        if is_empty(value):
            return False
        # re.ASCII: JavaScript's \d/\w/\s in a RegExp with no `u` flag match
        # ASCII only. Without this flag Python's \d matches any Unicode
        # decimal digit, so e.g. a Devanagari numeral would pass a pattern
        # like `^\d{1,3}$` here while failing it in the browser -- the
        # divergence beads digitva-cal.1 names explicitly (sa13-sa19).
        try:
            compiled = re.compile(str(pattern), re.ASCII)
        except re.error as error:
            raise ExpressionError(f"Invalid regex pattern {pattern!r}: {error}") from error
        return compiled.search(_js_string(value)) is not None
    if name == "count-selected":
        value = arguments[0]
        if isinstance(value, list):
            return float(len(value))
        if isinstance(value, str) and value.strip():
            return float(len(value.strip().split()))
        return 0.0
    if name == "string-length":
        return 0.0 if is_empty(arguments[0]) else float(len(_js_string(arguments[0])))
    if name == "int":
        number = as_number(arguments[0])
        return math.nan if math.isnan(number) else float(math.trunc(number))
    if name == "today":
        now = options.now
        if now is None or now.tzinfo is None:
            raise ExpressionError("today() requires a timezone-aware 'now' in evaluation options")
        return now.strftime("%Y-%m-%d")
    if name == "date":
        value = arguments[0]
        if is_iso_date(value):
            return value[:10]
        return value
    raise ExpressionError(f"Unsupported function '{name}'")
