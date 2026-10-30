#!/usr/bin/env bash
# One uniform phone-versus-WHO-container evaluation: committed datasets, two fixed profiles, one results layout.
#
#   quick  the first 200 certificates of datasets/hash-synthetic-10k, the 5 malformed, queries.json and calls.json (472 requests), and the golden
#          requests (every WHO read recorded in scripts/icd11-golden: 1,431 calls and 161 certificates): 2,064 request lines
#   full   all 10,000 of hash-synthetic-10k, datasets/clinical-variants-10k (10,000 + 10 edge cases), the 5 malformed,
#          queries.json and calls.json, the golden requests and datasets/api-sweep (8,909 reads): 30,783 request lines
#
# Writes scripts/icd11-parity/results/<date>-<profile>-engine-<ICD11_ENGINE_VERSION|local>[-RUN_NAME]/ with requests.tsv.gz, phone.tsv.gz,
# container.tsv.gz, summary.txt (compare.py's output) and run.json. The raw work directory (library, harness, uncompressed tables) stays in a
# temp directory outside the repo. Exits with compare.py's status (1 on any mismatch); the results are written either way.
#
# Needs what run_phone.sh needs: a phone on adb, the Android NDK, gh, python3, the WHO container on 127.0.0.1:8382. ENGINE_SO and STAGED
# (run_phone.sh) test a locally built library; the directory name then says "local".
#
# usage: [ENGINE_SO=... STAGED=...] scripts/icd11-parity/eval.sh quick|full [RUN_NAME]
set -euo pipefail
profile=${1:?usage: eval.sh quick|full [RUN_NAME]}
run_name=${2:-}
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
# shellcheck source=../icd11-engine.env
. "$repo/scripts/icd11-engine.env"
case "$profile" in
  quick) certificates=200 suite=- sections=golden ;;
  full) certificates=10000 suite="$here/datasets/clinical-variants-10k" sections=golden,sweep ;;
  *) echo "profile must be quick or full" >&2; exit 2 ;;
esac
case "$run_name" in *[!A-Za-z0-9._-]*) echo "RUN_NAME may hold letters, digits, . _ - only" >&2; exit 2 ;; esac
engine="${ENGINE_SO:+local}"; engine="${engine:-$ICD11_ENGINE_VERSION}"
date_utc="$(date -u +%Y-%m-%d)"
out="$here/results/${date_utc}-${profile}-engine-${engine}${run_name:+-$run_name}"
[ ! -e "$out" ] || { echo "$out exists; pick another RUN_NAME" >&2; exit 2; }

tmp="$(mktemp -d)"
echo "raw work directory: $tmp"
# The committed file is the dataset; make_certificates.py must still produce the same bytes for the same count.
gzip -dc "$here/datasets/hash-synthetic-10k/certificates.jsonl.gz" | sed -n "1,${certificates}p" > "$tmp/ours.jsonl"
python3 "$here/make_certificates.py" "$tmp/regenerated.jsonl" "$certificates"
cmp -s "$tmp/ours.jsonl" "$tmp/regenerated.jsonl" || { echo "make_certificates.py $certificates no longer reproduces datasets/hash-synthetic-10k" >&2; exit 3; }

status=0
OURS="$tmp/ours.jsonl" CERTIFICATES="$certificates" "$here/run_phone.sh" "$tmp/run" "$suite" "$sections" || status=$?
# compare.py exits 1 on a mismatch and still prints its table; any other failure leaves no table.
grep -q '^requests:' "$tmp/run/summary.txt" 2>/dev/null || { echo "run failed before the comparison (exit $status); work kept in $tmp" >&2; exit $((status ? status : 1)); }

mkdir -p "$out"
for name in requests phone container; do gzip -9n -c "$tmp/run/$name.tsv" > "$out/$name.tsv.gz"; done
cp "$tmp/run/summary.txt" "$out/summary.txt"

phone_prop() { adb shell getprop "$1" 2>/dev/null | tr -d '\r' || true; }
container_id="$(docker ps -q --filter publish=8382 2>/dev/null | head -n 1 || true)"
container_image=unknown
if [ -n "$container_id" ]; then
  image_id="$(docker inspect --format '{{.Image}}' "$container_id" 2>/dev/null || true)"
  container_image="$(docker image inspect --format '{{index .RepoDigests 0}}' "$image_id" 2>/dev/null || echo unknown)"
fi
kit_dirty="$(git -C "$repo" status --porcelain -- scripts/icd11-parity ':!scripts/icd11-parity/results' scripts/icd11-engine.env .github/workflows/collect-plus-release.yml | head -n 1 || true)"

RUN_DATE="$date_utc" PROFILE="$profile" ENGINE_LABEL="$engine" STATUS="$status" CONTAINER_IMAGE="$container_image" \
PHONE_MODEL="$(phone_prop ro.product.model)" PHONE_ANDROID="$(phone_prop ro.build.version.release)" \
KIT_COMMIT="$(git -C "$repo" rev-parse HEAD)" KIT_DIRTY="${kit_dirty:+true}" \
COMPARE_COMMIT="$(git -C "$repo" log -1 --format=%H -- scripts/icd11-parity/compare.py)" \
RUN="$tmp/run" OURS="$tmp/ours.jsonl" CERT_GZ="$here/datasets/hash-synthetic-10k/certificates.jsonl.gz" SUITE="$suite" SECTIONS="$sections" HERE="$here" OUT="$out" \
python3 - <<'PY'
import gzip, hashlib, json, os, pathlib, sys

env = os.environ
here, run = pathlib.Path(env["HERE"]), pathlib.Path(env["RUN"])
sha = lambda data: hashlib.sha256(data).hexdigest()
provenance = dict(line.rstrip("\n").split("=", 1) for line in open(run / "provenance.env") if "=" in line)
counts = {k: int(v) for k, v in (item.split() for item in (run / "counts.txt").read_text().strip().split(", "))}
datasets = {"hash-synthetic-10k/certificates.jsonl": sha(gzip.decompress(pathlib.Path(env["CERT_GZ"]).read_bytes())),
            "certificates sent": sha(pathlib.Path(env["OURS"]).read_bytes()),
            "queries.json": sha((here / "queries.json").read_bytes()), "calls.json": sha((here / "calls.json").read_bytes())}
sys.path.insert(0, str(here))
if "golden" in env["SECTIONS"]:
    import build_inputs
    datasets["golden (scripts/icd11-golden/fixtures)"] = build_inputs.golden_sha256()
if "sweep" in env["SECTIONS"]:
    datasets["api-sweep/calls.jsonl"] = sha(gzip.decompress((here / "datasets/api-sweep/calls.jsonl.gz").read_bytes()))
if env["SUITE"] != "-":
    datasets["clinical-variants-10k"] = json.loads((pathlib.Path(env["SUITE"]) / "hashes.json").read_text())
engine = {"version": env["ENGINE_LABEL"], "tag": provenance.get("ENGINE_TAG"), "archive_sha256": provenance.get("ENGINE_ARCHIVE_SHA256"),
          "local_so_sha256": provenance.get("ENGINE_LOCAL_SO_SHA256"),
          "so_sha256": provenance.get("ENGINE_SO_SHA256") or provenance.get("ENGINE_LOCAL_SO_SHA256")}
libs = ({"source": "Collect Plus APK", "tag": provenance["LIBS_PLUS_TAG"], "apk": provenance["LIBS_PLUS_APK"], "apk_sha256": provenance["LIBS_PLUS_APK_SHA256"]}
        if "LIBS_PLUS_TAG" in provenance else {"source": "STAGED", "path": provenance.get("STAGED")})
info = {
    "date_utc": env["RUN_DATE"], "profile": env["PROFILE"], "requests": sum(counts.values()), "requests_by_section": counts,
    "kit_commit": env["KIT_COMMIT"], "kit_tree_dirty": env["KIT_DIRTY"] == "true", "compare_commit": env["COMPARE_COMMIT"],
    "engine": engine, "openssl_libcxx_libs": libs,
    "phone": {"model": env["PHONE_MODEL"] or None, "android": env["PHONE_ANDROID"] or None},
    "container_image": env["CONTAINER_IMAGE"], "datasets_sha256": datasets, "compare_exit_status": int(env["STATUS"]), "backfilled": False,
}
pathlib.Path(env["OUT"], "run.json").write_text(json.dumps(info, indent=2) + "\n")
PY
echo "results: $out (compare exit $status)"
exit "$status"
