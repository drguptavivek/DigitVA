"""DigitVA load runner (stdlib + requests; Python 3.9 compatible). Tokens come from lt_setup.py.

  uv run --with requests python lt_run.py --base https://host --tokens lt_tokens.json \
      --phase mix --duration 600 --ramp 60 --think 8 --out run1
  uv run --with requests python lt_run.py --base https://host --tokens lt_tokens.json \
      --phase doris --rps 100 --duration 120 --out run2

mix:   interviewers loop POST /intake/submissions (direct start, one new case each);
       coders loop: GET /coding/available -> POST /coding/allocation {sid} ->
       GET workspace -> GET 2 categories -> POST doris terms -> POST doris process ->
       POST /coding/finalize (a coding_tester's finalize returns the case to the pool).
doris: each coder holds one allocation, then an open loop of --rps requests/s alternates
       doris-clinical /terms and /process across the coders.
Stop early: touch /tmp/lt_abort (or Ctrl-C); results are still written.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import random
import threading
import time
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

ABORT_FILE = "/tmp/lt_abort"
TIMEOUT = 60
QUERIES = ["stroke", "malaria", "pneumonia", "tuberculosis", "diabetes", "myocardial infarction",
           "sepsis", "cirrhosis", "dengue", "kidney failure"]
FIRST = ["Asha", "Ravi", "Meena", "Suresh", "Lata", "Kiran", "Geeta", "Mohan", "Sita", "Anil"]
LAST = ["Sharma", "Verma", "Das", "Nair", "Reddy", "Singh", "Patel", "Roy", "Khan", "Joshi"]


class Ctx:
    """Run-wide state: args, stop flag, metrics, the refresh pacer."""

    def __init__(self, args):
        self.a = args
        self.base = args.base.rstrip("/")
        self.stop = threading.Event()
        self.t0 = time.monotonic()
        self.lock = threading.Lock()
        self.rows = []  # (t_seconds, label, status, ms); status 0 = no response
        self.events = Counter()
        self.refresh_next = 0.0  # pacing: the refresh route allows 30/min per IP
        self.refresh_gap = 60.0 / args.refresh_per_min

    def should_stop(self):
        if self.stop.is_set():
            return True
        if os.path.exists(ABORT_FILE):
            self.stop.set()
        return self.stop.is_set()

    def add(self, label, status, ms):
        with self.lock:
            self.rows.append((time.monotonic() - self.t0, label, status, ms))

    def event(self, name, n=1):
        with self.lock:
            self.events[name] += n

    def think(self):
        self.stop.wait(self.a.think * random.uniform(0.5, 1.5))

    def refresh_slot(self):
        with self.lock:
            now = time.monotonic()
            at = max(now, self.refresh_next)
            self.refresh_next = at + self.refresh_gap
        if at > now:
            self.stop.wait(at - now)


class VUser:
    def __init__(self, tok, ctx):
        self.tok, self.ctx = tok, ctx
        self.email = tok["email"]
        self.s = requests.Session()
        self.s.verify = not ctx.a.insecure
        if ctx.a.host_header:  # the app refuses untrusted Hosts when addressed by IP
            self.s.headers["Host"] = ctx.a.host_header
        self.lock = threading.Lock()
        self.dead = False
        self.held = None  # va_sid of the coding allocation this user holds
        self.cert = None  # doris phase: the certificate this user processes
        self.n = 0

    def _send(self, method, path, label, body=None, params=None):
        t = time.perf_counter()
        try:
            r = self.s.request(
                method, self.ctx.base + path, json=body, params=params, timeout=TIMEOUT,
                headers={"Authorization": "Bearer " + self.tok["access_token"]},
            )
        except requests.RequestException:
            self.ctx.add(label, 0, (time.perf_counter() - t) * 1000)
            return None
        self.ctx.add(label, r.status_code, (time.perf_counter() - t) * 1000)
        return r

    def req(self, method, path, label, body=None, params=None):
        used = self.tok["access_token"]
        r = self._send(method, path, label, body, params)
        if r is not None and r.status_code == 401 and not self.dead and self.refresh(used):
            r = self._send(method, path, label, body, params)
        return r

    def refresh(self, used):
        """Rotate the pair once. The refresh token rotates and reuse revokes the
        session, so the read-modify-write of the stored pair is under the lock and
        a caller whose token was already replaced by another thread just retries."""
        with self.lock:
            if self.tok["access_token"] != used:
                return True
            for _ in range(4):
                self.ctx.refresh_slot()
                if self.ctx.should_stop():
                    return False
                t = time.perf_counter()
                try:
                    r = self.s.post(self.ctx.base + "/api/v1/auth/sessions/refresh", timeout=TIMEOUT, json={
                        "refresh_token": self.tok["refresh_token"], "device_id": self.tok["device_id"],
                        "device_secret": self.tok["device_secret"]})
                except requests.RequestException:
                    self.ctx.add("auth.refresh", 0, (time.perf_counter() - t) * 1000)
                    continue
                self.ctx.add("auth.refresh", r.status_code, (time.perf_counter() - t) * 1000)
                if r.status_code == 200:
                    body = r.json()
                    self.tok["access_token"], self.tok["refresh_token"] = body["access_token"], body["refresh_token"]
                    return True
                if r.status_code != 429:
                    self.dead = True  # revoked or invalid: nothing more this user can do
                    self.ctx.event("user_dead")
                    return False
                self.ctx.stop.wait(5)
            return False

    def release(self):
        """Let go of the held allocation (the case returns to the pool)."""
        if self.held:
            self.req("POST", "/api/v1/coding/allocation/release", "coding.release", {})
            self.held = None


def ok(r, *codes):
    return r is not None and r.status_code in (codes or (200,))


def jget(r, key, default=None):
    try:
        return r.json().get(key, default)
    except (ValueError, AttributeError):
        return default


# --------------------------------------------------------------------------- mix

def interview_body(tok):
    died = dt.date.today() - dt.timedelta(days=random.randint(1, 30))
    answers = {
        "Id10013": "yes", "Id10017": random.choice(FIRST), "Id10018": random.choice(LAST),
        "Id10019": random.choice(["male", "female"]), "Id10023": died.isoformat(),
        "finalAgeInYears": str(random.randint(18, 90)), "narr_language": "english",
    }
    text = json.dumps(answers, separators=(",", ":"))
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    return {
        "client_draft_id": str(uuid.uuid4()),  # the route insists on a bare UUID
        "project_id": tok["project_id"], "site_id": tok["site_id"], "org_unit_id": tok["org_unit_id"],
        "draft": {"startedAt": now, "completedAt": now},
        "completion": {"valid": True, "issues": []},
        "answers_json": text, "answers_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def interviewer_loop(u, ctx):
    while not ctx.should_stop() and not u.dead:
        r = u.req("POST", "/api/v1/intake/submissions", "intake.submit", interview_body(u.tok))
        ctx.event("interviews_ok" if ok(r, 200, 201) else "interviews_failed")
        ctx.think()


def pick_sids(u, ctx):
    """A page of the pick-mode pool at a random offset (so coders do not all
    fight over the first rows), falling back to the first page."""
    project = u.tok["project_id"]
    for offset in (random.choice(range(0, 150, 25)), 0):
        r = u.req("GET", "/api/v1/coding/available", "coding.available",
                  params={"project_id": project, "limit": 25, "offset": offset})
        forms = jget(r, "forms", []) if ok(r) else []
        if forms:
            return [f["va_sid"] for f in forms]
        if offset == 0:
            break
    return []


def allocate(u, ctx, prep=False):
    """Allocate one pool case; up to 3 sids tried on a 409 (another coder took it)."""
    sids = pick_sids(u, ctx)
    random.shuffle(sids)
    label = "prep.allocate" if prep else "coding.allocate"
    for sid in sids[:3]:
        r = u.req("POST", "/api/v1/coding/allocation", label, {"sid": sid})
        if ok(r, 200, 201):
            u.held = sid
            return sid
        ctx.event(f"alloc_fail_{r.status_code if r is not None else 'exc'}")
        if r is None or r.status_code != 409:
            break
    if not sids:
        ctx.event("alloc_fail_empty_pool")
    return None


def certificate(seed, item):
    """The workspace's prefilled certificate with one coded Part I condition."""
    cert = dict(seed)
    cert["ICDVersion"] = "ICD11"
    cert["Part1"] = [{"Conditions": [{"Text": item["title"], "Code": item["code"], "LinearizationURI": item["uri"]}]}]
    return cert


def search_items(u, sid, query, label="doris.terms", limit=10):
    r = u.req("POST", f"/api/v1/doris-clinical/terms/{sid}", label,
              {"schema_version": 1, "query": query, "limit": limit})
    items = jget(r, "items", []) if ok(r) else []
    return [i for i in items if i.get("code") and i.get("uri")]


def code_one(u, ctx):
    sid = allocate(u, ctx)
    if sid is None:
        ctx.stop.wait(ctx.a.think)
        return
    r = u.req("GET", f"/api/v1/va/{sid}/workspace", "va.workspace", params={"mode": "coding"})
    ws = r.json() if ok(r) else {}
    if ws.get("step") != "final" or ws.get("blocked_by"):
        ctx.event("workspace_unexpected")  # e.g. narrative QA pending: this script cannot finish it
        u.release()
        return
    for cat in (c["code"] for c in ws.get("categories", [])[:2]):
        u.req("GET", f"/api/v1/va/{sid}/categories/{cat}", "va.category", params={"mode": "coding"})
    ctx.think()
    seed = (ws.get("doris") or {}).get("initial_certificate") or {}
    items = search_items(u, sid, random.choice(QUERIES))
    ctx.think()
    for rev, item in enumerate(items[:2], start=1):
        if ctx.should_stop():
            break
        r = u.req("POST", f"/api/v1/doris-clinical/process/{sid}", "doris.process", {
            "schema_version": 1, "role": "coder", "client_revision": rev, "certificate": certificate(seed, item)})
        if not ok(r):
            break
        p = r.json()
        ctx.think()
        r = u.req("POST", f"/api/v1/coding/finalize/{sid}", "coding.finalize", {
            "conclusive_cod": f"{item['code']} {item['title']}", "remark": "load test",
            "doris_certificate": p["certificate"], "doris_result": p["doris"], "codedit_result": p["codedit"],
            "doris_process_token": p["process_token"], "doris_result_digest": p["result_digest"],
            "doris_client_revision": p["client_revision"]})
        if ok(r):
            u.held = None
            ctx.event("coding_cycles_ok")
            ctx.think()
            return
        # 422 final_blocked: this case's age/sex does not allow the code; try the next item once
    if not ctx.should_stop():  # an interrupted cycle is not a failed one
        ctx.event("coding_cycles_failed")
    u.release()
    ctx.think()


def coder_loop(u, ctx):
    try:
        while not ctx.should_stop() and not u.dead:
            code_one(u, ctx)
    finally:
        u.release()


def run_mix(ctx, users):
    deadline = ctx.t0 + ctx.a.duration

    def worker(u):
        ctx.stop.wait(random.uniform(0, ctx.a.ramp))
        loop = interviewer_loop if u.tok["role"] == "interviewer" else coder_loop
        try:
            if not ctx.should_stop():
                loop(u, ctx)
        finally:
            u.release()

    with ThreadPoolExecutor(max_workers=len(users)) as pool:
        futures = [pool.submit(worker, u) for u in users]
        try:
            while time.monotonic() < deadline and not all(f.done() for f in futures):
                if ctx.should_stop():
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        ctx.stop.set()  # deadline, abort file or Ctrl-C: workers release what they hold and return


# ------------------------------------------------------------------------- doris

def prepare_doris_user(u, ctx):
    """Hold an allocation and a processable certificate: the doris routes need both."""
    sid = allocate(u, ctx, prep=True)
    if sid is None:
        return False
    r = u.req("GET", f"/api/v1/va/{sid}/workspace", "prep.workspace", params={"mode": "coding"})
    seed = ((r.json().get("doris") or {}).get("initial_certificate") or {}) if ok(r) else {}
    items = search_items(u, sid, "stroke", label="prep.terms")
    if not items:
        u.release()
        return False
    u.cert = certificate(seed, items[0])
    return True


def run_doris(ctx, users):
    coders = [u for u in users if u.tok["role"] == "coder"]
    with ThreadPoolExecutor(max_workers=16) as pool:
        ready = [u for u, good in zip(coders, pool.map(lambda x: prepare_doris_user(x, ctx), coders)) if good]
    ctx.event("doris_users_ready", len(ready))
    ctx.event("doris_users_unready", len(coders) - len(ready))
    if not ready:
        return {"dispatched": 0}

    def op(u):
        k = u.n = u.n + 1
        if k % 2:
            search_items(u, u.held, random.choice(QUERIES))
        else:
            u.req("POST", f"/api/v1/doris-clinical/process/{u.held}", "doris.process", {
                "schema_version": 1, "role": "coder", "client_revision": k, "certificate": u.cert})

    ctx.t0 = time.monotonic()  # the timeline starts when the open loop does
    start, n, interval = ctx.t0, 0, 1.0 / ctx.a.rps
    pool = ThreadPoolExecutor(max_workers=min(500, max(64, ctx.a.rps * 4)))
    try:
        while not ctx.should_stop() and time.monotonic() - start < ctx.a.duration:
            due = start + n * interval
            wait = due - time.monotonic()
            if wait > 0:
                ctx.stop.wait(wait)
            pool.submit(op, ready[n % len(ready)])
            n += 1
    except KeyboardInterrupt:
        ctx.stop.set()
    elapsed = time.monotonic() - start
    pool.shutdown(wait=True)
    for u in ready:
        u.release()
    return {"dispatched": n, "target_rps": ctx.a.rps, "dispatched_rps": round(n / elapsed, 2),
            "window_s": round(elapsed, 1)}


# ---------------------------------------------------------------------- results

def pct(sorted_ms, p):
    if not sorted_ms:
        return None
    return round(sorted_ms[max(0, min(len(sorted_ms) - 1, math.ceil(p / 100 * len(sorted_ms)) - 1))], 1)


def summarise(ctx, extra):
    by = defaultdict(list)
    codes = defaultdict(Counter)
    buckets = defaultdict(list)
    for t, label, status, ms in ctx.rows:
        by[label].append(ms)
        codes[label][str(status)] += 1
        if t >= 0:
            buckets[int(t // 10)].append((status, ms))
    endpoints = {}
    for label, ms in sorted(by.items()):
        ms.sort()
        endpoints[label] = {"count": len(ms), "status": dict(sorted(codes[label].items())),
                            "p50_ms": pct(ms, 50), "p95_ms": pct(ms, 95), "p99_ms": pct(ms, 99), "max_ms": round(ms[-1], 1)}
    timeline = []
    for b in sorted(buckets):
        rows = buckets[b]
        lat = sorted(m for _, m in rows)
        timeline.append({"t": b * 10, "rps": round(len(rows) / 10, 1), "requests": len(rows),
                         "errors_5xx_or_exc": sum(1 for s, _ in rows if s == 0 or s >= 500),
                         "r429": sum(1 for s, _ in rows if s == 429), "p95_ms": pct(lat, 95)})
    return {"args": vars(ctx.a), "events": dict(ctx.events), **extra, "endpoints": endpoints, "timeline": timeline}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--tokens", required=True)
    ap.add_argument("--phase", choices=["mix", "doris"], required=True)
    ap.add_argument("--duration", type=float, default=300, help="seconds; mix: whole run incl. ramp")
    ap.add_argument("--ramp", type=float, default=30, help="mix: users start spread over this many seconds")
    ap.add_argument("--think", type=float, default=8, help="mean seconds between a user's requests (jittered 0.5-1.5x)")
    ap.add_argument("--rps", type=int, default=100, help="doris phase: aggregate requests/s")
    ap.add_argument("--out", default="lt_result")
    ap.add_argument("--insecure", action="store_true", help="verify=False (raw IP with a hostname cert)")
    ap.add_argument("--host-header", default=None, help="send this Host header on every request (use with --insecure for a raw IP)")
    ap.add_argument("--refresh-per-min", type=int, default=25, help="global pacing of token refreshes (route limit: 30/min/IP)")
    args = ap.parse_args()
    if args.insecure:
        requests.packages.urllib3.disable_warnings()
    if os.path.exists(ABORT_FILE):
        raise SystemExit(f"{ABORT_FILE} exists; remove it first")

    ctx = Ctx(args)
    with open(args.tokens) as fh:
        users = [VUser(t, ctx) for t in json.load(fh)]
    print(f"{args.phase}: {sum(u.tok['role'] == 'interviewer' for u in users)} interviewers, "
          f"{sum(u.tok['role'] == 'coder' for u in users)} coders -> {ctx.base}", flush=True)
    extra = {}
    try:
        if args.phase == "mix":
            run_mix(ctx, users)
        else:
            extra = run_doris(ctx, users)
    finally:
        ctx.stop.set()
        for u in users:  # anything still held (a failed prep, an interrupted run)
            u.release()
    result = summarise(ctx, extra)
    with open(args.out + ".json", "w") as fh:
        json.dump(result, fh, indent=1)
    with open(args.out + "_timeline.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["t", "rps", "requests", "errors_5xx_or_exc", "r429", "p95_ms"])
        w.writeheader()
        w.writerows(result["timeline"])

    print(f"{'endpoint':<22}{'n':>7}{'p50':>8}{'p95':>8}{'p99':>8}{'max':>9}  statuses")
    for label, e in result["endpoints"].items():
        print(f"{label:<22}{e['count']:>7}{e['p50_ms']:>8}{e['p95_ms']:>8}{e['p99_ms']:>8}{e['max_ms']:>9}  {e['status']}")
    print("events:", result["events"])
    if extra:
        done = sum(e["count"] for k, e in result["endpoints"].items() if k.startswith("doris."))
        print(f"doris: target {extra.get('target_rps')} rps, dispatched {extra.get('dispatched_rps')} rps, "
              f"completed {done} requests in {extra.get('window_s')}s = {round(done / max(extra.get('window_s') or 1, 1), 1)} rps")
    print(f"wrote {args.out}.json and {args.out}_timeline.csv")


if __name__ == "__main__":
    main()
