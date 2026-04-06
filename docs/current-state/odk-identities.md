---
title: "ODK Central Submission Identity: __id, instanceID, and deprecatedID"
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-07
---

# ODK Central Submission Identity: `__id`, `instanceID`, and `deprecatedID`

A single ODK Central submission carries **at least three** different identifiers.
Two of them look like UUIDs, one of them *changes* when the submission is edited,
and the naming is just similar enough to cause confusion.
This document walks through what each one is, which API surface exposes it,
and how to build a reliable sync pipeline on top of them.

---

## The cast of characters

| Identifier | What it is | Stable on edit? | Where it lives |
|---|---|---|---|
| `__id` | ODK Central's internal submission primary key | **Yes** | OData only |
| `instanceId` (REST top-level) | Same value as `__id` | **Yes** | REST API only |
| `meta.instanceID` / `currentVersion.instanceId` | The form-level instance UUID from the XML `<meta>` block | **No** — new UUID on every edit | OData, REST, XML |
| `deprecatedID` | The *previous* `instanceID` before the edit | N/A (only present after an edit) | XML only |

The two **stable** identifiers (`__id` and REST `instanceId`) are always the
same value — they are just returned by different API surfaces.
Think of them as the submission's "birth certificate" — assigned once, never
reissued.

The **mutable** `instanceID` is more like a "revision token" — it updates every
time the submission is edited in ODK Central or via Enketo.

---

## A concrete example (synthetic data)

Imagine a form `SITE01_DS_WHOVA2022` in ODK project `7`.
A health worker submits a form on their phone.
Later, a data manager edits it in Enketo to correct a typo.

### Initial submission

```
Submission arrives from ODK Collect.
ODK assigns it an internal key (becomes __id).
The phone's form XML sets <instanceID> to the same UUID.
```

| Field | Value |
|---|---|
| `__id` / REST `instanceId` | `uuid:a1b2c3d4-5678-4abc-def0-1234567890ab` |
| `meta.instanceID` | `uuid:a1b2c3d4-5678-4abc-def0-1234567890ab` |

Everything matches. This is the happy path for a freshly submitted form.

### After an Enketo edit

```
Data manager opens the submission in Enketo, fixes a typo, saves.
ODK Central keeps the same internal key but the XML gets a new instanceID.
The old instanceID moves into deprecatedID.
```

| Field | Value |
|---|---|
| `__id` / REST `instanceId` | `uuid:a1b2c3d4-5678-4abc-def0-1234567890ab` — **unchanged** |
| `meta.instanceID` | `uuid:f9e8d7c6-b5a4-3210-fedc-ba9876543210` — **new UUID** |
| `deprecatedID` | `uuid:a1b2c3d4-5678-4abc-def0-1234567890ab` — the original |

A second edit would produce yet another `instanceID`, and the *previous*
`instanceID` would become the new `deprecatedID`.

---

## What each API surface returns

ODK Central exposes submission data through two main API families.
Here is what identifier each one gives you, for the same edited submission.

### 1. OData endpoint — the analytics API

```
GET /v1/projects/7/forms/SITE01_DS_WHOVA2022.svc/Submissions
```

```json
{
  "value": [
    {
      "__id": "uuid:a1b2c3d4-5678-4abc-def0-1234567890ab",
      "__system": {
        "submissionDate": "2025-09-10T08:30:00.000Z",
        "updatedAt": "2025-11-15T14:22:00.000Z",
        "reviewState": "hasIssues"
      },
      "meta": {
        "instanceID": "uuid:f9e8d7c6-b5a4-3210-fedc-ba9876543210",
        "instanceName": "SITE01_2025_001_MARY_WHOVA2022"
      },
      "unique_id": "SITE01_2025_001_MARY",
      "...": "..."
    }
  ]
}
```

Takeaways:

- `__id` — **the stable key**, always the original UUID. This is what you should
  use as your primary identifier.
- `meta.instanceID` — **the current revision's UUID**. Matches `__id` for fresh
  submissions, diverges after edits.
- There is **no** `deprecatedID` in OData. You cannot see the previous revision
  token through this API.

Single-entity access works the same way:

```
GET .../Submissions('uuid:a1b2c3d4-5678-4abc-def0-1234567890ab')
```

### 2. REST endpoint — the management API

```
GET /v1/projects/7/forms/SITE01_DS_WHOVA2022/submissions
```

```json
[
  {
    "instanceId": "uuid:a1b2c3d4-5678-4abc-def0-1234567890ab",
    "submitterId": 42,
    "reviewState": "hasIssues",
    "createdAt": "2025-09-10T08:30:00.000Z",
    "updatedAt": "2025-11-15T14:22:00.000Z",
    "deletedAt": null,
    "currentVersion": {
      "instanceId": "uuid:f9e8d7c6-b5a4-3210-fedc-ba9876543210",
      "instanceName": "SITE01_2025_001_MARY_WHOVA2022",
      "submitterId": 55,
      "current": true,
      "createdAt": "2025-11-15T14:22:00.000Z"
    }
  }
]
```

Takeaways:

- Top-level `instanceId` — **the stable key**, same value as OData `__id`.
- `currentVersion.instanceId` — **the current revision's UUID**, same as OData
  `meta.instanceID`.
- The REST API exposes the version history through `currentVersion` (and
  `versions[]` on the detail endpoint) but still anchors identity on the stable
  top-level `instanceId`.

Extended metadata (header `X-Extended-Metadata: true`) enriches the submitter
and device information but does not change the identity fields.

### 3. XML download — the raw form data

```
GET /v1/projects/7/forms/SITE01_DS_WHOVA2022/submissions/{KEY}.xml
```

```xml
<data id="SITE01_DS_WHOVA2022" version="SITE01_DS_WHOVA2022_20250625_1">
  <start>2025-09-10T14:00:00.000+05:30</start>
  <end>2025-09-10T14:25:00.000+05:30</end>
  <unique_id>SITE01_2025_001_MARY</unique_id>
  <!-- ... hundreds of form fields ... -->

  <meta>
    <audit>audit.csv</audit>
    <instanceID>uuid:f9e8d7c6-b5a4-3210-fedc-ba9876543210</instanceID>
    <instanceName>SITE01_2025_001_MARY_WHOVA2022</instanceName>
    <deprecatedID>uuid:a1b2c3d4-5678-4abc-def0-1234567890ab</deprecatedID>
  </meta>
</data>
```

Takeaways:

- `meta/instanceID` — the **current revision** UUID (same as OData
  `meta.instanceID` and REST `currentVersion.instanceId`).
- `meta/deprecatedID` — the **previous revision** UUID. This is the *only*
  place where the old ID is visible. Not available in OData or REST.
- There is **no `__id`-equivalent** in the XML. The stable key is only
  recoverable from `deprecatedID` for the very first edit — after multiple edits,
  `deprecatedID` points to the *previous* `instanceID`, not the original `__id`.

---

## Visual cheat sheet

```
                        FRESH SUBMISSION           AFTER EDIT
                        ─────────────────          ─────────────────

OData  __id             uuid:a1b2...               uuid:a1b2...     (stable)
       meta.instanceID  uuid:a1b2...               uuid:f9e8...     (changed!)

REST   instanceId       uuid:a1b2...               uuid:a1b2...     (stable)
       currentVersion.  uuid:a1b2...               uuid:f9e8...     (changed!)
         instanceId

XML    meta/instanceID  uuid:a1b2...               uuid:f9e8...     (changed!)
       meta/deprecated  (absent)                   uuid:a1b2...     (previous)
```

---

## OData quirks and limitations

OData is the most efficient way to pull submission data — it returns flat,
paginated JSON with all form fields. But it has important gaps and quirks that
the official docs don't shout about.

### Repeat groups: three ways to get them, none perfect

By default (no `$expand`), the OData `Submissions` endpoint **flattens**
form groups into top-level leaf keys — equivalent to `groupPaths=false` in CSV
exports. Repeat groups are simply **omitted** from the response.

You have three options for getting repeat data:

**Option A: `$expand=*`** (since ODK Central v1.2)

```
GET .../svc/Submissions?$expand=*
```

Expands all repeat repetitions inline as nested JSON arrays. This gets you
everything in one call, but the response can be **much** larger — every repeat
row is embedded inside its parent submission. For forms with many repeats, this
can be expensive.

**Option B: Separate navigation queries**

Repeat groups are exposed as separate OData "sub-tables". You query them
individually:

```
GET .../svc/Submissions.repeat_group_name
```

Each sub-table row includes a reference back to its parent submission. You
reconstruct the hierarchy client-side. More calls, but each call is smaller
and you can filter/sort the repeats independently.

**Option C: Fall back to XML**

The XML download always contains the full hierarchical structure. No
reconstruction needed, but you have to parse XML.

**Important restriction:** `$select` and `$expand` **cannot be used together**.
If you need both field projection and repeat expansion, you are out of luck —
you have to take the full payload.

### `$filter` only works on metadata fields

You might expect to filter by any form field. You cannot. ODK Central's OData
only supports `$filter` on these fields:

| What | REST API name | OData field name |
|---|---|---|
| Submission ID | `instanceId` | `__id` |
| Submitter Actor ID | `submitterId` | `__system/submitterId` |
| Submission Timestamp | `createdAt` | `__system/submissionDate` |
| Update Timestamp | `updatedAt` | `__system/updatedAt` |
| Review State | `reviewState` | `__system/reviewState` |
| Delete Timestamp | `deletedAt` | `__system/deletedAt` |

All form fields (name, age, unique_id, etc.) are **non-filterable**. The
`$metadata` document confirms this via `NonFilterableProperties` annotations.

This is why delta sync must use timestamps rather than field-level criteria —
you can only say "give me submissions updated after X", never "give me
submissions where village = Nairobi".

### `$select` has limitations

`$select` lets you choose which fields to return (reducing payload size):

```
GET .../svc/Submissions?$select=__id,meta/instanceID,__system/updatedAt
```

But:

- Child properties of repeats **cannot** be selected with `$select`.
- `$select` and `$expand` **cannot be used together**.

### `$orderby` only works on metadata fields

Same restriction as `$filter` — you can only sort on the six metadata fields
listed above. You cannot sort by form field values.

### Paging with `$skiptoken` (since v2023.4)

If `$top` is provided, the response includes `@odata.nextLink` containing a
`$skiptoken` — an opaque cursor. This gives **consistent paging** even while
new submissions are being created mid-sync. Use it as-is for the next page.
Do not try to construct or parse `$skiptoken` yourself.

### No attachment metadata

OData rows do not tell you how many attachments a submission has, or whether
they are all present. You need the REST attachment endpoint:

```
GET /v1/projects/7/forms/SITE01_DS_WHOVA2022/submissions/{instanceId}/attachments
```

### No edit count, no deprecatedID

OData returns the **current** state of the submission only. There is no way to
see what changed between revisions, when each edit happened, or who made it.
The REST `versions[]` endpoint provides this. OData also has no `deprecatedID`
— you can infer that a submission was edited by checking if
`__id != meta.instanceID`, but you cannot see the chain of previous revisions.

### No submitter or device information in the basic response

The basic OData response includes `__system/submitterName` and
`__system/reviewState` but not `submitterId` or `deviceId`. The REST endpoint
with `X-Extended-Metadata: true` is needed for those.

### Review state comments are invisible to `updatedAt`

Adding or reading review comments does **not** change `__system/updatedAt`.
ODK only bumps `updatedAt` for data-XML edits. Comment changes are therefore
invisible to a delta sync based on timestamps.

### `$metadata` — the schema document

```
GET .../svc/$metadata
```

Returns EDMX CSDL XML describing the form schema. Groups are `ComplexType`s,
repeats are `EntityType`s (with their own primary keys). The `Submissions`
entity type has `__id` as its `<Key>`. This document is the authoritative
source for which fields are filterable, sortable, and expandable — but for
schemas you already know, there is little reason to fetch it.

### The `$metadata` identity revelation

The metadata document explicitly confirms what we have been saying:

```xml
<EntityType Name="Submissions">
  <Key><PropertyRef Name="__id"/></Key>
  <Property Name="__id" Type="Edm.String"/>
  <Property Name="meta" Type="org.opendatakit.user.simple.meta"/>
  ...
</EntityType>
<ComplexType Name="meta">
  <Property Name="instanceID" Type="Edm.String"/>
</ComplexType>
```

`__id` is the **entity key** (primary key). `meta.instanceID` is just a
string property nested inside a complex type. OData itself treats them
differently — `__id` is the identity, `instanceID` is data.

---

## Recommended strategy: efficient sync pipeline

The goal: detect what changed, download only what you need, and enrich each
changed submission with metadata that OData does not provide — while minimising
HTTP calls and data transfer.

### Phase 1 — Detect deltas (cheap, no form data transferred)

```
GET .../svc/Submissions?$filter=
    (__system/submissionDate gt {since})
    or (__system/updatedAt gt {since})
    &$top=0&$count=true
```

This returns **only a count** — zero bytes of form data. If the count is zero,
nothing changed since your last sync timestamp. Skip the form entirely.

Store a `last_synced_at` timestamp per form after each successful sync. Use the
most recent `__system/updatedAt` across all synced submissions as the next
`since` value.

**Why both `updatedAt` AND `submissionDate`?** New submissions have no
`updatedAt`, so filtering on `submissionDate` alone catches fresh ones. But
edits only bump `updatedAt`, not `submissionDate`. You need both in the filter.

**Fallback: gap detection.** If the delta check fails or times out, compare
ODK's ID listing against your local keys:

```
GET .../submissions                                    # REST listing, IDs only
```

Build the set of expected local keys. Any ODK ID not in your local set is a
gap — fetch those individually via single-entity OData calls.

### Phase 2 — Download changed payloads (bulk OData)

```
GET .../svc/Submissions?$top=250&$skip=0
    &$filter=(__system/submissionDate gt {since})
            or (__system/updatedAt gt {since})
```

Page through in batches (250 is a good page size). Each page returns full OData
records with all flattened form fields. Normalise each record:

```
__id                     → stable identity (your primary key)
__system.submissionDate  → when the submission first arrived
__system.updatedAt       → when it was last edited
__system.reviewState     → current review state
meta.instanceName        → human-readable label
meta.instanceID          → volatile revision token (do NOT key on this)
```

For gap-synced submissions, use single-entity OData fetches:

```
GET .../svc/Submissions('{instanceId}')
```

### Phase 3 — Enrich each changed submission (targeted REST + XML)

For every submission that was inserted or updated, make three follow-up calls
to fill in what OData omits:

**a) Extended metadata** (REST + `X-Extended-Metadata` header):

```
GET .../submissions/{instanceId}
Header: X-Extended-Metadata: true
```

Returns: `submitterId`, `deviceId`, `currentVersion.instanceId` (the mutable
instanceID), `reviewState`, `instanceName`.

**b) XML** (for form version and device ID):

```
GET .../submissions/{instanceId}.xml
```

Returns: `FormVersion` (the `version` attribute on the root `<data>` element),
`DeviceID` (from `<deviceid>`), and the full hierarchical form data including
repeat groups if you need them.

**c) Attachments** (for attachment counts):

```
GET .../submissions/{instanceId}/attachments
```

Returns: list of expected attachments with names and sizes, letting you compute
attachment counts.

### Traffic budget per sync

| Scenario | Delta check | OData download | Enrichment calls |
|---|---|---|---|
| No changes | 1 call, ~100 bytes | 0 | 0 |
| 10 submissions changed | 1 call | ~1 page (1 call) | 10 × 3 = 30 calls |
| First sync, 500 submissions | 0 (skip delta) | ~2 pages | 500 × 3 = 1500 calls |
| Gap check, 5 missing | 1 call (delta=0) | 5 single-entity calls | 5 × 3 = 15 calls |

The enrichment calls are per-submission and cannot be batched — this is the
main cost. Enrichment should therefore only run for submissions that are
genuinely new or changed, not for the full dataset on every sync.

### Handling edits to submissions in active workflows

When a submission that is already being processed receives an ODK edit, you
have a conflict: the local workflow state may depend on the old data.

Recommended approach:

1. Detect the change through normal delta sync (OData `updatedAt` changes).
2. Compare the incoming payload fingerprint against the stored payload
   (excluding volatile metadata like `instanceID`, `ReviewState`, `updatedAt`).
3. If the **data** changed (not just metadata), create a pending upstream
   version and flag the submission as `upstream_changed`.
4. Do **not** automatically overwrite the payload while someone is working on
   it. Surface the conflict for manual resolution.

---

## Common pitfalls

1. **Confusing `__id` with `instanceID` in OData responses.**
   They have different values after an edit. Use `__id` for identity,
   `meta.instanceID` for revision tracking.

2. **Using `instanceID` as a primary key.**
   It changes on edits. You will get duplicate rows after edits if you key on it.

3. **Assuming the REST listing `instanceId` equals `meta.instanceID`.**
   They are different fields with different semantics. The REST top-level
   `instanceId` is the stable key; `currentVersion.instanceId` is the revision
   token.

4. **Expecting `deprecatedID` to be the original `__id` after multiple edits.**
   After the second edit, `deprecatedID` points to the *first edit's*
   `instanceID`, not the original `__id`. Only OData `__id` or REST top-level
   `instanceId` reliably gives you the original.

5. **Filtering by form fields in OData `$filter`.**
   Only the six metadata fields (`__id`, `__system/submitterId`,
   `__system/submissionDate`, `__system/updatedAt`, `__system/reviewState`,
   `__system/deletedAt`) are filterable. All form fields are non-filterable.

6. **Using `$select` and `$expand` together.**
   ODK Central does not support this combination. Choose one or the other.

7. **Relying on `updatedAt` to detect review comment changes.**
   Review comments do not bump `updatedAt`. Only data-XML edits do.

8. **Assuming OData gives you the full picture.**
   Without `$expand=*`, repeat groups are omitted entirely. Even with it,
   OData lacks attachment metadata, version history, and `deprecatedID`.

---

## Quick reference: which identifier to use when

| You need to... | Use | API |
|---|---|---|
| Uniquely identify a submission | `__id` | OData |
| Detect if a submission was edited | `__id` ≠ `meta.instanceID` | OData |
| See the previous revision's ID | `deprecatedID` | XML |
| List all submission keys (lightweight) | `instanceId` array | REST listing |
| Fetch attachments for a submission | top-level `instanceId` | REST |
| Post a review state to ODK | top-level `instanceId` | REST |
| Get the current revision's instanceID | `currentVersion.instanceId` | REST |
| See full version history | `versions[]` | REST detail |
| Get hierarchical form data (repeat groups) | `$expand=*` | OData |
| Get hierarchical form data + deprecatedID | full XML | XML download |
