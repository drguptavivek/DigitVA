"""Resolve the synthetic condition list to ICD-11 2026-01 codes and URIs, once.

Asks the local official WHO container (whoicd/icd-api:2.6.0 on 127.0.0.1:8382)
for each condition text and keeps the first result whose title matches. The
output, conditions.json, is committed, so certificate generation never needs
the container again and every run uses the same codes.

usage: python3 scripts/icd11-parity/resolve_conditions.py
"""
import json
import pathlib
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).parent
BASE = "http://127.0.0.1:8382/icd/release/11/2026-01/mms"
HEADERS = {"Accept": "application/json", "Accept-Language": "en", "API-Version": "v2"}

# (key, search text, age groups it may appear in). Natural, disease-only causes common in verbal autopsy.
CONDITIONS = [
    ("ami", "Acute myocardial infarction", "adult"),
    ("coronary", "Coronary atherosclerosis", "adult"),
    ("ihd", "Chronic ischaemic heart disease", "adult"),
    ("heart_failure", "Congestive heart failure", "adult"),
    ("hypertension", "Essential hypertension", "adult"),
    ("hhd", "Hypertensive heart disease", "adult"),
    ("ich", "Intracerebral haemorrhage", "adult"),
    ("ischaemic_stroke", "Cerebral ischaemic stroke", "adult"),
    ("t2dm", "Type 2 diabetes mellitus", "adult"),
    ("ckd", "Chronic kidney disease", "adult"),
    ("copd", "Chronic obstructive pulmonary disease", "adult"),
    ("asthma", "Asthma", "adult child"),
    ("pneumonia", "Pneumonia, organism unspecified", "adult child"),
    ("sepsis", "Sepsis without septic shock", "adult child"),
    ("resp_tb", "Respiratory tuberculosis, without mention of bacteriological or histological confirmation", "adult"),
    ("hiv", "HIV disease", "adult"),
    ("cirrhosis", "Alcoholic cirrhosis", "adult"),
    ("hepatocellular", "Hepatocellular carcinoma", "adult"),
    ("lung_cancer", "lung cancer", "adult"),
    ("breast_cancer", "breast cancer", "adult"),
    ("cervix_cancer", "cervix cancer", "adult"),
    ("stomach_cancer", "stomach cancer", "adult"),
    ("anaemia", "Iron deficiency anaemia", "adult child"),
    ("malaria", "falciparum malaria", "adult child"),
    ("dengue", "Dengue", "adult child"),
    ("typhoid", "Typhoid fever", "adult child"),
    ("gastroenteritis", "Gastroenteritis or colitis without specification of infectious agent", "adult child"),
    ("dehydration", "Dehydration", "adult child"),
    ("measles", "Measles without complication", "child"),
    ("meningitis", "Bacterial meningitis", "adult child"),
    ("preterm", "Preterm newborn", "neonate"),
    ("rds", "Respiratory distress syndrome of newborn", "neonate"),
    ("birth_asphyxia", "Birth asphyxia", "neonate"),
    ("neonatal_sepsis", "sepsis of newborn", "neonate"),
    ("lbw", "Low birth weight", "neonate"),
    ("pph", "Postpartum haemorrhage", "maternal"),
    ("uterine_atony", "Uterine atony", "maternal"),
    ("eclampsia", "Eclampsia", "maternal"),
    ("puerperal_sepsis", "Puerperal sepsis", "maternal"),
]


def search(text):
    url = f"{BASE}/search?" + urllib.parse.urlencode(
        {"q": text, "flatResults": "true", "highlightingEnabled": "false", "useFlexisearch": "false"}
    )
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=20) as reply:
        return json.load(reply)["destinationEntities"]


def main():
    resolved = []
    for key, text, groups in CONDITIONS:
        # Plain stem codes only: no postcoordination (&) or multiple-parent (/) codes.
        hits = [h for h in search(text) if h.get("theCode") and "&" not in h["theCode"] and "/" not in h["theCode"]]
        if not hits:
            raise SystemExit(f"no ICD-11 code found for {key!r}: {text!r}")
        exact = [h for h in hits if h["title"].lower() == text.lower()]
        hit = (exact or hits)[0]
        resolved.append({"key": key, "text": text, "groups": groups.split(), "code": hit["theCode"],
                         "uri": hit["id"], "title": hit["title"]})
        print(f"{key:18} {hit['theCode']:12} {hit['title']}")
    (HERE / "conditions.json").write_text(json.dumps(resolved, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
