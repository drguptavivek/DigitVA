#!/usr/bin/env python3
"""Export a lean ICD-10 2019 hierarchy CSV from the local WHO ClaML XML.

Usage (inside Docker):
  docker compose exec minerva_app_service \
    uv run python scripts/export_icd10_hierarchy_csv.py
"""

from __future__ import annotations

import argparse
import csv
import re
import xml.etree.ElementTree as ET
from pathlib import Path


DEFAULT_XML_PATH = Path("docs/icd-causegrp-mappings/ICD-to-VA-Buckets/icd102019en.xml")
DEFAULT_OUTPUT_PATH = Path("docs/icd-causegrp-mappings/generated/icd10_2019_hierarchy.csv")
THREE_CHARACTER_CODE_RE = re.compile(r"^[A-Z][0-9][0-9]$")
ICD_CODE_RE = re.compile(r"^[A-Z][0-9][0-9](?:\.[0-9]+)?$")

CSV_FIELDS = [
    "code",
    "title",
    "node_type",
    "semantic_level",
    "parent_code",
    "chapter_code",
    "chapter_title",
    "block_code",
    "block_title",
    "three_character_code",
    "three_character_title",
    "has_children",
    "is_leaf",
    "is_three_character_code",
    "is_detailed_code",
    "is_coding_selectable",
    "sex_selectable",
    "age_group_selectable",
    "policy_status",
    "restriction_note",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a lean ICD-10 2019 hierarchy CSV from the WHO ClaML XML.",
    )
    parser.add_argument(
        "--xml-path",
        default=str(DEFAULT_XML_PATH),
        help=f"Input ClaML XML path. Default: {DEFAULT_XML_PATH}",
    )
    parser.add_argument(
        "--output-path",
        default=str(DEFAULT_OUTPUT_PATH),
        help=f"Output CSV path. Default: {DEFAULT_OUTPUT_PATH}",
    )
    return parser.parse_args()


def _preferred_title(node: ET.Element) -> str:
    rubric = node.find("Rubric[@kind='preferred']")
    if rubric is None:
        rubric = node.find("Rubric[@kind='preferredLong']")
    if rubric is None:
        return ""
    label = rubric.find("Label")
    if label is None:
        return ""
    return " ".join("".join(label.itertext()).split())


def _is_three_character_code(code: str) -> bool:
    return bool(THREE_CHARACTER_CODE_RE.fullmatch(code or ""))


def _semantic_level(node_type: str, code: str) -> str:
    if node_type == "chapter":
        return "chapter"
    if node_type == "block":
        return "block"
    if _is_three_character_code(code):
        return "three_character"
    return "detailed_code"


def _load_classes(
    xml_path: Path,
) -> tuple[dict[str, dict[str, object]], list[str]]:
    root = ET.parse(xml_path).getroot()
    class_nodes = root.findall("Class")
    top_level_sort = ""

    for meta in root.findall("Meta"):
        if meta.attrib.get("name") == "TopLevelSort":
            top_level_sort = meta.attrib.get("value", "")
            break

    classes: dict[str, dict[str, object]] = {}
    for node in class_nodes:
        code = node.attrib["code"]
        child_codes = [child.attrib["code"] for child in node.findall("SubClass")]
        parent = node.find("SuperClass")
        classes[code] = {
            "code": code,
            "title": _preferred_title(node),
            "node_type": node.attrib.get("kind", ""),
            "parent_code": parent.attrib.get("code", "") if parent is not None else "",
            "child_codes": child_codes,
        }

    modifier_classes_by_code: dict[str, list[ET.Element]] = {}
    for modifier_node in root.findall("ModifierClass"):
        modifier_code = modifier_node.attrib.get("modifier")
        if not modifier_code:
            continue
        modifier_classes_by_code.setdefault(modifier_code, []).append(modifier_node)

    for node in class_nodes:
        parent_code = node.attrib["code"]
        if not ICD_CODE_RE.fullmatch(parent_code):
            continue
        modified_by_nodes = node.findall("ModifiedBy")
        if not modified_by_nodes:
            continue

        for modified_by_node in modified_by_nodes:
            modifier_code = modified_by_node.attrib.get("code")
            if not modifier_code:
                continue
            for modifier_class in modifier_classes_by_code.get(modifier_code, []):
                suffix = modifier_class.attrib.get("code", "")
                if not suffix:
                    continue
                code = _modified_code(parent_code, suffix)
                if code in classes:
                    continue
                classes[code] = {
                    "code": code,
                    "title": _modified_title(node, modifier_class),
                    "node_type": "modifiedcategory",
                    "parent_code": parent_code,
                    "child_codes": [],
                }
                classes[parent_code]["child_codes"].append(code)

    top_level_codes = [code for code in top_level_sort.split() if code in classes]
    return classes, top_level_codes


def _modified_code(parent_code: str, suffix: str) -> str:
    if suffix.startswith(".") and "." in parent_code:
        return f"{parent_code}{suffix[1:]}"
    if suffix and suffix[0].isdigit() and "." not in parent_code:
        return f"{parent_code}.{suffix}"
    return f"{parent_code}{suffix}"


def _modified_title(parent_node: ET.Element, modifier_node: ET.Element) -> str:
    parent_title = _preferred_title(parent_node)
    modifier_title = _preferred_title(modifier_node)
    if parent_title and modifier_title:
        return f"{parent_title} : {modifier_title}"
    return parent_title or modifier_title


def _lineage(code: str, classes: dict[str, dict[str, object]]) -> list[str]:
    path: list[str] = []
    current = code
    while current:
        path.append(current)
        current = str(classes[current]["parent_code"])
    path.reverse()
    return path


def _ordered_codes(
    classes: dict[str, dict[str, object]],
    top_level_codes: list[str],
) -> list[str]:
    ordered: list[str] = []

    def walk(code: str) -> None:
        ordered.append(code)
        for child_code in classes[code]["child_codes"]:
            if child_code in classes:
                walk(child_code)

    for code in top_level_codes:
        walk(code)
    return ordered


def _row_for_code(code: str, classes: dict[str, dict[str, object]]) -> dict[str, str]:
    node = classes[code]
    lineage_codes = _lineage(code, classes)
    lineage_nodes = [classes[item] for item in lineage_codes]

    chapter_node = next((item for item in lineage_nodes if item["node_type"] == "chapter"), None)
    block_node = next((item for item in lineage_nodes if item["node_type"] == "block"), None)
    three_character_node = next(
        (item for item in lineage_nodes if _is_three_character_code(str(item["code"]))),
        None,
    )

    child_codes = [child for child in node["child_codes"] if child in classes]
    is_three_character = _is_three_character_code(code)
    is_detailed_code = "." in code
    has_children = bool(child_codes)

    return {
        "code": str(node["code"]),
        "title": str(node["title"]),
        "node_type": str(node["node_type"]),
        "semantic_level": _semantic_level(str(node["node_type"]), code),
        "parent_code": str(node["parent_code"]),
        "chapter_code": str(chapter_node["code"]) if chapter_node else "",
        "chapter_title": str(chapter_node["title"]) if chapter_node else "",
        "block_code": str(block_node["code"]) if block_node else "",
        "block_title": str(block_node["title"]) if block_node else "",
        "three_character_code": str(three_character_node["code"]) if three_character_node else "",
        "three_character_title": (
            str(three_character_node["title"]) if three_character_node else ""
        ),
        "has_children": str(has_children).lower(),
        "is_leaf": str(not has_children).lower(),
        "is_three_character_code": str(is_three_character).lower(),
        "is_detailed_code": str(is_detailed_code).lower(),
        "is_coding_selectable": "",
        "sex_selectable": "",
        "age_group_selectable": "",
        "policy_status": "unreviewed",
        "restriction_note": "",
    }


def main() -> int:
    args = _parse_args()
    xml_path = Path(args.xml_path)
    output_path = Path(args.output_path)

    classes, top_level_codes = _load_classes(xml_path)
    rows = [_row_for_code(code, classes) for code in _ordered_codes(classes, top_level_codes)]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} hierarchy rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
