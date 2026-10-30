"""Make datasets/api-sweep/calls.jsonl.gz: the reads the coding screen makes for every ICD-11 code of our datasets.

Asks the WHO container once (read-only GETs and searches, nothing is written) and records every request it makes, answered or not
(a 404 is a valid answer to compare). The phone engine and the container are then compared on exactly these requests (build_inputs.py,
section `sweep`). Every id in a request (entity ids, URIs) was discovered from the container on the date in the dataset README; it is
not guessed, so a new WHO release needs a new sweep.

Code universe: the codes of datasets/hash-synthetic-10k (conditions.json), of datasets/clinical-variants-10k (every Code in a certificate
chain) and of the golden corpora (scripts/icd11-golden/corpus: certificate codes, postcoordination stems and the parts of their built
expressions). For each code the reads that the picker's routes make (mobile/digitva-collect/src/workspace/dorisGuidance.ts,
dorisTerminology.ts), with the same caps:
  codeinfo (plain, flexiblemode, convertToTerminalCodes); entity of the stem (plain, include ancestor, include diagnosticCriteria) and
  the stem's residual children (`unspecified`, `other`); foundation_entity of the entity's `source` (plain, include ancestor);
  hierarchy: ancestors (parent[0], 12 at most), siblings, children (12 each), related maternal/perinatal foundation entities (12 each);
  related: the coded entity of each related foundation entity and its children (12 each); details: exclusion targets (12);
  postcoordination: every axis (12 at most) with its roots (12 each); postcoordination-options: the children of each axis's first
  expandable root (12); composed expressions: stem&X (extension values) then stem/value (any other value), the first value of each axis,
  a second value where the axis allows several, one expression with the first value of every axis, and codeinfo of each value;
  search: the title (when 2 to 80 characters) and its first 4 letters, with the picker's flags and limit 20; for each axis (SEARCH_AXES at
  most) the first root's title and its first 3 letters with subtreesFilter set to the axis roots.
Requests are deduplicated and sorted; the file is gzip -9n of one {"op", "args"} JSON line each.

usage: python3 scripts/icd11-parity/make_sweep.py [--check] [BASE_URL]     (default http://127.0.0.1:8382)
  --check regenerates into memory and exits 1 when datasets/api-sweep/calls.jsonl.gz would change (README.md is not compared).
"""
import collections
import datetime
import gzip
import hashlib
import json
import pathlib
import re
import subprocess
import sys

import run_container

HERE = pathlib.Path(__file__).parent
DATASET = HERE / "datasets" / "api-sweep"
GOLDEN_CORPUS = HERE.parent / "icd11-golden" / "corpus"
MAX_AXES = MAX_OPTIONS = MAX_PATH = MAX_EXCLUSIONS = 12  # dorisGuidance.ts
SEARCH_AXES = 3  # axes per stem that get a subtree search (the first ones; the rest share their flags)
LIMIT = 20  # dorisTerminology.ts ENGINE_LIMIT
FLAGS = {"includePostcoordination": True, "flatResults": True, "highlightingEnabled": True, "medicalCodingMode": True}
MMS = re.compile(r"^http://id\.who\.int/icd/release/11/2026-01/mms/(\d+)(?:/(unspecified|other))?$")
FOUNDATION = re.compile(r"^http://id\.who\.int/icd/entity/(\d+)$")
ROOT_URI = "http://id.who.int/icd/release/11/2026-01/mms"


def codes_of(node, found):
    """Every string under a `Code` key, anywhere in the JSON value (a JSON text is opened too)."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "Code" and isinstance(value, str):
                found.add(value)
            else:
                codes_of(value, found)
    elif isinstance(node, list):
        for item in node:
            codes_of(item, found)
    elif isinstance(node, str) and node.startswith("{"):
        try:
            codes_of(json.loads(node), found)
        except ValueError:
            pass


def universe():
    found = {row["code"] for row in json.loads((HERE / "conditions.json").read_text())}
    for line in gzip.decompress((HERE / "datasets/clinical-variants-10k/inputs_all.jsonl.gz").read_bytes()).decode().splitlines():
        codes_of(json.loads(line)["submission"], found)
    for line in gzip.decompress((HERE / "datasets/clinical-variants-10k/edge_inputs.jsonl.gz").read_bytes()).decode().splitlines():
        codes_of(json.loads(line)["submission"], found)
    for line in gzip.decompress((HERE / "datasets/hash-synthetic-10k/certificates.jsonl.gz").read_bytes()).decode().splitlines():
        codes_of(json.loads(line)["certificate"], found)
    for item in json.loads((GOLDEN_CORPUS / "doris.json").read_text())["items"]:
        codes_of(item["certificate"], found)
    for item in json.loads((GOLDEN_CORPUS / "postcoordination.json").read_text())["items"]:
        found.add(item["stem"])
        for built in item.get("built", []):
            found.update(re.split(r"[&/]", built["expression"]))
    return sorted(code for code in found if code)


def title_of(entity):
    value = entity.get("title")
    return value.get("@value", "") if isinstance(value, dict) else ""


class Sweep:
    """Asks the container once per distinct request and keeps the requests, answered or not."""

    def __init__(self, root):
        self.root, self.base = root, root + "/icd/release/11/2026-01"
        self.asked = {}  # canonical key -> (op, args)
        self.answers = {}  # canonical key -> parsed JSON body or None

    def call(self, op, **args):
        key = op + "\t" + json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if key not in self.answers:
            status, body, _ = run_container.call_op(self.root, self.base, op, args)
            self.asked[key] = (op, args)
            self.answers[key] = json.loads(body) if 200 <= status < 300 else None
        return self.answers[key]

    def entity(self, uri):
        """The entity a URI names (linearization, residual or foundation), or None when WHO has none or the URI is not one."""
        if not isinstance(uri, str):
            return None
        if found := MMS.fullmatch(uri):
            return self.call("entity", id=found[1], **({"residual": found[2]} if found[2] else {}))
        if found := FOUNDATION.fullmatch(uri):
            return self.call("foundation_entity", id=found[1])
        return None

    def search(self, text, subtrees=None):
        self.call("search", q=text + "%", **FLAGS, **({"subtreesFilter": ",".join(subtrees)} if subtrees else {}), limit=LIMIT)

    def search_title(self, title, subtrees=None, prefix=4):
        title = title.strip()
        if 2 <= len(title) <= 80:
            self.search(title, subtrees)
        if len(title) > prefix:
            self.search(title[:prefix].strip(), subtrees)

    def code(self, code):
        """All reads for one code."""
        info = self.call("codeinfo", code=code)
        self.call("codeinfo", code=code, flexiblemode=True)
        self.call("codeinfo", code=code, convertToTerminalCodes=True)
        stem_uri = info.get("stemId") if info else None
        entity = self.entity(stem_uri)
        if not entity:
            return
        found = MMS.fullmatch(stem_uri)
        ident, residual = found[1], ({"residual": found[2]} if found[2] else {})
        for include in ("ancestor", "diagnosticCriteria"):
            self.call("entity", id=ident, **residual, include=include)
        for kind in ("unspecified", "other"):
            self.call("entity", id=ident, residual=kind)
        if foundation := FOUNDATION.fullmatch(entity.get("source") or ""):
            self.call("foundation_entity", id=foundation[1])
            self.call("foundation_entity", id=foundation[1], include="ancestor")
        self.hierarchy(stem_uri, entity)
        self.related(entity)
        for exclusion in (entity.get("exclusion") or [])[:MAX_EXCLUSIONS]:
            if isinstance(exclusion, dict):
                self.entity(exclusion.get("linearizationReference"))
        self.axes(code, entity)
        self.search_title(title_of(entity))

    def hierarchy(self, stem_uri, entity):
        current, seen, parent = entity, {stem_uri}, None
        for _ in range(MAX_PATH):
            parents = current.get("parent") or []
            if not parents or parents[0] == ROOT_URI or parents[0] in seen:
                break
            seen.add(parents[0])
            current = self.entity(parents[0])
            if not current:
                break
            parent = parent or current  # the first one read is the immediate parent
        siblings = [uri for uri in (parent.get("child") or []) if uri != stem_uri] if parent else []
        for uri in siblings[:MAX_OPTIONS] + (entity.get("child") or [])[:MAX_OPTIONS]:
            self.entity(uri)
        for name in ("relatedEntitiesInMaternalChapter", "relatedEntitiesInPerinatalChapter"):
            for uri in (entity.get(name) or [])[:MAX_OPTIONS]:
                self.entity(uri)

    def related(self, entity):
        """related route: each related foundation entity's coded (MMS) entity and its children."""
        for name in ("relatedEntitiesInMaternalChapter", "relatedEntitiesInPerinatalChapter"):
            for uri in (entity.get(name) or [])[:MAX_OPTIONS]:
                found = FOUNDATION.fullmatch(uri)
                coded = self.entity(f"http://id.who.int/icd/release/11/2026-01/mms/{found[1]}") if found else None
                for child in ((coded or {}).get("child") or [])[:MAX_OPTIONS]:
                    self.entity(child)

    def axes(self, code, entity):
        """postcoordination, postcoordination-options, the searches over each axis and the composed expressions."""
        scales = [s for s in (entity.get("postcoordinationScale") or [])[:MAX_AXES] if isinstance(s, dict)]
        values = []  # ([coded value codes of the axis in order], allows several)
        for number, scale in enumerate(scales):
            roots = (scale.get("scaleEntity") or [])[:MAX_OPTIONS]
            read = [(uri, self.entity(uri)) for uri in roots]
            coded = [(uri, e) for uri, e in read if e and isinstance(e.get("code"), str) and e["code"]]
            expandable = next((e for _, e in read if e and e.get("child")), None)
            for child in ((expandable or {}).get("child") or [])[:MAX_OPTIONS]:
                self.entity(child)
            if coded and number < SEARCH_AXES:
                self.search_title(title_of(coded[0][1]), roots, prefix=3)
            if coded:
                values.append(([e["code"] for _, e in coded], scale.get("allowMultipleValues") != "NotAllowed"))

        def compose(*parts):
            """WHO's canonical order: extension values (&) first, then the other stems (/)."""
            return code + "".join("&" + p for p in parts if p.startswith("X")) + "".join("/" + p for p in parts if not p.startswith("X"))

        for names, several in values:
            self.call("codeinfo", code=names[0])
            self.call("codeinfo", code=compose(names[0]))
            if several and len(names) > 1:
                self.call("codeinfo", code=compose(names[0], names[1]))
        if len(values) > 1:
            self.call("codeinfo", code=compose(*(names[0] for names, _ in values)))


def build(root):
    sweep, codes = Sweep(root), universe()
    for code in codes:
        sweep.code(code)
    return sweep, len(codes)


def lines(sweep):
    return "".join(json.dumps({"op": op, "args": args}, ensure_ascii=False, separators=(",", ":")) + "\n"
                   for _, (op, args) in sorted(sweep.asked.items())).encode("utf-8")


def readme(sweep, data, digest, today, codes):
    count = collections.Counter(op for op, _ in sweep.asked.values())
    rows = "\n".join(f"| `{op}` | {n:,} |" for op, n in sorted(count.items()))
    return f"""# api-sweep

The reads that the Collect Plus coding screen makes for every ICD-11 code of DigitVA's datasets, made by
`scripts/icd11-parity/make_sweep.py` from the WHO container on {today}. Release 2026-01; container `{digest}`.

`calls.jsonl.gz`: {len(sweep.asked):,} requests, one `{{"op", "args"}}` JSON line each, sorted, gzip -9n. Unpacked, its sha256 is

    {hashlib.sha256(data).hexdigest()}

| op | requests |
| --- | --- |
{rows}

Every id in it (entity ids, URIs, codes of composed expressions) was discovered from the container on {today}; none is guessed, as in
`calls.json`. A 404 answer is a request like any other: the phone engine must refuse it too. `build_inputs.py` turns the file into the
section `sweep` (`sweep/<line>-<op>`); the run is `eval.sh full`.

## Code universe

{codes:,} distinct codes: the 39 of `conditions.json`, every `Code` of the certificates of `hash-synthetic-10k` and
`clinical-variants-10k` (10,000 + 10 edge cases) and of the golden corpora (`scripts/icd11-golden/corpus`: certificate codes,
postcoordination stems, the parts of their built expressions). Codes the container does not know (the edge cases') still get their
code-info requests.

## What is asked for each code

The picker's routes, with the caps of `mobile/digitva-collect/src/workspace/dorisGuidance.ts` (12 axes, 12 roots, options, siblings,
children, related, exclusions; 12 ancestors) and `dorisTerminology.ts` (search limit 20):

- code info: plain, `flexiblemode`, `convertToTerminalCodes`
- entity of the stem (a residual stem is read as its residual): plain, `include=ancestor`, `include=diagnosticCriteria`; the residual children
  `unspecified` and `other` of the stem's category; `foundation_entity` of its `source`, plain and `include=ancestor`
- hierarchy: the entity of each ancestor, sibling and child, and the foundation entity of each related maternal and perinatal link
- related: the coded entity of each related foundation entity and its children
- details: the entity of each exclusion target
- postcoordination: the entity of every axis root; postcoordination-options: the children of each axis's first expandable root
- composed expressions: `stem&X...` for extension values and `stem/code` for any other, the first value of each axis, a second value where
  the axis allows several, one expression with the first value of every axis, and code info of each first value
- search (`q="<text>%"`, the four flags, `limit` 20): the stem's title when 2 to 80 characters, and its first 4 letters; for each of the first
  {SEARCH_AXES} axes, the first root's title and its first 3 letters with `subtreesFilter` set to the axis's roots

Not covered: `include` on related entities, `descendant` (the bridge refuses it, `calls.json` tests that), a stem reached by a code the
datasets do not contain, and search texts a coder might type (`queries.json`, the golden search corpus and the titles above stand for them).

## Regenerate

    python3 scripts/icd11-parity/make_sweep.py            # writes calls.jsonl.gz and this README
    python3 scripts/icd11-parity/make_sweep.py --check    # exits 1 when the file would change

Needs the WHO container (`whoicd/icd-api:2.6.0`) on 127.0.0.1:8382. A different container image or release changes the ids and the replies;
record the new digest here.
"""


def main():
    args = [a for a in sys.argv[1:] if a != "--check"]
    root = args[0] if args else "http://127.0.0.1:8382"
    sweep, codes = build(root)
    data = lines(sweep)
    target = DATASET / "calls.jsonl.gz"
    if "--check" in sys.argv:
        same = target.exists() and gzip.decompress(target.read_bytes()) == data
        print(f"{target}: {'unchanged' if same else 'would change'} ({len(sweep.asked):,} requests)")
        sys.exit(0 if same else 1)
    DATASET.mkdir(parents=True, exist_ok=True)
    target.write_bytes(gzip.compress(data, 9, mtime=0))
    try:
        container = subprocess.check_output(["docker", "ps", "-q", "--filter", "publish=8382"], text=True).split()[0]
        image = subprocess.check_output(["docker", "inspect", "--format", "{{.Image}}", container], text=True).strip()
        digest = subprocess.check_output(["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", image], text=True).strip()
    except (OSError, IndexError, subprocess.CalledProcessError):
        digest = "unknown"
    (DATASET / "README.md").write_text(readme(sweep, data, digest, datetime.date.today().isoformat(), codes), encoding="utf-8")
    print(f"{target}: {len(sweep.asked):,} requests, {target.stat().st_size:,} bytes")
    for op, n in sorted(collections.Counter(op for op, _ in sweep.asked.values()).items()):
        print(f"  {op}: {n}")


if __name__ == "__main__":
    main()
