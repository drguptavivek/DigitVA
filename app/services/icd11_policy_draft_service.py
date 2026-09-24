"""Draft the ICD-11 coding-selectability policy from WHO's VA annex.

Policy: docs/policy/who-2022-icd11-coding-allowability.md (draft, owner
review pending). A category is selectable when WHO's annex ICD-11 ranges
cover it (expanded with the bucket generator's own range helpers) or owner
decision 5a names it, unless its chapter is never selectable. Sex and age
restrictions come from the reviewed ICD-10 policy through WHO's
10To11MapToOneCategory table, then from the chapter rules the ICD-10 policy
applies to the equivalent chapters.

Nothing here writes to the database: the output is a policy JSON in the
``import_icd11_mms_policy_json`` format plus a review CSV and README, for the
owner to review before anyone imports it.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models import MasIcd11Mms
from app.services.cod_bucket_icd11_generator import (
    CAUSE_LIST_PATH,
    CHANGE_LIST_PATH,
    CROSSWALK_PATH,
    _load_cause_list,
    _load_crosswalk,
    expand_range,
    load_catalogue,
    parse_icd11_ranges,
)

DEFAULT_POLICY_DRAFT_DIR = (
    "docs/icd-causegrp-mappings/migration-artifacts/who-2022-icd11-policy-draft-2026-09-24"
)
ICD10_POLICY_PATH = (
    "docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd-cod-2026-revision/"
    "who_2022_icd10_2019_2_policy_reviewed.json"
)
TEN_TO_ELEVEN_PATH = (
    "docs/icd-causegrp-mappings/migration-artifacts/"
    "icd11-icd10-mapping-tables-2025-01-base-2026-09-16/10To11MapToOneCategory.txt"
)
SOURCE_VERSION = "WHO_2022_ICD11_MMS_2026_01_DRAFT"

# Owner decision 4 (2026-09-24): the annex's one malformed range.
ANNEX_CORRECTIONS = {"5C52.Y-5C52-Z": "5C52.Y-5C52.Z"}
# Owner decision 5a (2026-09-24): clinically relevant codes in no annex
# range. Each `(start, end)` covers its descendants, as annex ranges do.
DECISION_5A_RANGES = (
    ("5A20", "5A2Y"),
    ("3A50", "3A50"),
    ("3A4Z", "3A4Z"),
    ("DB94", "DB94"),
    ("1C8G", "1C8G"),
    ("1C8H", "1C8H"),
    ("RA01", "RA01"),
)
# Chapters never selectable: factors influencing health status (Q),
# traditional medicine (S), functioning (V), extension codes (X).
EXCLUDED_CHAPTERS = {"24": "Q", "26": "S", "V": "V", "X": "X"}
# Chapter 25 (RA emergency codes) is selectable only for the RA01 family.
EMERGENCY_CHAPTER = "25"
EMERGENCY_ALLOWED_STEM = "RA01"
# The ICD-10 policy restricts whole chapters: O00-O99 female adult,
# P00-P96 neonate, on their ICD-11 chapters. Chapter 20 (LA-LD) is all ages
# although ICD-10 makes Q00-Q99 neonate (owner, 2026-09-24).
CHAPTER_RESTRICTIONS = {
    "18": ("female", "adult", "chapter 18 (JA-JB), as ICD-10 O00-O99"),
    "19": ("both", "neonate", "chapter 19 (KA-KD), as ICD-10 P00-P96"),
}
# The ICD-10 policy's named sex-specific neoplasm ranges, on their ICD-11
# blocks: C51-C58, C60-C63, D26-D28, D29 (D25 maps one-to-one to 2E86.0).
BLOCK_RESTRICTIONS = (
    ("2C70", "2C7Z", "female", "all", "block 2C70-2C7Z, as ICD-10 C51-C58"),
    ("2C80", "2C8Z", "male", "all", "block 2C80-2C8Z, as ICD-10 C60-C63"),
    ("2F31", "2F33", "female", "all", "2F31-2F33, as ICD-10 D26-D28"),
    ("2F34", "2F34", "male", "all", "2F34, as ICD-10 D29"),
)
# ICD-10 chapters whose restriction is a blanket chapter rule, not a
# judgement about the code: never carried to ICD-11 (owner, 2026-09-24).
# The chapter rules above cover chapters 18 and 19 instead.
ICD10_BLANKET_RULE_LETTERS = ("O", "P", "Q")
DEFAULT_RESTRICTION = ("both", "all")

RULE_ANNEX = "annex"
RULE_DECISION_5A = "decision_5a"
RULE_EXCLUDED_CHAPTER = "excluded_chapter"
RULE_EXCLUDED_EMERGENCY = "excluded_emergency"
RULE_NOT_IN_ANNEX = "not_in_annex"

FLAG_PAST_END = "past_written_end"
FLAG_CONFLICT = "icd10_conflict"
FLAG_NOT_ONE_TO_ONE = "icd10_not_one_to_one"
FLAG_RULE_OVERRIDES_ICD10 = "rule_overrides_icd10"
FLAG_CHILDREN_DIFFER = "children_differ"


@dataclass
class Icd11PolicyDraft:
    """One draft run: a decision per active category plus range issues."""

    release: str
    decisions: list[dict] = field(default_factory=list)
    range_issues: list[str] = field(default_factory=list)

    @property
    def selectable(self) -> list[dict]:
        return [row for row in self.decisions if row["selectable"]]


def load_icd10_restrictions(path: str = ICD10_POLICY_PATH) -> dict[str, tuple[str, str]]:
    """`{icd10_code: (sex, age)}` for the selectable rows of an ICD-10 policy JSON."""
    with open(path, encoding="utf-8") as handle:
        items = json.load(handle)["items"]
    return {
        item["code"]: (item["sex_selectable"] or "both", item["age_group_selectable"] or "all")
        for item in items
        if item.get("is_coding_selectable")
    }


def load_icd10_to_icd11(
    path: str = TEN_TO_ELEVEN_PATH,
    change_list_path: str = CHANGE_LIST_PATH,
    crosswalk_path: str = CROSSWALK_PATH,
) -> dict[str, str]:
    """WHO 10To11MapToOneCategory as `{icd10_code: icd11_target}`, 2026-01 codes.

    Targets are 2025-01 codes; each code a 2026-01 `MovedTo` change renamed is
    translated, inside `&` (postcoordination) and `/` (alternatives) too. The
    change list is read through the bucket generator's loader so both tools
    translate the same way.
    """
    _, moved_from = _load_crosswalk(crosswalk_path, change_list_path)
    moved_to = {old: new for new, old in moved_from.items()}
    mapping: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle, delimiter="\t")
        next(reader, None)
        for row in reader:
            if len(row) < 10 or not row[2].strip() or not row[9].strip():
                continue
            mapping[row[2].strip()] = "/".join(
                "&".join(moved_to.get(part, part) for part in alternative.split("&"))
                for alternative in row[9].strip().split("/")
            )
    return mapping


def load_category_rows(release: str) -> list[dict]:
    """Every active category of `release`, all chapters, in WHO order."""
    rows = db.session.execute(
        sa.select(
            MasIcd11Mms.code,
            MasIcd11Mms.title,
            MasIcd11Mms.linearization_uri,
            MasIcd11Mms.chapter_no,
            MasIcd11Mms.is_residual,
            MasIcd11Mms.is_leaf,
        )
        .where(
            MasIcd11Mms.release == release,
            MasIcd11Mms.is_active.is_(True),
            MasIcd11Mms.class_kind == "category",
            MasIcd11Mms.code.is_not(None),
        )
        .order_by(MasIcd11Mms.sort_order, MasIcd11Mms.linearization_uri)
    ).all()
    return [row._asdict() for row in rows]


def _icd10_sources(
    icd10_to_icd11: dict[str, str], restrictions: dict[str, tuple[str, str]]
) -> tuple[dict[str, list], dict[str, list]]:
    """`(plain, loose)`: `{icd11_code: [(icd10_code, (sex, age))]}`.

    An ICD-10 code's restriction is its own policy row, or for a dotted code
    not in the policy its three-character parent's (the ICD-10 policy writes
    its restrictions at three-character level). `plain` holds single-code
    targets; `loose` holds the stems of postcoordinated or alternative ones.
    O, P and Q codes are left out: their restriction is a blanket chapter rule.
    """
    plain: dict[str, list] = defaultdict(list)
    loose: dict[str, list] = defaultdict(list)
    for icd10_code, target in icd10_to_icd11.items():
        if icd10_code.startswith(ICD10_BLANKET_RULE_LETTERS):
            continue
        restriction = restrictions.get(icd10_code)
        if restriction is None and "." in icd10_code:
            restriction = restrictions.get(icd10_code.split(".")[0])
        if restriction is None:
            continue
        if "&" not in target and "/" not in target:
            plain[target].append((icd10_code, restriction))
            continue
        for alternative in target.split("/"):
            loose[alternative.split("&")[0]].append((icd10_code, restriction))
    return plain, loose


def _format_restriction(restriction: tuple[str, str]) -> str:
    return f"{restriction[0]}/{restriction[1]}"


def _selectable_rules(
    catalogue: dict[str, dict], cause_rows: list[dict], range_issues: list[str]
) -> tuple[dict[str, str], dict[str, set]]:
    """`({code: rule}, {code: flags})` from the annex ranges and decision 5a."""
    sorted_codes = sorted(catalogue)
    rules: dict[str, str] = {}
    flags: dict[str, set] = defaultdict(set)
    for cause in cause_rows:
        text = cause.get("icd11_codes") or ""
        for wrong, right in ANNEX_CORRECTIONS.items():
            text = text.replace(wrong, right)
        ranges, bad_tokens = parse_icd11_ranges(text)
        range_issues.extend(f"{cause['va_code']}: malformed token {token}" for token in bad_tokens)
        for token, start, end in ranges:
            covered, past_end = expand_range(start, end, sorted_codes, catalogue)
            if not covered:
                range_issues.append(f"{cause['va_code']}: {token} covers no catalogue category")
            for code in covered:
                rules.setdefault(code, RULE_ANNEX)
            for code in past_end:
                flags[code].add(f"{FLAG_PAST_END}:{token}")
    for start, end in DECISION_5A_RANGES:
        covered, _ = expand_range(start, end, sorted_codes, catalogue)
        if not covered:
            range_issues.append(f"decision 5a: {start}-{end} covers no catalogue category")
        for code in covered:
            rules.setdefault(code, RULE_DECISION_5A)
    return rules, flags


def _icd10_restriction(
    plain: list, loose: list, row_flags: set
) -> tuple[tuple[str, str], str, str]:
    """`(restriction, source, detail)` from a code's ICD-10 sources.

    Carried only when every source agrees; disagreeing sources, or sources
    reaching the code only through postcoordinated or alternative targets,
    leave both/all and flag the code.
    """
    values = {value for _, value in plain + loose}
    if plain and len(values) == 1:
        return values.pop(), "icd10", "icd10 " + " ".join(sorted(code for code, _ in plain))
    listing = " ".join(f"{code}={_format_restriction(value)}" for code, value in sorted(plain + loose))
    if plain:
        row_flags.add(f"{FLAG_CONFLICT}:{listing}")
    elif any(value != DEFAULT_RESTRICTION for value in values):
        row_flags.add(f"{FLAG_NOT_ONE_TO_ONE}:{listing}")
    return DEFAULT_RESTRICTION, "default", "default"


def draft_icd11_policy(
    *,
    release: str,
    rows: list[dict],
    catalogue: dict[str, dict],
    cause_rows: list[dict],
    icd10_restrictions: dict[str, tuple[str, str]],
    icd10_to_icd11: dict[str, str],
) -> Icd11PolicyDraft:
    """Decide selectability, sex and age for every row (no database access).

    `rows` are the release's active categories in WHO order (parents before
    children); `catalogue` is `load_catalogue`'s `{code: {"title", "parent"}}`.
    Selectable: annex or decision 5a, minus the excluded chapters. Sex/age of
    a selectable code, first match wins: a chapter or block rule; its ICD-10
    sources when they all agree; its parent's ICD-10-derived value; the one
    value all its selectable children share; else both/all.
    """
    draft = Icd11PolicyDraft(release=release)
    selectable_rules, flags = _selectable_rules(catalogue, cause_rows, draft.range_issues)
    plain_sources, loose_sources = _icd10_sources(icd10_to_icd11, icd10_restrictions)
    sorted_codes = sorted(catalogue)
    block_rules: dict[str, tuple[tuple[str, str], str]] = {}
    for start, end, sex, age, label in BLOCK_RESTRICTIONS:
        for code in expand_range(start, end, sorted_codes, catalogue)[0]:
            block_rules[code] = ((sex, age), label)

    by_code: dict[str, dict] = {}
    for row in rows:
        code = row["code"]
        chapter = row["chapter_no"]
        rule = selectable_rules.get(code, RULE_NOT_IN_ANNEX)
        if chapter in EXCLUDED_CHAPTERS:
            rule = RULE_EXCLUDED_CHAPTER
        elif chapter == EMERGENCY_CHAPTER and code.split(".")[0] != EMERGENCY_ALLOWED_STEM:
            rule = RULE_EXCLUDED_EMERGENCY
        decision = {
            "code": code,
            "title": row["title"],
            "linearization_uri": row["linearization_uri"],
            "chapter_no": chapter,
            "is_residual": bool(row.get("is_residual")),
            "is_leaf": bool(row.get("is_leaf", True)),
            "selectable": rule in (RULE_ANNEX, RULE_DECISION_5A),
            "rule": rule,
            "sex": None,
            "age": None,
            "restriction_source": "",
            "restriction_rule": "",
            "flags": flags.get(code, set()),
        }
        draft.decisions.append(decision)
        by_code[code] = decision
        if not decision["selectable"]:
            continue

        plain = plain_sources.get(code, [])
        restriction, source, detail = _icd10_restriction(
            plain, loose_sources.get(code, []), decision["flags"]
        )
        parent = by_code.get(catalogue.get(code, {}).get("parent"))
        if source == "default" and parent and parent["restriction_source"] in ("icd10", "inherited"):
            restriction, source = (parent["sex"], parent["age"]), "inherited"
            detail = f"inherited from {parent['code']}"
        decision["sex"], decision["age"] = restriction
        decision["restriction_source"], decision["restriction_rule"] = source, detail

    children: dict[str, list[dict]] = defaultdict(list)
    for decision in draft.selectable:
        parent_code = catalogue.get(decision["code"], {}).get("parent")
        if parent_code in by_code:
            children[parent_code].append(decision)
    # Children come after their parent in WHO order, so walking backwards
    # settles a whole subtree before its root.
    for decision in reversed(draft.selectable):
        kids = children.get(decision["code"])
        if decision["restriction_source"] != "default" or not kids:
            continue
        values = {(kid["sex"], kid["age"]) for kid in kids}
        if len(values) == 1 and values != {DEFAULT_RESTRICTION}:
            decision["sex"], decision["age"] = values.pop()
            decision["restriction_source"] = "children"
            decision["restriction_rule"] = "shared by all selectable children"

    for decision in draft.selectable:
        chapter = decision["chapter_no"]
        if chapter in CHAPTER_RESTRICTIONS:
            sex, age, label = CHAPTER_RESTRICTIONS[chapter]
            override, source = ((sex, age), label), f"chapter {chapter}"
        elif decision["code"] in block_rules:
            override, source = block_rules[decision["code"]], "block"
        else:
            continue
        current = (decision["sex"], decision["age"])
        if current not in (DEFAULT_RESTRICTION, override[0]):
            decision["flags"].add(f"{FLAG_RULE_OVERRIDES_ICD10}:{_format_restriction(current)}")
        (decision["sex"], decision["age"]), decision["restriction_rule"] = override
        decision["restriction_source"] = source

    for decision in draft.selectable:
        kids = children.get(decision["code"], [])
        if len({(kid["sex"], kid["age"]) for kid in kids} | {(decision["sex"], decision["age"])}) > 1:
            decision["flags"].add(FLAG_CHILDREN_DIFFER)
    return draft


def build_icd11_policy_draft(release: str) -> Icd11PolicyDraft:
    """Run the draft against the database catalogue and the frozen sources."""
    return draft_icd11_policy(
        release=release,
        rows=load_category_rows(release),
        catalogue=load_catalogue(release),
        cause_rows=_load_cause_list(CAUSE_LIST_PATH),
        icd10_restrictions=load_icd10_restrictions(),
        icd10_to_icd11=load_icd10_to_icd11(),
    )


def policy_payload(draft: Icd11PolicyDraft) -> dict:
    """The selectable rows in the `import_icd11_mms_policy_json` format.

    `policy_status` is left out on purpose: the importer then keeps each
    row's status, so re-importing a regenerated draft never clears a
    `reviewed` mark the owner has set. A restricted row carries its
    provenance in `restriction_note`.
    """
    items = [
        {
            "linearization_uri": row["linearization_uri"],
            "code": row["code"],
            "title": row["title"],
            "class_kind": "category",
            "chapter_no": row["chapter_no"],
            "is_coding_selectable": True,
            "sex_selectable": row["sex"],
            "age_group_selectable": row["age"],
            "restriction_note": (
                f"Draft: {row['restriction_rule']}"
                if (row["sex"], row["age"]) != DEFAULT_RESTRICTION
                else None
            ),
        }
        for row in draft.selectable
    ]
    return {
        "release": draft.release,
        "source_version": SOURCE_VERSION,
        "status": "draft",
        "policy": "docs/policy/who-2022-icd11-coding-allowability.md",
        "row_count": len(items),
        "items": items,
    }


def write_icd11_policy_draft(draft: Icd11PolicyDraft, output_dir: str | Path) -> list[Path]:
    """Write the policy JSON, the review CSV and a README with the counts."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    policy_path = output_dir / "who_2022_icd11_mms_2026_01_policy_draft.json"
    policy_path.write_text(json.dumps(policy_payload(draft), indent=2) + "\n", encoding="utf-8")

    review_rows = [row for row in draft.decisions if row["chapter_no"] != "X"]
    review_path = output_dir / "icd11_policy_review.csv"
    with open(review_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ["code", "title", "chapter_no", "selectable", "sex", "age", "rule",
             "restriction_rule", "residual", "leaf", "flags"]
        )
        for row in review_rows:
            writer.writerow(
                [row["code"], row["title"], row["chapter_no"], "yes" if row["selectable"] else "no",
                 row["sex"] or "", row["age"] or "", row["rule"], row["restriction_rule"],
                 "yes" if row["is_residual"] else "no", "yes" if row["is_leaf"] else "no",
                 "; ".join(sorted(row["flags"]))]
            )

    readme_path = output_dir / "README.md"
    readme_path.write_text(_readme(draft), encoding="utf-8")
    return [policy_path, review_path, readme_path]


def _readme(draft: Icd11PolicyDraft) -> str:
    selectable = draft.selectable
    chapters = sorted(
        {row["chapter_no"] for row in draft.decisions},
        key=lambda chapter: (not chapter.isdigit(), chapter.zfill(2)),
    )
    total_by_chapter = Counter(row["chapter_no"] for row in draft.decisions)
    selectable_by_chapter = Counter(row["chapter_no"] for row in selectable)
    rules = Counter(row["rule"] for row in draft.decisions)
    restrictions = Counter(
        (row["sex"], row["age"]) for row in selectable if (row["sex"], row["age"]) != DEFAULT_RESTRICTION
    )
    restriction_sources = Counter(
        row["restriction_source"]
        for row in selectable
        if (row["sex"], row["age"]) != DEFAULT_RESTRICTION
    )
    flag_counts = Counter(
        flag.split(":")[0] for row in draft.decisions for flag in row["flags"] if row["chapter_no"] != "X"
    )
    lines = [
        "---",
        "title: WHO 2022 ICD-11 coding-selectability policy draft (2026-01)",
        "doc_type: migration-artifact",
        "status: draft",
        "owner: engineering",
        f"last_updated: {date.today().isoformat()}",
        "---",
        "",
        "# WHO 2022 ICD-11 coding-selectability policy draft (2026-01)",
        "",
        "Written by `flask icd11 policy-draft` "
        "(`app/services/icd11_policy_draft_service.py`). Rules: "
        "`docs/policy/who-2022-icd11-coding-allowability.md` (draft, owner review "
        "pending). Nothing here has been imported into any database and no "
        "migration reads this folder.",
        "",
        "Sources: annex ICD-11 ranges `" + CAUSE_LIST_PATH + "`; catalogue "
        f"`mas_icd11_mms` release `{draft.release}`; ICD-10 restrictions `{ICD10_POLICY_PATH}`; "
        f"ICD-10 to ICD-11 map `{TEN_TO_ELEVEN_PATH}` (2025-01 codes translated to 2026-01 "
        f"through the `MovedTo` rows of `{CHANGE_LIST_PATH}`).",
        "",
        "Owner decisions of 2026-09-24 applied: chapter 20 (LA-LD) is all ages (no "
        "neonate chapter rule), and ICD-10 O/P/Q restrictions (blanket chapter rules) are "
        "never carried to any ICD-11 code; chapters 18 and 19 take their chapter rules "
        "instead.",
        "",
        "## Files",
        "",
        "- `who_2022_icd11_mms_2026_01_policy_draft.json`: the selectable categories in the "
        "format `flask icd11 policy-import` and the admin ICD-11 browser import read. It is "
        "a full replacement: every active category it does not list (chapter X included) is "
        "reset to not selectable with no sex/age/note. Items carry no `policy_status`, so an "
        "import leaves each row's status as it is.",
        "- `icd11_policy_review.csv`: every category outside chapter X, with the rule that "
        "decided it, its sex/age, where they came from, and review flags.",
        "",
        "## Totals",
        "",
        f"- Active categories: {len(draft.decisions)}",
        f"- Selectable: {len(selectable)} (residual {sum(row['is_residual'] for row in selectable)}, "
        f"with children {sum(not row['is_leaf'] for row in selectable)})",
        "",
        "## Categories per rule",
        "",
        "| Rule | Categories |",
        "|---|---:|",
        *[f"| `{rule}` | {count} |" for rule, count in sorted(rules.items())],
        "",
        "## Selectable per chapter",
        "",
        "| Chapter | Categories | Selectable |",
        "|---|---:|---:|",
        *[
            f"| {chapter} | {total_by_chapter[chapter]} | {selectable_by_chapter[chapter]} |"
            for chapter in chapters
        ],
        "",
        "## Sex and age restrictions (selectable rows)",
        "",
        "| Sex | Age | Categories |",
        "|---|---|---:|",
        *[f"| {sex} | {age} | {count} |" for (sex, age), count in sorted(restrictions.items())],
        "",
        "| Source of the restriction | Categories |",
        "|---|---:|",
        *[f"| {source} | {count} |" for source, count in sorted(restriction_sources.items())],
        "",
        "## Review flags (chapter X excluded)",
        "",
        "| Flag | Categories |",
        "|---|---:|",
        *[f"| `{flag}` | {count} |" for flag, count in sorted(flag_counts.items())],
        "",
        "## Not selectable outside the excluded chapters",
        "",
        "Categories no annex range or decision 5a covers (`not_in_annex`) and the "
        "non-RA01 emergency codes (`excluded_emergency`):",
        "",
        *[
            f"- `{row['code']}` {row['title']} ({row['rule']})"
            for row in draft.decisions
            if row["rule"] in (RULE_NOT_IN_ANNEX, RULE_EXCLUDED_EMERGENCY)
        ],
        "",
        "## Range issues",
        "",
        *([f"- {issue}" for issue in draft.range_issues] or ["- none"]),
        "",
    ]
    return "\n".join(lines)
