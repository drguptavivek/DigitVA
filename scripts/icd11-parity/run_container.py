"""Send the same request list to the official WHO container and write results in the phone harness's format.

Same calls the DigitVA server makes (app/services/who_icd_api.py), with API-Version v2:
D -> POST /icd/release/11/2026-01/{doris,codedit} with the text as the body;
G -> the REST request that matches the engine call "<op>\t<json>" (see call_op): search is the server's own POST with a
form body, codeinfo and the entities are GETs with the arguments as query parameters, doris and codedit POST the certificate.
Two bounds are DigitVA's, not WHO's, and WHO's container knows neither: `limit` on search (the container is asked without it and its
reply is trimmed the way Bridge.cs trims, see chop) and `include` containing "descendant" (refused here as the bridge refuses it,
without asking the container). A `limit` outside 1..200 is answered 400 here too, and so is a `limit` together with `flatResults=false`
(WHO nests descendants under each result, which the trim does not reach).
HTTP errors are recorded with their status and body, not raised.

usage: python3 scripts/icd11-parity/run_container.py REQUESTS.tsv OUT.tsv [BASE_URL]
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HEADERS = {"Accept": "application/json", "Accept-Language": "en", "API-Version": "v2"}


def call(url, body=None, content_type="application/json"):
    headers = dict(HEADERS, **({"Content-Type": content_type} if body is not None else {}))
    request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=60) as reply:
            status, text = reply.status, reply.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        status, text = error.code, error.read().decode("utf-8", "replace")
    elapsed = (time.perf_counter() - started) * 1000
    return status, " ".join(text.replace("\t", " ").splitlines()), elapsed


def query(args, names):
    """Query string of the arguments that are present; booleans spelled the way ASP.NET binds them."""
    pairs = [(k, str(args[k]).lower() if isinstance(args[k], bool) else args[k]) for k in names if k in args and args[k] is not None]
    return ("?" + urllib.parse.urlencode(pairs)) if pairs else ""


REFUSED_DESCENDANT = '{"error":"include descendant is not allowed"}'
REFUSED_LIMIT_NESTED = '{"error":"limit requires flatResults"}'


def chop(status, body, limit):
    """Bridge.cs Chop on the container's search reply: keep `limit` destinationEntities, set resultChopped when any were cut."""
    if not 200 <= status < 300:
        return body
    reply = json.loads(body)
    entities = reply.get("destinationEntities")
    if isinstance(entities, list) and len(entities) > limit:
        reply["destinationEntities"] = entities[:limit]
        reply["resultChopped"] = True
    return json.dumps(reply, ensure_ascii=False, separators=(",", ":"))


RELEASE = "icd/release/11/2026-01"


def rest(op, args):
    """The single WHO REST request of the engine call `op` with `args`: (method, path, body, content type), the path relative to the
    container root. search is the server's POST with a form body, codeinfo and the entities are GETs with the arguments as query
    parameters, doris and codedit POST the certificate. The bounds (limit, refused include) are not here: call_op applies them."""
    if op == "search":
        form = {k: str(v).lower() if isinstance(v, bool) else v for k, v in args.items() if v is not None}
        return "POST", f"{RELEASE}/mms/search", urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    if op == "codeinfo":
        return "GET", f"{RELEASE}/mms/codeinfo/" + urllib.parse.quote(args.get("code", ""), safe="") + query(args, ["flexiblemode", "convertToTerminalCodes"]), None, None
    if op == "entity":
        residual = "/" + urllib.parse.quote(args["residual"], safe="") if args.get("residual") else ""
        return "GET", f"{RELEASE}/mms/" + urllib.parse.quote(args.get("id", ""), safe="") + residual + query(args, ["include"]), None, None
    if op == "foundation_entity":
        return "GET", "icd/entity/" + urllib.parse.quote(args.get("id", ""), safe="") + query(args, ["include"]), None, None
    if op in ("doris", "codedit"):
        return "POST", f"{RELEASE}/{op}", json.dumps(args["certificate"], separators=(",", ":"), ensure_ascii=False).encode("utf-8"), "application/json"
    raise SystemExit(f"unknown op {op}")


def call_op(root, base, op, args):
    """The container's answer to the engine call `op` with the JSON object `args`: (status, body, ms)."""
    if op in ("entity", "foundation_entity") and "descendant" in str(args.get("include") or "").lower():
        return 400, REFUSED_DESCENDANT, 0.0
    if op == "search" and "limit" in args:
        limit = args["limit"]
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            return 400, '{"error":"bad argument: limit"}', 0.0
        flat = args.get("flatResults")
        if flat is not None and not isinstance(flat, bool):
            return 400, '{"error":"bad argument: flatResults"}', 0.0
        if flat is False:
            return 400, REFUSED_LIMIT_NESTED, 0.0
        status, body, ms = call_op(root, base, op, {k: v for k, v in args.items() if k != "limit"})
        return status, chop(status, body, limit), ms
    _, path, body, content_type = rest(op, args)
    return call(f"{root}/{path}", body, content_type) if body is not None else call(f"{root}/{path}")


def main():
    requests_path, out_path = sys.argv[1], sys.argv[2]
    root = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8382"
    base = root + "/icd/release/11/2026-01"
    with open(requests_path, encoding="utf-8") as src, open(out_path, "w", encoding="utf-8") as out:
        for line in src:
            kind, ident, arg = line.rstrip("\n").split("\t", 2)
            if kind == "G":
                op, args = arg.split("\t", 1)
                s, body, t = call_op(root, base, op, json.loads(args))
                out.write(f"CALL\t{ident}\t{t:.2f}\t{s}\t{body}\n")
            elif kind == "D":
                s1, doris, t1 = call(f"{base}/doris", arg.encode("utf-8"))
                s2, codedit, t2 = call(f"{base}/codedit", arg.encode("utf-8"))
                out.write(f"CERT\t{ident}\t{t1:.2f}\t{t2:.2f}\t{s1}\t{s2}\t{doris}\t{codedit}\n")

if __name__ == "__main__":
    main()
