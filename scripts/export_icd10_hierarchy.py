#!/usr/bin/env python3
"""Export WHO ICD-10 hierarchy tables from the WHO API or local XML snapshot.

Usage (inside Docker):
  docker compose exec minerva_app_service \
    uv run python scripts/export_icd10_hierarchy.py

The script can use either:
- the live WHO ICD API
- the local ICD-10 2019 ClaML XML snapshot

It writes normalized CSV tables under `docs/icd-causegrp-mappings/generated/`.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"
DEFAULT_RELEASE_URL = "https://id.who.int/icd/release/10/2019"
DEFAULT_OUTPUT_DIR = Path("docs/icd-causegrp-mappings/generated/icd10_2019_api")
DEFAULT_XML_PATH = Path("docs/icd-causegrp-mappings/ICD-to-VA-Buckets/icd102019en.xml")
DEFAULT_LANGUAGE = "en"
DEFAULT_WORKERS = 8
REQUEST_TIMEOUT_SECONDS = 60
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

THREE_CHARACTER_CODE_RE = re.compile(r"^[A-Z][0-9][0-9]$")

ENTITY_FIELDS = [
    "uri",
    "code",
    "title",
    "class_kind",
    "semantic_level",
    "depth",
    "parent_uri",
    "parent_code",
    "parent_title",
    "child_count",
    "is_leaf",
    "is_three_character_code",
    "is_terminal_code",
    "browser_url",
]
LINEAGE_FIELDS = [
    "uri",
    "code",
    "title",
    "class_kind",
    "semantic_level",
    "depth",
    "is_leaf",
    "is_three_character_code",
    "is_terminal_code",
    "chapter_code",
    "chapter_title",
    "block_code",
    "block_title",
    "three_character_code",
    "three_character_title",
    "final_code",
    "final_title",
]
EDGE_FIELDS = [
    "parent_uri",
    "parent_code",
    "parent_title",
    "child_index",
    "child_uri",
    "child_code",
    "child_title",
]
SUMMARY_FIELDS = ["metric", "count"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export WHO ICD-10 2019 hierarchy tables from the WHO API or XML snapshot.",
    )
    parser.add_argument(
        "--source",
        choices=("api", "xml"),
        default="xml",
        help="Hierarchy source. Default: xml",
    )
    parser.add_argument(
        "--release-url",
        default=DEFAULT_RELEASE_URL,
        help=f"WHO ICD release root URL for API mode. Default: {DEFAULT_RELEASE_URL}",
    )
    parser.add_argument(
        "--xml-path",
        default=str(DEFAULT_XML_PATH),
        help=f"Local ClaML XML path for XML mode. Default: {DEFAULT_XML_PATH}",
    )
    parser.add_argument(
        "--language",
        default=DEFAULT_LANGUAGE,
        help=f"Accept-Language value to request. Default: {DEFAULT_LANGUAGE}",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Directory for generated CSVs. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Concurrent fetch workers. Default: {DEFAULT_WORKERS}",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Append to existing CSVs in the output directory and continue from saved state.",
    )
    return parser.parse_args()


def _require_env(name: str) -> str:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return raw_value


def _extract_text(value: Any) -> str:
    if isinstance(value, dict):
        text = value.get("@value")
        return str(text).strip() if text else ""
    if value is None:
        return ""
    return str(value).strip()


def _is_three_character_code(code: str) -> bool:
    return bool(THREE_CHARACTER_CODE_RE.fullmatch(code or ""))


def _fetch_access_token(client_id: str, client_secret: str) -> str:
    response = requests.post(
        TOKEN_URL,
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials", "scope": "icdapi_access"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise SystemExit("WHO ICD token response did not include access_token.")
    return str(token)


def _fetch_entity(url: str, headers: dict[str, str]) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            return {
                "uri": url,
                "code": str(payload.get("code") or "").strip(),
                "title": _extract_text(payload.get("title")),
                "class_kind": str(payload.get("classKind") or "").strip(),
                "browser_url": str(payload.get("browserUrl") or "").strip(),
                "child_urls": list(dict.fromkeys(payload.get("child") or [])),
            }
        except requests.RequestException as exc:  # pragma: no cover - exercised in live runs
            last_error = exc
            if (
                isinstance(exc, requests.HTTPError)
                and exc.response is not None
                and exc.response.status_code not in RETRYABLE_STATUS_CODES
            ):
                break
            if attempt == 5:
                break
            time.sleep(min(2**attempt, 10))
    raise RuntimeError(f"Failed to fetch WHO ICD entity {url}: {last_error}") from last_error


def _log_entity_progress(record: dict[str, Any], total_fetched: int) -> None:
    code = record["code"] or record["uri"]
    title = record["title"] or "(no title)"

    if record["class_kind"] == "chapter":
        print(f"[chapter {total_fetched}] {code} {title}", flush=True)
        return

    if _is_three_character_code(record["code"]):
        print(f"[disease {total_fetched}] {code} {title}", flush=True)


def _build_xml_uri(code: str) -> str:
    if not code:
        return DEFAULT_RELEASE_URL
    return f"{DEFAULT_RELEASE_URL}/{code}"


def _extract_xml_preferred_title(node: ET.Element) -> str:
    rubric = node.find("Rubric[@kind='preferred']")
    if rubric is None:
        rubric = node.find("Rubric[@kind='preferredLong']")
    if rubric is None:
        return ""
    label = rubric.find("Label")
    if label is None:
        return ""
    return " ".join("".join(label.itertext()).split())


class _CsvAppender:
    def __init__(self, path: Path, fieldnames: list[str], resume: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = path.exists()
        mode = "a" if resume and file_exists else "w"
        self._handle = path.open(mode, newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._handle, fieldnames=fieldnames)
        if mode == "w" or self._handle.tell() == 0:
            self._writer.writeheader()
            self._handle.flush()

    def writerow(self, row: dict[str, Any]) -> None:
        self._writer.writerow(row)
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


def _blank_summary_counts() -> dict[str, int]:
    return {
        "all_entities": 0,
        "chapters": 0,
        "blocks": 0,
        "three_character_categories": 0,
        "terminal_three_character_categories": 0,
        "dotted_terminal_codes": 0,
        "terminal_codes_total": 0,
    }


def _increment_summary_counts(summary_counts: dict[str, int], entity_row: dict[str, Any]) -> None:
    summary_counts["all_entities"] += 1
    if entity_row["semantic_level"] == "chapter":
        summary_counts["chapters"] += 1
    if entity_row["semantic_level"] == "block":
        summary_counts["blocks"] += 1
    if entity_row["is_three_character_code"] == "true":
        summary_counts["three_character_categories"] += 1
    if (
        entity_row["is_three_character_code"] == "true"
        and entity_row["is_terminal_code"] == "true"
    ):
        summary_counts["terminal_three_character_categories"] += 1
    if "." in entity_row["code"] and entity_row["is_terminal_code"] == "true":
        summary_counts["dotted_terminal_codes"] += 1
    if entity_row["is_terminal_code"] == "true":
        summary_counts["terminal_codes_total"] += 1


def _prepare_output_dir(output_dir: Path, resume: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if resume:
        return

    for filename in ("entities.csv", "lineage.csv", "edges.csv", "summary.csv"):
        path = output_dir / filename
        if path.exists():
            path.unlink()


def _build_rows_for_entity(
    url: str,
    entities: dict[str, dict[str, Any]],
    parent_by_url: dict[str, str],
    sibling_index_by_url: dict[str, int],
    lineage_cache: dict[str, list[str]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    record = entities[url]
    parent_url = parent_by_url.get(url, "")
    parent_record = entities.get(parent_url)
    semantic_level = _semantic_level(record, parent_url)
    lineage = _lineage_urls(url, parent_by_url, lineage_cache)
    lineage_records = [entities[item_url] for item_url in lineage]

    chapter_record = next(
        (item for item in lineage_records if item["class_kind"] == "chapter"),
        None,
    )
    block_record = next(
        (item for item in lineage_records if item["class_kind"] == "block"),
        None,
    )
    three_character_record = next(
        (item for item in lineage_records if _is_three_character_code(item["code"])),
        None,
    )

    is_leaf = not record["child_urls"]
    is_three_character = _is_three_character_code(record["code"])
    is_terminal_code = record["class_kind"] == "category" and is_leaf

    entity_row = {
        "uri": record["uri"],
        "code": record["code"],
        "title": record["title"],
        "class_kind": record["class_kind"],
        "semantic_level": semantic_level,
        "depth": len(lineage) - 1,
        "parent_uri": parent_url,
        "parent_code": parent_record["code"] if parent_record else "",
        "parent_title": parent_record["title"] if parent_record else "",
        "child_count": len(record["child_urls"]),
        "is_leaf": str(is_leaf).lower(),
        "is_three_character_code": str(is_three_character).lower(),
        "is_terminal_code": str(is_terminal_code).lower(),
        "browser_url": record["browser_url"],
    }
    lineage_row = {
        "uri": record["uri"],
        "code": record["code"],
        "title": record["title"],
        "class_kind": record["class_kind"],
        "semantic_level": semantic_level,
        "depth": len(lineage) - 1,
        "is_leaf": str(is_leaf).lower(),
        "is_three_character_code": str(is_three_character).lower(),
        "is_terminal_code": str(is_terminal_code).lower(),
        "chapter_code": chapter_record["code"] if chapter_record else "",
        "chapter_title": chapter_record["title"] if chapter_record else "",
        "block_code": block_record["code"] if block_record else "",
        "block_title": block_record["title"] if block_record else "",
        "three_character_code": three_character_record["code"] if three_character_record else "",
        "three_character_title": (
            three_character_record["title"] if three_character_record else ""
        ),
        "final_code": record["code"] if is_terminal_code else "",
        "final_title": record["title"] if is_terminal_code else "",
    }
    edge_row = None
    if parent_record is not None:
        edge_row = {
            "parent_uri": parent_record["uri"],
            "parent_code": parent_record["code"],
            "parent_title": parent_record["title"],
            "child_index": sibling_index_by_url.get(url, 0),
            "child_uri": record["uri"],
            "child_code": record["code"],
            "child_title": record["title"],
        }
    return entity_row, lineage_row, edge_row


def _load_resume_state(
    output_dir: Path,
    release_url: str,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, str],
    dict[str, int],
    dict[str, str],
    dict[str, int],
]:
    entities_path = output_dir / "entities.csv"
    edges_path = output_dir / "edges.csv"

    if not entities_path.exists():
        return {}, {release_url: ""}, {release_url: 0}, {release_url: ""}, _blank_summary_counts()

    entities: dict[str, dict[str, Any]] = {}
    parent_by_url: dict[str, str] = {}
    sibling_index_by_url: dict[str, int] = {release_url: 0}
    pending: dict[str, str] = {}
    summary_counts = _blank_summary_counts()

    with entities_path.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            entities[row["uri"]] = {
                "uri": row["uri"],
                "code": row["code"],
                "title": row["title"],
                "class_kind": row["class_kind"],
                "browser_url": row.get("browser_url", ""),
                "child_urls": [],
            }
            parent_by_url[row["uri"]] = row["parent_uri"]
            _increment_summary_counts(summary_counts, row)

    children_by_parent: dict[str, list[tuple[int, str]]] = defaultdict(list)
    if edges_path.exists():
        with edges_path.open("r", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                child_index = int(row["child_index"] or 0)
                child_uri = row["child_uri"]
                parent_uri = row["parent_uri"]
                children_by_parent[parent_uri].append((child_index, child_uri))
                sibling_index_by_url[child_uri] = child_index
                parent_by_url[child_uri] = parent_uri

    for parent_uri, children in children_by_parent.items():
        if parent_uri in entities:
            entities[parent_uri]["child_urls"] = [
                child_uri for _, child_uri in sorted(children, key=lambda item: item[0])
            ]

    for parent_uri, children in children_by_parent.items():
        for _, child_uri in sorted(children, key=lambda item: item[0]):
            if child_uri not in entities:
                pending[child_uri] = parent_uri

    if release_url not in entities:
        pending.setdefault(release_url, "")
        parent_by_url.setdefault(release_url, "")

    print(
        f"resume: loaded {len(entities)} entity row(s) and {sum(len(v) for v in children_by_parent.values())} edge row(s)",
        flush=True,
    )
    return entities, parent_by_url, sibling_index_by_url, pending, summary_counts


def _write_summary_csv(output_dir: Path, summary_counts: dict[str, int]) -> None:
    summary_rows = [
        {"metric": metric, "count": count}
        for metric, count in summary_counts.items()
    ]
    _write_csv(output_dir / "summary.csv", SUMMARY_FIELDS, summary_rows)


def _stream_icd_hierarchy(
    release_url: str,
    headers: dict[str, str],
    workers: int,
    output_dir: Path,
    resume: bool,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, int], dict[str, int]]:
    _prepare_output_dir(output_dir, resume)
    if resume:
        entities, parent_by_url, sibling_index_by_url, pending, summary_counts = _load_resume_state(
            output_dir=output_dir,
            release_url=release_url,
        )
    else:
        entities = {}
        parent_by_url = {release_url: ""}
        sibling_index_by_url = {release_url: 0}
        pending = {release_url: ""}
        summary_counts = _blank_summary_counts()

    entity_writer = _CsvAppender(output_dir / "entities.csv", ENTITY_FIELDS, resume=resume)
    lineage_writer = _CsvAppender(output_dir / "lineage.csv", LINEAGE_FIELDS, resume=resume)
    edge_writer = _CsvAppender(output_dir / "edges.csv", EDGE_FIELDS, resume=resume)
    lineage_cache: dict[str, list[str]] = {}
    wave = 0

    try:
        while pending:
            wave += 1
            batch = pending
            pending = {}
            print(f"wave {wave}: fetching {len(batch)} node(s)", flush=True)

            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {
                    executor.submit(_fetch_entity, url, headers): url
                    for url in batch
                    if url not in entities
                }

                for future in as_completed(future_map):
                    url = future_map[future]
                    entity = future.result()
                    entities[url] = entity
                    entity_row, lineage_row, edge_row = _build_rows_for_entity(
                        url=url,
                        entities=entities,
                        parent_by_url=parent_by_url,
                        sibling_index_by_url=sibling_index_by_url,
                        lineage_cache=lineage_cache,
                    )
                    entity_writer.writerow(entity_row)
                    lineage_writer.writerow(lineage_row)
                    if edge_row is not None:
                        edge_writer.writerow(edge_row)
                    _increment_summary_counts(summary_counts, entity_row)
                    _log_entity_progress(entity, summary_counts["all_entities"])

            for url in batch:
                entity = entities[url]
                for child_index, child_url in enumerate(entity["child_urls"]):
                    if child_url in parent_by_url:
                        continue
                    parent_by_url[child_url] = url
                    sibling_index_by_url[child_url] = child_index
                    if child_url not in entities:
                        pending[child_url] = url

            print(f"wave {wave}: total fetched so far {len(entities)} node(s)", flush=True)
            _write_summary_csv(output_dir, summary_counts)
    finally:
        entity_writer.close()
        lineage_writer.close()
        edge_writer.close()

    return entities, parent_by_url, sibling_index_by_url, summary_counts


def _load_xml_entities(
    xml_path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, int], str]:
    root = ET.parse(xml_path).getroot()
    title_node = root.find("Title")
    release_title = " ".join("".join(title_node.itertext()).split()) if title_node is not None else ""
    release_uri = _build_xml_uri("")

    entities: dict[str, dict[str, Any]] = {
        release_uri: {
            "uri": release_uri,
            "code": "",
            "title": release_title,
            "class_kind": "",
            "browser_url": "http://apps.who.int/classifications/icd10/browse/2019/en",
            "child_urls": [],
        }
    }
    parent_by_url: dict[str, str] = {release_uri: ""}
    sibling_index_by_url: dict[str, int] = {release_uri: 0}

    class_nodes = root.findall("Class")
    by_code: dict[str, ET.Element] = {}
    child_codes_by_parent: dict[str, list[str]] = defaultdict(list)

    for node in class_nodes:
        code = node.attrib["code"]
        by_code[code] = node
        uri = _build_xml_uri(code)
        entities[uri] = {
            "uri": uri,
            "code": code,
            "title": _extract_xml_preferred_title(node),
            "class_kind": node.attrib.get("kind", ""),
            "browser_url": f"http://apps.who.int/classifications/icd10/browse/2019/en#/{code}",
            "child_urls": [],
        }

    top_level_sort = ""
    for meta in root.findall("Meta"):
        if meta.attrib.get("name") == "TopLevelSort":
            top_level_sort = meta.attrib.get("value", "")
            break

    top_level_codes = [code for code in top_level_sort.split() if code in by_code]
    entities[release_uri]["child_urls"] = [_build_xml_uri(code) for code in top_level_codes]
    for idx, code in enumerate(top_level_codes):
        child_uri = _build_xml_uri(code)
        parent_by_url[child_uri] = release_uri
        sibling_index_by_url[child_uri] = idx

    for node in class_nodes:
        code = node.attrib["code"]
        uri = _build_xml_uri(code)
        superclass = node.find("SuperClass")
        if superclass is not None:
            parent_code = superclass.attrib.get("code", "")
            parent_uri = _build_xml_uri(parent_code)
            parent_by_url[uri] = parent_uri
        elif code not in top_level_codes:
            parent_by_url.setdefault(uri, release_uri)

        for child_node in node.findall("SubClass"):
            child_code = child_node.attrib.get("code", "")
            if child_code in by_code:
                child_codes_by_parent[code].append(child_code)

    for parent_code, child_codes in child_codes_by_parent.items():
        parent_uri = _build_xml_uri(parent_code)
        child_uris = [_build_xml_uri(child_code) for child_code in child_codes]
        if parent_uri in entities:
            entities[parent_uri]["child_urls"] = child_uris
        for idx, child_uri in enumerate(child_uris):
            parent_by_url[child_uri] = parent_uri
            sibling_index_by_url[child_uri] = idx

    return entities, parent_by_url, sibling_index_by_url, release_uri


def _stream_xml_hierarchy(
    xml_path: Path,
    output_dir: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    entities, parent_by_url, sibling_index_by_url, release_uri = _load_xml_entities(xml_path)
    _prepare_output_dir(output_dir, resume=False)

    entity_writer = _CsvAppender(output_dir / "entities.csv", ENTITY_FIELDS, resume=False)
    lineage_writer = _CsvAppender(output_dir / "lineage.csv", LINEAGE_FIELDS, resume=False)
    edge_writer = _CsvAppender(output_dir / "edges.csv", EDGE_FIELDS, resume=False)
    summary_counts = _blank_summary_counts()
    lineage_cache: dict[str, list[str]] = {}
    tree_order_cache: dict[str, tuple[int, ...]] = {}

    ordered_urls = sorted(
        entities,
        key=lambda url: (
            _tree_order_key(url, parent_by_url, sibling_index_by_url, tree_order_cache),
            entities[url]["code"],
        ),
    )

    try:
        for url in ordered_urls:
            entity_row, lineage_row, edge_row = _build_rows_for_entity(
                url=url,
                entities=entities,
                parent_by_url=parent_by_url,
                sibling_index_by_url=sibling_index_by_url,
                lineage_cache=lineage_cache,
            )
            entity_writer.writerow(entity_row)
            lineage_writer.writerow(lineage_row)
            if edge_row is not None:
                edge_writer.writerow(edge_row)
            _increment_summary_counts(summary_counts, entity_row)
            _log_entity_progress(entities[url], summary_counts["all_entities"])
    finally:
        entity_writer.close()
        lineage_writer.close()
        edge_writer.close()

    _write_summary_csv(output_dir, summary_counts)
    print(f"xml: streamed {len(entities)} node(s) from {xml_path}", flush=True)
    if release_uri not in entities:
        raise RuntimeError("XML release root missing from entity map.")
    return entities, summary_counts


def _semantic_level(record: dict[str, Any], parent_uri: str) -> str:
    if not parent_uri:
        return "release"
    if record["class_kind"] == "chapter":
        return "chapter"
    if record["class_kind"] == "block":
        return "block"
    if _is_three_character_code(record["code"]):
        return "three_character"
    return "final_code"


def _lineage_urls(
    url: str,
    parent_by_url: dict[str, str],
    cache: dict[str, list[str]],
) -> list[str]:
    if url in cache:
        return cache[url]

    parent_url = parent_by_url.get(url, "")
    if not parent_url:
        lineage = [url]
    else:
        lineage = [*_lineage_urls(parent_url, parent_by_url, cache), url]
    cache[url] = lineage
    return lineage


def _tree_order_key(
    url: str,
    parent_by_url: dict[str, str],
    sibling_index_by_url: dict[str, int],
    cache: dict[str, tuple[int, ...]],
) -> tuple[int, ...]:
    if url in cache:
        return cache[url]

    parent_url = parent_by_url.get(url, "")
    current_index = sibling_index_by_url.get(url, 0)
    if not parent_url:
        key = tuple()
    else:
        key = (*_tree_order_key(parent_url, parent_by_url, sibling_index_by_url, cache), current_index)
    cache[url] = key
    return key


def _walk_icd_hierarchy(
    release_url: str,
    headers: dict[str, str],
    workers: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, int]]:
    entities: dict[str, dict[str, Any]] = {}
    parent_by_url: dict[str, str] = {release_url: ""}
    sibling_index_by_url: dict[str, int] = {release_url: 0}
    pending: dict[str, str] = {release_url: ""}
    wave = 0

    while pending:
        wave += 1
        batch = pending
        pending = {}
        print(f"wave {wave}: fetching {len(batch)} node(s)", flush=True)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(_fetch_entity, url, headers): (url, parent_url)
                for url, parent_url in batch.items()
                if url not in entities
            }

            for future in as_completed(future_map):
                url, _ = future_map[future]
                entity = future.result()
                entities[url] = entity
                _log_entity_progress(entity, len(entities))

        for url in batch:
            entity = entities[url]
            for child_index, child_url in enumerate(entity["child_urls"]):
                if child_url in parent_by_url:
                    continue
                parent_by_url[child_url] = url
                sibling_index_by_url[child_url] = child_index
                if child_url not in entities:
                    pending[child_url] = url

        print(f"wave {wave}: total fetched so far {len(entities)} node(s)", flush=True)

    return entities, parent_by_url, sibling_index_by_url


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _build_outputs(
    entities: dict[str, dict[str, Any]],
    parent_by_url: dict[str, str],
    sibling_index_by_url: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    lineage_cache: dict[str, list[str]] = {}
    tree_order_cache: dict[str, tuple[int, ...]] = {}

    ordered_urls = sorted(
        entities,
        key=lambda url: (
            _tree_order_key(url, parent_by_url, sibling_index_by_url, tree_order_cache),
            entities[url]["code"],
        ),
    )

    entity_rows: list[dict[str, Any]] = []
    lineage_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []

    for url in ordered_urls:
        record = entities[url]
        parent_url = parent_by_url.get(url, "")
        parent_record = entities.get(parent_url)
        semantic_level = _semantic_level(record, parent_url)
        lineage = _lineage_urls(url, parent_by_url, lineage_cache)
        lineage_records = [entities[item_url] for item_url in lineage]

        chapter_record = next(
            (item for item in lineage_records if item["class_kind"] == "chapter"),
            None,
        )
        block_record = next(
            (item for item in lineage_records if item["class_kind"] == "block"),
            None,
        )
        three_character_record = next(
            (item for item in lineage_records if _is_three_character_code(item["code"])),
            None,
        )

        is_leaf = not record["child_urls"]
        is_three_character = _is_three_character_code(record["code"])
        is_terminal_code = record["class_kind"] == "category" and is_leaf

        entity_rows.append(
            {
                "uri": record["uri"],
                "code": record["code"],
                "title": record["title"],
                "class_kind": record["class_kind"],
                "semantic_level": semantic_level,
                "depth": len(lineage) - 1,
                "parent_uri": parent_url,
                "parent_code": parent_record["code"] if parent_record else "",
                "parent_title": parent_record["title"] if parent_record else "",
                "child_count": len(record["child_urls"]),
                "is_leaf": str(is_leaf).lower(),
                "is_three_character_code": str(is_three_character).lower(),
                "is_terminal_code": str(is_terminal_code).lower(),
                "browser_url": record["browser_url"],
            }
        )

        lineage_rows.append(
            {
                "uri": record["uri"],
                "code": record["code"],
                "title": record["title"],
                "class_kind": record["class_kind"],
                "semantic_level": semantic_level,
                "depth": len(lineage) - 1,
                "is_leaf": str(is_leaf).lower(),
                "is_three_character_code": str(is_three_character).lower(),
                "is_terminal_code": str(is_terminal_code).lower(),
                "chapter_code": chapter_record["code"] if chapter_record else "",
                "chapter_title": chapter_record["title"] if chapter_record else "",
                "block_code": block_record["code"] if block_record else "",
                "block_title": block_record["title"] if block_record else "",
                "three_character_code": (
                    three_character_record["code"] if three_character_record else ""
                ),
                "three_character_title": (
                    three_character_record["title"] if three_character_record else ""
                ),
                "final_code": record["code"] if is_terminal_code else "",
                "final_title": record["title"] if is_terminal_code else "",
            }
        )

        for child_index, child_url in enumerate(record["child_urls"]):
            child_record = entities[child_url]
            edge_rows.append(
                {
                    "parent_uri": record["uri"],
                    "parent_code": record["code"],
                    "parent_title": record["title"],
                    "child_index": child_index,
                    "child_uri": child_record["uri"],
                    "child_code": child_record["code"],
                    "child_title": child_record["title"],
                }
            )

    level_counts = {
        "all_entities": len(entity_rows),
        "chapters": sum(row["semantic_level"] == "chapter" for row in entity_rows),
        "blocks": sum(row["semantic_level"] == "block" for row in entity_rows),
        "three_character_categories": sum(
            row["is_three_character_code"] == "true" for row in entity_rows
        ),
        "terminal_three_character_categories": sum(
            row["is_three_character_code"] == "true" and row["is_terminal_code"] == "true"
            for row in entity_rows
        ),
        "dotted_terminal_codes": sum(
            "." in row["code"] and row["is_terminal_code"] == "true" for row in entity_rows
        ),
        "terminal_codes_total": sum(row["is_terminal_code"] == "true" for row in entity_rows),
    }
    summary_rows = [{"metric": metric, "count": count} for metric, count in level_counts.items()]
    return entity_rows, lineage_rows, edge_rows, summary_rows


def main() -> int:
    load_dotenv()
    args = _parse_args()

    client_id = _require_env("ICD_API_ClientId")
    client_secret = _require_env("ICD_API_ClientSecret")
    headers = {
        "Authorization": f"Bearer {_fetch_access_token(client_id, client_secret)}",
        "API-Version": "v2",
        "Accept-Language": args.language,
    }

    output_dir = Path(args.output_dir)
    entities, _, _, summary_counts = _stream_icd_hierarchy(
        release_url=args.release_url,
        headers=headers,
        workers=max(1, args.workers),
        output_dir=output_dir,
        resume=args.resume,
    )
    print(f"Streamed {len(entities)} entities to {output_dir / 'entities.csv'}", flush=True)
    print(f"Streamed lineage rows to {output_dir / 'lineage.csv'}", flush=True)
    print(f"Streamed edges to {output_dir / 'edges.csv'}", flush=True)
    for metric, count in summary_counts.items():
        print(f"{metric}: {count}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
