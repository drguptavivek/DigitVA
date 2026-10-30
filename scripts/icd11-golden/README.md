# ICD-11 / DORIS golden sets

Three versioned sets recorded from the reference (the pinned WHO container
`whoicd/icd-api:2.6.0`, release 2026-01, and the DigitVA server's own service
functions). The TypeScript port is tested offline in jest against `who`
(WHO's replies); the phone engine is compared with the same replies in the
parity kit. Design: `.tasks/2026-10-29-android-offline-doris-parity.md`.

| Set | Corpus (inputs, owner-reviewed) | Fixtures | What each fixture holds |
| --- | --- | --- | --- |
| DORIS | `corpus/doris.json` | `fixtures/doris/<id>.json` | the certificate, WHO's codeinfo/DORIS/CoDEdit calls and replies, and DigitVA's process reply (`doris`, `codedit`, `ucod_parts`, `who_notes`; digests and token left out) or its 422 error |
| Postcoordination | `corpus/postcoordination.json` | `fixtures/postcoordination/<id>.json` | per stem: codeinfo, selection-check, postcoordination, postcoordination-options (first expandable root of each axis), hierarchy, related (maternal, perinatal), details; per built expression: codeinfo, selection-check, URI, hierarchy, related, details |
| Search | `corpus/search.json` | `fixtures/search/<id>.json` | WHO's search reply and DigitVA's `terms` reply cut to the top 5 in order (`item_count` says how many of the 20 there were) |

Fixture shape: `input` (the corpus item), `operations[]` (`name`, `request`,
`calls` = keys into `who` in call order with repeats, `reply` = `{http_status,
body}` exactly as the route returns it, errors included) and `who` (key ->
`{method, path, request_body, status, reply}`, one line each). `uniqueSearchId`
is removed; nothing else is dropped or trimmed. `manifest.json` has counts,
bytes, the WHO image digest and release.

`REVIEW.md` lists every corpus item for approval; regenerate it with
`python3 scripts/icd11-golden/review.py`. `status` in each corpus file is
`approved`: the owner approved all three sets on 2026-10-30 and they are frozen.
A change sets it back to `draft` until the owner approves again.

## Re-record

Needs the dev stack with `icd_api_service` running. Take the digest from the
host, then run inside the app container (reads WHO only; no database writes):

```bash
DIGEST=$(docker image inspect --format '{{index .RepoDigests 0}}' \
  "$(docker inspect --format '{{.Config.Image}}' digitva-icd_api_service-1)" | sed 's/.*@//')
docker compose exec -T minerva_app_service uv run --no-sync python \
  scripts/icd11-golden/record.py --who-image-digest "$DIGEST"
```

`--only id,id` re-records some items (manifest untouched); `--set doris|postcoordination|search`
limits a set; `--check` writes nothing and exits 1 if any fixture would change.

**Any changed expected value is a reviewed change, never a silent re-record.**
Run `--check` first, read the git diff of `fixtures/`, and commit it with the
reason (WHO release, server rule change, corpus edit). The recorder is
deterministic: two runs on the same container give identical files.

## Notes

- Private server function used: `app.routes.api.doris_clinical._codeinfo_item`
  (the route handlers need a session and allocation). The route-level input
  checks and error bodies are copied in `record.py`.
- The recorder patches `requests` to capture the exact calls; it refuses any
  URL containing `include=descendant`, and the server's own caps apply (20
  terms, 12 axes and options, 48 guidance calls per request).
- Titles in `ucod_parts` use a per-item in-memory cache instead of Redis, so
  every title lookup reaches WHO and is recorded.
