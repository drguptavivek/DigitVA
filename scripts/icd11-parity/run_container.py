"""Send the same request list to the official WHO container and write results in the phone harness's format.

Same calls the DigitVA server makes (app/services/who_icd_api.py), with API-Version v2:
D -> POST /icd/release/11/2026-01/{doris,codedit} with the text as the body;
S -> GET .../mms/search?q=<text> (no other options, as the phone's search op takes the text only);
C -> GET .../mms/codeinfo/<code> (path-encoded).
HTTP errors are recorded with their status and body, not raised.

usage: python3 scripts/icd11-parity/run_container.py REQUESTS.tsv OUT.tsv [BASE_URL]
"""
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HEADERS = {"Accept": "application/json", "Accept-Language": "en", "API-Version": "v2"}


def call(url, body=None):
    headers = dict(HEADERS, **({"Content-Type": "application/json"} if body is not None else {}))
    request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=60) as reply:
            status, text = reply.status, reply.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        status, text = error.code, error.read().decode("utf-8", "replace")
    elapsed = (time.perf_counter() - started) * 1000
    return status, " ".join(text.replace("\t", " ").splitlines()), elapsed


def main():
    requests_path, out_path = sys.argv[1], sys.argv[2]
    base = (sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8382") + "/icd/release/11/2026-01"
    with open(requests_path, encoding="utf-8") as src, open(out_path, "w", encoding="utf-8") as out:
        for line in src:
            kind, ident, arg = line.rstrip("\n").split("\t", 2)
            if kind == "D":
                s1, doris, t1 = call(f"{base}/doris", arg.encode("utf-8"))
                s2, codedit, t2 = call(f"{base}/codedit", arg.encode("utf-8"))
                out.write(f"CERT\t{ident}\t{t1:.2f}\t{t2:.2f}\t{s1}\t{s2}\t{doris}\t{codedit}\n")
            elif kind == "S":
                s, body, t = call(f"{base}/mms/search?" + urllib.parse.urlencode({"q": arg}))
                out.write(f"SEARCH\t{ident}\t{t:.2f}\t{s}\t{body}\n")
            elif kind == "C":
                s, body, t = call(f"{base}/mms/codeinfo/" + urllib.parse.quote(arg, safe=""))
                out.write(f"CODEINFO\t{ident}\t{t:.2f}\t{s}\t{body}\n")


if __name__ == "__main__":
    main()
