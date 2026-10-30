"""Record the ICD-11 / DORIS golden fixtures from the reference.

For every corpus item this calls the DigitVA server's own service functions (no
HTTP to Flask, no auth, no database writes) against the WHO container, and
saves in one file per item:

  * every raw WHO REST call the server code made and WHO's JSON reply, so the
    TypeScript port can be replayed offline (``who``: replies by key, and each
    operation's ``calls``: the keys in call order, repeats included);
  * the DigitVA reply the server builds from those calls (``reply``).

Run inside the app container (see README.md):

  docker compose exec -T minerva_app_service uv run --no-sync python \
      scripts/icd11-golden/record.py --who-image-digest sha256:...

Private server functions used, because the routes wrap them in Flask handlers
that need a session and an allocation: ``doris_clinical._codeinfo_item``. The
route-level input checks and error bodies are copied from
``app/routes/api/doris_clinical.py`` (``_error``, the 422 / 503 mapping).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # the app package, when run as a script

import requests  # noqa: E402

SETS = ("doris", "postcoordination", "search")
# Never ask WHO for descendants: the phone engine refuses it too.
FORBIDDEN_QUERY = "include=descendant"
MAX_RESPONSE = 2 * 1024 * 1024  # who_icd_api._MAX_RESPONSE_LENGTH
PLACEHOLDER_URI = "http://id.who.int/icd/release/11/2026-01/mms/0"


# --------------------------------------------------------------- recording

def _scrub(value):
    """Drop WHO's per-request ``uniqueSearchId`` (non-deterministic)."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k != "uniqueSearchId"}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


class Recorder:
    """Captures each WHO request/reply that goes through ``requests``."""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/") + "/"
        self.replies: dict[str, dict] = {}
        self.calls: list[str] = []
        self.silent = False

    def reset(self):
        self.replies, self.calls = {}, []

    def capture(self, method, url, body, response):
        # Read the body the way who_icd_api does, then hand it back as the raw stream.
        content = response.raw.read(MAX_RESPONSE + 1)
        response.raw = io.BytesIO(content)
        if self.silent:
            return response
        path = url[len(self.base):] if url.startswith(self.base) else url
        body_text = body.decode("utf-8") if isinstance(body, bytes) else (body or "")
        key = f"{method} {path}"
        if body_text:
            key += " #" + hashlib.sha1(body_text.encode()).hexdigest()[:10]
        try:
            reply = {"reply": _scrub(json.loads(content))}
        except ValueError:
            reply = {"reply_text": content.decode("utf-8", "replace")}
        self.replies[key] = {"method": method, "path": path, "request_body": body_text or None,
                             "status": response.status_code, **reply}
        self.calls.append(key)
        return response

    def install(self):
        real_request, real_post = requests.request, requests.post

        def guard(url):
            if FORBIDDEN_QUERY in url.lower():
                raise RuntimeError(f"refused: {FORBIDDEN_QUERY} in {url}")

        def request(method, url, **kw):
            guard(url)
            return self.capture(method, url, kw.get("data"), real_request(method, url, **kw))

        def post(url, data=None, json=None, **kw):  # noqa: A002 - mirrors requests.post
            guard(url)
            return self.capture("POST", url, data, real_post(url, data=data, json=json, **kw))

        requests.request, requests.post = request, post

    @contextmanager
    def operation(self):
        """Collect the call keys made inside the block (repeats kept)."""
        start = len(self.calls)
        box: list[str] = []
        try:
            yield box
        finally:
            box.extend(self.calls[start:])

    @contextmanager
    def paused(self):
        self.silent = True
        try:
            yield
        finally:
            self.silent = False


class MemoryCache:
    """Stand-in for the Redis cache behind icd11_titles, empty per item, so
    every title lookup reaches WHO and is recorded."""

    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value, timeout=None):
        self._data[key] = value


# ------------------------------------------------- DigitVA replies, per route

def _err(code, message, status, fields=None):
    body = {"schema_version": 1, "error": {"code": code, "message": message}}
    if fields is not None:
        body["error"]["fields"] = fields
    return {"http_status": status, "body": body}


def _ok(body):
    return {"http_status": 200, "body": body}


class Server:
    """The route logic of doris_clinical.py, minus Flask, auth and allocation."""

    def __init__(self):
        from app.routes.api import doris_clinical as route
        from app.services import icd11_postcoordination as pc
        from app.services import who_icd_api
        from app.services.doris_certificate import DorisCertificateError, expected_expression_uri
        from app.services.doris_processing import process_certificate

        self.route, self.pc, self.who = route, pc, who_icd_api
        self.DorisCertificateError = DorisCertificateError
        self.expected_expression_uri = expected_expression_uri
        self.process_certificate = process_certificate
        self.release = who_icd_api.DEFAULT_ICD11_RELEASE

    def _unavailable(self, guidance=False):
        return _err("WHO_API_UNAVAILABLE",
                    "WHO ICD-11 guidance is unavailable." if guidance else "WHO ICD-11 service unavailable.", 503)

    def terms(self, query, limit=20, subtree_uris=None):
        if not (isinstance(query, str) and 2 <= len(query.strip()) <= 80 and 1 <= limit <= 20
                and self.pc.valid_subtree_uris(subtree_uris)):
            return _err("INVALID_INPUT", "The terminology request is invalid.", 422)
        try:
            result = self.pc.search_terms(query, limit=limit, subtree_uris=subtree_uris)
        except (self.who.WhoIcdApiUnavailable, ValueError):
            return self._unavailable()
        return _ok({"schema_version": 1, "items": result["items"],
                    "truncated": result["truncated"], "next_cursor": None})

    def codeinfo(self, code):
        if not isinstance(code, str) or not code.strip() or len(code.strip()) > 128:
            return _err("INVALID_INPUT", "The code request is invalid.", 422)
        try:
            item = self.route._codeinfo_item(code.strip())  # private: see module doc
        except (self.who.WhoIcdApiUnavailable, ValueError):
            return self._unavailable()
        if item is None:
            return _err("CODE_NOT_FOUND", "Select a valid ICD-11 code.", 422)
        return _ok({"schema_version": 1, "item": item})

    def selection_check(self, code, uri):
        try:
            item = self.route._codeinfo_item(code.strip())
        except (self.who.WhoIcdApiUnavailable, ValueError):
            return self._unavailable()
        if item is None or item["uri"] != uri.strip():
            return _err("INVALID_SELECTION", "The selected code does not match its WHO URI.", 422)
        return _ok({"schema_version": 1, "item": item})

    def guidance(self, operation):
        try:
            with self.pc.guidance_request():
                return _ok(operation())
        except self.pc.PostcoordinationError as exc:
            return _err(exc.code, str(exc), exc.status)
        except (self.who.WhoIcdApiUnavailable, ValueError):
            return self._unavailable(guidance=True)

    def process(self, certificate, digest):
        payload = {"schema_version": 1, "client_revision": 0, "certificate": certificate}
        try:
            result = self.process_certificate(payload, release=self.release, who_image_digest=digest,
                                              va_sid=None, actor_role=None)
        except self.DorisCertificateError as exc:
            return _err("INVALID_INPUT", "The DORIS certificate is invalid.", 422,
                        [{"path": f.path, "message": f.message} for f in exc.fields])
        except ValueError:
            return _err("INVALID_INPUT", "The DORIS process request is invalid.", 422)
        except self.who.WhoIcdApiUnavailable:
            return self._unavailable()
        # Digests are derived from the WHO image digest; the token is server-secret.
        for key in ("certificate_digest", "result_digest"):
            result.pop(key, None)
        return _ok(result)


# ------------------------------------------------------------ item recorders

def _run(rec: Recorder, name: str, request: dict, fn) -> dict:
    with rec.operation() as calls:
        reply = fn()
    return {"name": name, "request": request, "calls": calls, "reply": reply}


def _stem_uri(rec, server, code):
    with rec.paused():
        info = server.who.get_icd11_codeinfo(code)
    return info.get("stemId") if isinstance(info, dict) else None


def _guidance_ops(rec, server, code, ops):
    """hierarchy, related (both chapters) and details for one code or expression."""
    pc = server.pc
    ops.append(_run(rec, "hierarchy", {"code": code}, lambda: server.guidance(lambda: pc.hierarchy(code))))
    for chapter in ("maternal", "perinatal"):
        ops.append(_run(rec, f"related-{chapter}", {"code": code, "chapter": chapter},
                        lambda chapter=chapter: server.guidance(lambda: pc.related_terms(code, chapter))))
    ops.append(_run(rec, "details", {"code": code}, lambda: server.guidance(lambda: pc.code_details(code))))


def _codeinfo_ops(rec, server, code, ops):
    ops.append(_run(rec, "codeinfo", {"code": code}, lambda: server.codeinfo(code)))
    with rec.operation() as calls:
        uri = server.expected_expression_uri(code, server.release) or PLACEHOLDER_URI
    ops.append(_run(rec, "selection-check", {"code": code, "uri": uri}, lambda: server.selection_check(code, uri)))
    ops[-1]["calls"] = calls + ops[-1]["calls"]  # computing the URI is part of the check
    return uri


def record_postcoordination(rec, server, item, digest):
    ops, stem = [], item["stem"]
    _codeinfo_ops(rec, server, stem, ops)
    pc = server.pc
    ops.append(_run(rec, "postcoordination", {"code": stem}, lambda: server.guidance(lambda: pc.postcoordination(stem))))
    reply = ops[-1]["reply"]
    requests_ = []  # (axis, parent uri, why)
    if reply["http_status"] == 200:
        for axis in reply["body"]["axes"]:
            expandable = next((o for o in axis["options"] if o["has_children"]), None)
            if expandable:
                requests_.append((axis["id"], expandable["uri"]))
    for extra in item.get("options", []):
        requests_.append((extra["axis_id"], _stem_uri(rec, server, extra["parent"]) or PLACEHOLDER_URI))
    for axis_id, parent_uri in requests_:
        ops.append(_run(rec, "postcoordination-options",
                        {"stem_code": stem, "axis_id": axis_id, "parent_uri": parent_uri},
                        lambda a=axis_id, p=parent_uri: server.guidance(lambda: pc.postcoordination_options(stem, a, p))))
    _guidance_ops(rec, server, stem, ops)
    built = []
    for entry in item.get("built", []):
        bops: list[dict] = []
        uri = _codeinfo_ops(rec, server, entry["expression"], bops)
        _guidance_ops(rec, server, entry["expression"], bops)
        built.append({"expression": entry["expression"], "why": entry["why"],
                      "uri": None if uri == PLACEHOLDER_URI else uri, "operations": bops})
    return {"operations": ops, "built": built}


def record_doris(rec, server, item, digest):
    cert = item["certificate"]
    return {"operations": [_run(rec, "process", {"schema_version": 1, "client_revision": 0, "certificate": cert},
                                lambda: server.process(cert, digest))]}


def record_search(rec, server, item, digest):
    op = _run(rec, "terms", {"schema_version": 1, "query": item["query"], "limit": 20},
              lambda: server.terms(item["query"], 20))
    body = op["reply"]["body"]
    if op["reply"]["http_status"] == 200:  # expected = the top 5, in order
        body["item_count"] = len(body["items"])
        body["items"] = body["items"][:5]
    return {"operations": [op]}


RECORDERS = {"doris": record_doris, "postcoordination": record_postcoordination, "search": record_search}


def failures_in(fixture) -> list[str]:
    """Reasons the recording itself (not the expected result) is unusable."""
    found = []
    ops = list(fixture["operations"]) + [o for b in fixture.get("built", []) for o in b["operations"]]
    for op in ops:
        body = op["reply"]["body"]
        if op["reply"]["http_status"] == 503 and body["error"]["code"] in ("WHO_API_UNAVAILABLE", "GUIDANCE_BUSY"):
            found.append(f"{op['name']}: {body['error']['code']}")
        if op["name"] == "process" and op["reply"]["http_status"] == 200:
            for engine in ("doris", "codedit"):
                if body[engine]["status"] in ("timeout", "unavailable", "malformed_response"):
                    found.append(f"process: {engine} {body[engine]['status']}")
    return found


# ---------------------------------------------------------------------- main

def dump(value) -> str:
    return json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def dump_fixture(fixture: dict) -> str:
    """Readable diffs: everything indented, but each raw WHO reply on one line."""
    who = fixture["who"]
    head = dump({k: v for k, v in fixture.items() if k != "who"}).rstrip("\n}").rstrip()
    lines = [" " * 2 + json.dumps(key, ensure_ascii=False) + ": "
             + json.dumps(who[key], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
             for key in sorted(who)]
    return head + ',\n "who": {\n' + ",\n".join(lines) + "\n }\n}\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", choices=(*SETS, "all"), default="all")
    parser.add_argument("--only", help="comma-separated item ids (does not touch the manifest)")
    parser.add_argument("--out", default=str(HERE / "fixtures"))
    parser.add_argument("--who-image-digest", help="from docker image inspect on the host; required for a full run")
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 if any fixture would change")
    args = parser.parse_args(argv)
    only = set(args.only.split(",")) if args.only else None
    if not (only or args.check or args.who_image_digest):
        parser.error("--who-image-digest is required for a full run (the manifest records it)")

    from app import create_app
    from app.services import icd11_titles

    app = create_app()
    out = Path(args.out)
    rec = Recorder(app.config["ICD11_API_BASE_URL"])
    rec.install()
    failures, changed, written = [], [], {}
    for set_name in SETS if args.set == "all" else (args.set,):
        corpus = json.loads((HERE / "corpus" / f"{set_name}.json").read_text())
        written[set_name] = corpus["items"]
        for item in corpus["items"]:
            if only and item["id"] not in only:
                continue
            rec.reset()
            icd11_titles.cache = MemoryCache()
            try:
                with app.app_context():  # fresh flask.g per item (title outage flag)
                    result = RECORDERS[set_name](rec, Server(), item, app.config["DORIS_WHO_IMAGE_DIGEST"])
            except Exception as exc:  # noqa: BLE001 - report and keep going
                failures.append(f"{set_name}/{item['id']}: script error {type(exc).__name__}: {exc}")
                continue
            fixture = {"id": item["id"], "kind": set_name, "input": item, "who": rec.replies, **result}
            for reason in failures_in(fixture):
                failures.append(f"{set_name}/{item['id']}: {reason}")
            path = out / set_name / f"{item['id']}.json"
            text = dump_fixture(fixture)
            if not path.exists() or path.read_text() != text:
                changed.append(str(path.relative_to(out)))
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)

    if not (only or args.check):
        stale = []
        for set_name, items in written.items():
            keep = {f"{i['id']}.json" for i in items}
            for path in sorted((out / set_name).glob("*.json")):
                if path.name not in keep:
                    stale.append(str(path))
                    path.unlink()
        manifest = {
            "release": "2026-01",
            "who_image": "whoicd/icd-api:2.6.0",
            "who_image_digest": args.who_image_digest,
            "who_image_digest_pinned_in_config": app.config["DORIS_WHO_IMAGE_DIGEST"],
            "sets": {}, "failures": failures,
        }
        for set_name in written:
            corpus = json.loads((HERE / "corpus" / f"{set_name}.json").read_text())
            files = sorted((out / set_name).glob("*.json"))
            manifest["sets"][set_name] = {
                "corpus_status": corpus["status"], "corpus_items": len(corpus["items"]),
                "fixtures": len(files), "bytes": sum(f.stat().st_size for f in files),
            }
        (out / "manifest.json").write_text(dump(manifest))
        print("removed stale:", stale or "none")
    print("changed:", len(changed), changed[:10])
    print("failures:", len(failures))
    for line in failures:
        print("  ", line)
    return 1 if failures or (args.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())
