"""Quality check for browser-local ICD semantic search (digitva-zpe).

Embeds every searchable ICD-10 and ICD-11 title with the same quantized ONNX
model the browser would run (transformers.js / onnxruntime-web), then measures
retrieval quality for 30 clinical phrases a VA coder might type. English only,
per the owner's constraints; see docs/planning/icd-semantic-search.md.

Run on a dev machine (not the 4GB server):

    uv run --with transformers,onnxruntime,numpy,huggingface_hub \
        python tooling/icd-semantic-search/quality_check.py \
        [--model Xenova/all-MiniLM-L6-v2] [--topk 10]

Downloads the model from Hugging Face on first run. Exits non-zero when an
expected-code spec matches nothing in its corpus (a broken expectation, not a
model failure).
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ICD10_CSV = REPO_ROOT / (
    "docs/icd-causegrp-mappings/migration-artifacts/"
    "icd10-2019-base-2026-04-27/icd10_2019_hierarchy.csv"
)
ICD11_CSV = REPO_ROOT / "resource/icd11_mms_2026_01_hierarchy.csv"

# The searchable corpus mirrors what the coding-search endpoints serve:
# ICD-10 category/modifiedcategory rows; ICD-11 categories outside chapter X
# (the generator scope -- chapter X extension codes are never codable).
def load_icd10() -> list[tuple[str, str]]:
    with ICD10_CSV.open(newline="", encoding="utf-8") as handle:
        return [
            (row["code"], row["title"])
            for row in csv.DictReader(handle)
            if row["node_type"] in ("category", "modifiedcategory") and row["code"]
        ]


def load_icd11() -> list[tuple[str, str]]:
    with ICD11_CSV.open(newline="", encoding="utf-8") as handle:
        return [
            (row["code"], row["title"])
            for row in csv.DictReader(handle)
            if row["class_kind"] == "category"
            and row["code"]
            and row["chapter_no"] != "X"
        ]


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


def expected_codes(rows: list[tuple[str, str]], spec: dict) -> set[str]:
    substrs = [s.lower() for s in spec.get("substr", ())]
    return {
        code
        for code, title in rows
        if code in spec.get("codes", ())
        or any(s in title.lower() for s in substrs)
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="Xenova/all-MiniLM-L6-v2")
    parser.add_argument("--topk", type=int, default=10)
    parser.add_argument(
        "--query-prefix",
        default="",
        help="text prepended to every query (BGE models want "
        "'Represent this sentence for searching relevant passages: ')",
    )
    args = parser.parse_args()
    import numpy as np
    import onnxruntime as ort
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    corpora = {"icd10": load_icd10(), "icd11": load_icd11()}
    for label, rows in corpora.items():
        print(f"{label}: {len(rows)} titles")

    model_dir = snapshot_download(
        args.model, allow_patterns=["onnx/model_quantized.onnx", "tokenizer*", "*.json"]
    )
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    session = ort.InferenceSession(
        str(Path(model_dir) / "onnx/model_quantized.onnx"),
        providers=["CPUExecutionProvider"],
    )
    input_names = {i.name for i in session.get_inputs()}

    def embed(texts: list[str], batch_size: int = 256) -> np.ndarray:
        chunks = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            encoded = tokenizer(
                batch, padding=True, truncation=True, max_length=128, return_tensors="np"
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
        return vectors / np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9, None)

    embeddings, codes_by_label = {}, {}
    for label, rows in corpora.items():
        embeddings[label] = embed([title for _, title in rows])
        codes_by_label[label] = [code for code, _ in rows]

    queries = embed([args.query_prefix + phrase for phrase, _, _ in PHRASES])

    failures = 0
    print(f"\nmodel={args.model}  metric=cosine  corpus order=embedding rank")
    print(f"{'phrase':58} {'icd10':>12} {'icd11':>12}")
    hits = {label: {"5": 0, "10": 0, "rr": 0.0, "n": 0} for label in corpora}
    for (phrase, spec10, spec11), query in zip(PHRASES, queries):
        cells = []
        for label, spec in (("icd10", spec10), ("icd11", spec11)):
            if not spec:
                cells.append("       --    ")
                continue
            wanted = expected_codes(corpora[label], spec)
            if not wanted:
                print(f"BROKEN EXPECTATION: {label} spec {spec!r} matches nothing", file=sys.stderr)
                failures += 1
                cells.append("       ??    ")
                continue
            scores = embeddings[label] @ query
            order = sorted(range(len(scores)), key=lambda i: -scores[i])
            rank = next(
                (position + 1 for position, i in enumerate(order)
                 if codes_by_label[label][i] in wanted),
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
