"""Quality check for browser-local ICD semantic search (digitva-zpe).

Embeds every searchable ICD-10 and ICD-11 title with the same quantized ONNX
model the browser would run (transformers.js / onnxruntime-web), then measures
retrieval quality for 30 clinical phrases a VA coder might type, in modes that
isolate each candidate improvement:

- lexical          -- whole-query substring, mirroring today's ILIKE endpoints
- lexical-tokens   -- per-token overlap, the cheapest no-ML server-side upgrade
- dense            -- embedding cosine only
- hybrid           -- reciprocal-rank fusion of dense + lexical-tokens
- (--context)      -- documents embedded as title + block/chapter title

English only, per the owner's constraints; see
docs/planning/icd-semantic-search.md for results and decisions.

Run on a dev machine (not the 4GB server):

    uv run --isolated --no-project --with transformers,onnxruntime,numpy,huggingface_hub \
        python tooling/icd-semantic-search/quality_check.py \
        [--mode dense|lexical|lexical-tokens|hybrid] [--context] \
        [--model Xenova/bge-small-en-v1.5] \
        [--query-prefix "Represent this sentence for searching relevant passages: "]

Downloads the model from Hugging Face on first run (only for dense/hybrid
modes). Exits non-zero when an expected-code spec matches nothing in its
corpus (a broken expectation, not a model failure).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ICD10_CSV = REPO_ROOT / (
    "docs/icd-causegrp-mappings/migration-artifacts/"
    "icd10-2019-base-2026-04-27/icd10_2019_hierarchy.csv"
)
ICD11_CSV = REPO_ROOT / "resource/icd11_mms_2026_01_hierarchy.csv"
CAUSE_LIST_CSV = REPO_ROOT / "resource/who_2022_va_cause_list_icd10_icd11.csv"
CAUSE_DEFINITIONS_JSON = REPO_ROOT / "resource/va_cause_definitions_who_2022.json"

# The searchable corpus mirrors what the coding-search endpoints serve:
# ICD-10 category/modifiedcategory rows; ICD-11 categories outside chapter X
# (the generator scope -- chapter X extension codes are never codable).
def load_icd10() -> list[tuple[str, str, str]]:
    """(code, title, context) where context is "block. chapter" titles."""
    with ICD10_CSV.open(newline="", encoding="utf-8") as handle:
        return [
            (
                row["code"],
                row["title"],
                ". ".join(p for p in (row["block_title"], row["chapter_title"]) if p),
            )
            for row in csv.DictReader(handle)
            if row["node_type"] in ("category", "modifiedcategory") and row["code"]
        ]


def load_icd11() -> list[tuple[str, str, str]]:
    """(code, title, context); context is the outermost ancestor block/chapter."""
    with ICD11_CSV.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_uri = {row["linearization_uri"]: row for row in rows if row["linearization_uri"]}
    out: list[tuple[str, str, str]] = []
    for row in rows:
        if (
            row["class_kind"] != "category"
            or not row["code"]
            or row["chapter_no"] == "X"
        ):
            continue
        context = ""
        uri = row["parent_linearization_uri"]
        while uri in by_uri:
            parent = by_uri[uri]
            if parent["class_kind"] in ("block", "chapter"):
                context = parent["title"]
                break
            uri = parent["parent_linearization_uri"]
        out.append((row["code"], row["title"], context))
    return out

def load_causes() -> list[dict]:
    """The 63 VA causes with their ICD code ranges and WHO definitions."""
    definitions: dict[str, str] = {}
    with CAUSE_DEFINITIONS_JSON.open(encoding="utf-8") as handle:
        for item in json.load(handle):
            definitions[item["va_code"]] = " ".join(
                re.sub(r"<[^>]+>", " ", item.get("definition_html") or "").split()
            )
    with CAUSE_LIST_CSV.open(newline="", encoding="utf-8") as handle:
        return [
            {
                "va_code": row["va_code"],
                "va_title": row["va_title"],
                "definition": definitions.get(row["va_code"], ""),
                "icd10": (row["icd10_codes"] or "").upper(),
                "icd11": (row["icd11_codes"] or "").upper(),
            }
            for row in csv.DictReader(handle)
        ]


def cause_covers(cause: dict, label: str, code: str) -> bool:
    """True when the cause's ICD token list for `label` covers `code`.

    Tokens are single codes or `start-end` ranges; a single token also
    covers its descendants (`JB40` covers `JB40.0`). Outside chapter X the
    plain string order of codes is WHO's order (the generator relies on
    the same property).
    """
    for token in re.split(r"[;,\s]+", cause[label]):
        if not token or "(" in token or "." == token[:1]:
            continue
        head, sep, tail = token.partition("-")
        if sep and tail and head <= code <= tail:
            return True
        if not sep and (token == code or code.startswith(token + ".") or code.startswith(token)):
            return True
    return False




# (phrase, icd10 spec, icd11 spec); a spec is exact codes and/or
# case-insensitive title substrings, and must match at least one corpus row.
PHRASES: list[tuple[str, dict, dict]] = [
    ("fever with severe headache and stiff neck",
     {"substr": ["meningitis"]}, {"substr": ["meningitis"]}),
    ("profuse watery diarrhoea and vomiting with severe dehydration",
     {"codes": ["A09", "A00"]}, {"codes": ["1A00"], "substr": ["gastroenteritis"]}),
    ("heavy bleeding from the birth canal soon after the baby was born",
     {"codes": ["O72"], "substr": ["postpartum haemorrhage"]}, {"codes": ["JA43"]}),
    ("the baby was born dead before labour began",
     {"codes": ["P95"], "substr": ["stillbirth"]}, {"codes": ["KD3B.0"]}),
    ("died in a house fire with burns over most of the body",
     {"substr": ["burn"]}, {}),
    ("hit by a truck while walking along the road",
     {"codes": ["V02", "V03"]}, {"codes": ["PA00", "PA01"]}),
    ("bitten by a dog a month ago, now fear of water and muscle spasms",
     {"codes": ["A82"]}, {"codes": ["1C82"]}),
    ("chronic cough with weight loss and night sweats for several months",
     {"codes": ["A15", "A16"]}, {"codes": ["1B10"]}),
    ("sudden crushing chest pain, died within the hour",
     {"codes": ["I21"]}, {"codes": ["BA41"]}),
    ("old man with slowly increasing difficulty swallowing and weight loss",
     {"codes": ["C15"]}, {"codes": ["2B70"]}),
    ("fever and foul-smelling discharge a week after childbirth",
     {"codes": ["O85"]}, {"codes": ["JB40.0"]}),
    ("long history of alcohol intake, swollen belly and vomiting blood",
     {"codes": ["K70"]}, {"codes": ["DB93"]}),
    ("convulsions and high blood pressure at eight months of pregnancy",
     {"codes": ["O15"], "substr": ["eclampsia"]}, {"codes": ["JA25"]}),
    ("child with fever and rash spreading from the face, cough and runny nose",
     {"codes": ["B05"]}, {"codes": ["1F03"]}),
    ("tired and pale for months, abnormal white blood cells on the report",
     {"substr": ["leukaemia"]}, {"substr": ["leukaemia"]}),
    ("elderly man with bone pain and increasing difficulty passing urine",
     {"codes": ["C61"]}, {"codes": ["2C82"]}),
    ("snake bit him while he was working in the fields",
     {"codes": ["T63.0", "X20"]}, {}),
    ("found drowned in the village pond",
     {"codes": ["T75.1", "W65"], "substr": ["drowning"]},
     {"codes": ["NF08.1", "PA90"]}),
    ("known HIV infection with chronic diarrhoea and weight loss",
     {"codes": ["B24"]}, {"substr": ["immunodeficiency virus"]}),
    ("severe headache and blurred vision with very high blood pressure",
     {"codes": ["I10"]}, {"codes": ["BA00"]}),
    ("the baby did not cry at birth and remained blue and limp",
     {"codes": ["P21"]}, {"codes": ["KB21"]}),
    ("born two months early, died on the third day of life",
     {"codes": ["P07"], "substr": ["gestation"]},
     {"substr": ["preterm newborn", "extremely preterm"]}),
    ("chronic cough with foul-smelling sputum since a pneumonia years ago",
     {"codes": ["J47"]}, {"codes": ["CA24"]}),
    ("diabetic whose foot ulcer turned black and foul",
     {"codes": ["E11.5", "R02"], "substr": ["gangrene"]}, {}),
    ("swelling of face and difficulty breathing minutes after a wasp sting",
     {"codes": ["T78.2"], "substr": ["anaphylact"]}, {"codes": ["4A84"]}),
    ("found dead in the field the morning after a lightning storm",
     {"codes": ["X33", "T75.0"]}, {"codes": ["NF08.0", "PJ00"]}),
    ("severe abdominal pain with a rigid belly, died after surgery",
     {"codes": ["K65"], "substr": ["peritonitis"]}, {"substr": ["peritonitis"]}),
    ("severe anaemia throughout pregnancy, heart failure at term",
     {"codes": ["O99.0"]}, {"codes": ["JB64.0"]}),
    ("yellow eyes, distended abdomen and black stools for months",
     {"codes": ["K74"], "substr": ["cirrhosis"]}, {"codes": ["DB93"]}),
    ("swollen face, passing very little urine, increasingly breathless",
     {"codes": ["N17", "N18"], "substr": ["renal failure"]},
     {"codes": ["GB60"], "substr": ["kidney failure"]}),
]


def expected_codes(rows: list[tuple[str, str, str]], spec: dict) -> set[str]:
    substrs = [s.lower() for s in spec.get("substr", ())]
    return {
        code
        for code, title, _context in rows
        if code in spec.get("codes", ())
        or any(s in title.lower() for s in substrs)
    }


def substring_order(rows: list[tuple[str, str, str]], phrase: str) -> list[int]:
    """Today's endpoint behaviour: whole normalized query as a substring."""
    query = phrase.lower().strip()
    return [
        index
        for index, (code, title, _context) in enumerate(rows)
        if query in f"{code} {title}".lower()
    ]


def token_order(rows: list[tuple[str, str, str]], phrase: str) -> list[int]:
    """Cheapest no-ML upgrade: per-token overlap on code+title."""
    tokens = [t for t in re.split(r"[^a-z0-9]+", phrase.lower()) if len(t) > 2]
    if not tokens:
        return []
    scored = []
    for index, (code, title, _context) in enumerate(rows):
        hay = f"{code} {title}".lower()
        found = sum(1 for token in tokens if token in hay)
        if found:
            scored.append((found / len(tokens), -index, index))
    scored.sort(reverse=True)
    return [index for _s, _i, index in scored]


def rrf(orders: list[list[int]], k: int = 60, depth: int = 300) -> list[int]:
    fused: dict[int, float] = {}
    for order in orders:
        for position, index in enumerate(order[:depth], start=1):
            fused[index] = fused.get(index, 0.0) + 1.0 / (k + position)
    return sorted(fused, key=lambda index: -fused[index])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="Xenova/all-MiniLM-L6-v2")
    parser.add_argument("--topk", type=int, default=10)
    parser.add_argument(
        "--mode",
        default="dense",
        choices=["lexical", "lexical-tokens", "dense", "hybrid", "causes"],
    )
    parser.add_argument(
        "--context",
        action="store_true",
        help="embed 'title. block. chapter' instead of the bare title",
    )
    parser.add_argument(
        "--cause-doc",
        default="full",
        choices=["title", "full"],
        help="causes mode: embed the VA cause title alone or with its WHO definition",
    )
    parser.add_argument(
        "--query-prefix",
        default="",
        help="text prepended to every query (BGE models want "
        "'Represent this sentence for searching relevant passages: ')",
    )
    args = parser.parse_args()

    corpora = {"icd10": load_icd10(), "icd11": load_icd11()}
    for label, rows in corpora.items():
        print(f"{label}: {len(rows)} titles")

    embeddings: dict[str, object] = {}
    queries: list = [None] * len(PHRASES)
    causes = load_causes() if args.mode == "causes" else []
    if args.mode in ("dense", "hybrid", "causes"):
        import numpy as np
        import onnxruntime as ort
        from huggingface_hub import snapshot_download
        from transformers import AutoTokenizer

        model_dir = snapshot_download(
            args.model,
            allow_patterns=["onnx/model_quantized.onnx", "tokenizer*", "*.json"],
        )
        tokenizer = AutoTokenizer.from_pretrained(model_dir)
        session = ort.InferenceSession(
            str(Path(model_dir) / "onnx/model_quantized.onnx"),
            providers=["CPUExecutionProvider"],
        )
        input_names = {i.name for i in session.get_inputs()}

        def embed(texts: list[str], batch_size: int = 256):
            chunks = []
            for start in range(0, len(texts), batch_size):
                batch = texts[start : start + batch_size]
                encoded = tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=128,
                    return_tensors="np",
                )
                feed = {
                    name: encoded[name]
                    for name in input_names
                    if name in ("input_ids", "attention_mask", "token_type_ids")
                }
                hidden = session.run(None, feed)[0]
                mask = np.asarray(encoded["attention_mask"])[..., None]
                summed = (hidden * mask).sum(axis=1)
                counts = np.clip(mask.sum(axis=1), 1e-9, None)
                chunks.append(summed / counts)
            vectors = np.concatenate(chunks)
            return vectors / np.clip(
                np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9, None
            )

        if args.mode == "causes":
            if args.cause_doc == "full":
                docs = [
                    f"{c['va_title']}. {c['definition']}" if c["definition"] else c["va_title"]
                    for c in causes
                ]
            else:
                docs = [c["va_title"] for c in causes]
            embeddings["causes"] = embed(docs)
        else:
            for label, rows in corpora.items():
                if args.context:
                    docs = [
                        f"{title}. {context}" if context else title
                        for _code, title, context in rows
                    ]
                else:
                    docs = [title for _code, title, _context in rows]
                embeddings[label] = embed(docs)
        queries = embed([args.query_prefix + phrase for phrase, _, _ in PHRASES])

    failures = 0
    print(
        f"\nmode={args.mode}  "
        f"model={args.model if args.mode in ('dense', 'hybrid', 'causes') else '-'}  "
        f"context={args.context}  prefix={bool(args.query_prefix)}"
        + (f"  cause_doc={args.cause_doc}" if args.mode == "causes" else "")
    )
    print(f"{'phrase':58} {'icd10':>12} {'icd11':>12}")
    hits = {label: {"5": 0, "10": 0, "rr": 0.0, "n": 0} for label in corpora}
    for (phrase, spec10, spec11), query in zip(PHRASES, queries):
        cells = []
        for label, spec in (("icd10", spec10), ("icd11", spec11)):
            rows = corpora[label]
            if not spec:
                cells.append("       --    ")
                continue
            wanted = expected_codes(rows, spec)
            if not wanted:
                print(
                    f"BROKEN EXPECTATION: {label} spec {spec!r} matches nothing",
                    file=sys.stderr,
                )
                failures += 1
                cells.append("       ??    ")
                continue
            if args.mode == "causes":
                scores = embeddings["causes"] @ query
                order = sorted(range(len(causes)), key=lambda i: -scores[i])
                rank = next(
                    (
                        position + 1
                        for position, index in enumerate(order)
                        if any(
                            cause_covers(causes[index], label, code)
                            for code in wanted
                        )
                    ),
                    None,
                )
                stat = hits[label]
                stat["n"] += 1
                if rank is not None:
                    stat["rr"] += 1.0 / rank
                    if rank <= 3:
                        stat["5"] += 1
                    if rank <= 5:
                        stat["10"] += 1
                cells.append(f"{('top' + str(rank)) if rank else 'miss':>12}")
                continue
            if args.mode == "lexical":
                orders = [substring_order(rows, phrase)]
            elif args.mode == "lexical-tokens":
                orders = [token_order(rows, phrase)]
            elif args.mode == "dense":
                scores = embeddings[label] @ query
                orders = [sorted(range(len(scores)), key=lambda i: -scores[i])]
            else:  # hybrid
                scores = embeddings[label] @ query
                orders = [
                    sorted(range(len(scores)), key=lambda i: -scores[i]),
                    token_order(rows, phrase),
                ]
            order = orders[0] if len(orders) == 1 else rrf(orders)
            rank = next(
                (
                    position + 1
                    for position, index in enumerate(order)
                    if rows[index][0] in wanted
                ),
                None,
            )
            stat = hits[label]
            stat["n"] += 1
            if rank is not None:
                stat["rr"] += 1.0 / rank
                if rank <= 5:
                    stat["5"] += 1
                if rank <= 10:
                    stat["10"] += 1
            cells.append(f"{('top' + str(rank)) if rank else 'miss':>12}")
        print(f"{phrase[:58]:58} {cells[0]} {cells[1]}")

    print("\nsummary")
    for label, stat in hits.items():
        n = stat["n"] or 1
        print(
            f"  {label}: hit@5 {stat['5']}/{stat['n']}  hit@10 {stat['10']}/{stat['n']}"
            f"  MRR {stat['rr'] / n:.2f}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
