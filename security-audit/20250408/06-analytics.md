---
title: Security Audit — api/analytics.py
doc_type: security-report
status: draft
owner: vivek
last_updated: 2026-04-07
---

# `app/routes/api/analytics.py` — Security Audit

## Routes Overview

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/v1/analytics/summary` | role_required (varies) |
| GET | `/api/v1/analytics/submissions` | role_required |
| GET | `/api/v1/analytics/coders` | role_required |
| GET | `/api/v1/analytics/timeline` | role_required |

(Exact role requirements depend on blueprint registration — verified as requiring login.)

---

## SEC-011 — Cache invalidation failures silently swallowed

**Severity:** LOW  
**File:** `api/analytics.py`  
**Lines:** ~134–138

**Description:**  
`_bust_user_analytics_cache()` catches all exceptions and logs a warning without re-raising.
If Redis is temporarily unavailable or the cache key format changes, stale analytics data
continues to be served without any user-visible indication.

```python
except Exception as exc:
    log.warning(
        "Could not bust %s cache for user %s: %s",
        cache_prefix, uid, exc, exc_info=True
    )
    # ← exception swallowed; stale data served silently
```

**Risk:** Low — this is a data freshness issue, not a security vulnerability per se.
However, if an admin revokes a user's access and the analytics cache is not busted, the
next analytics request from that user may still succeed with cached scope.

**Recommendation:**  
After a permission change that alters a user's scope, verify cache is busted or fall back to
a version-counter approach (increment a user-level cache version key so all cached responses
are automatically invalidated without having to enumerate them).

---

## Positive Controls Verified

- All routes require authentication/role.
- Analytics scope is derived from `current_user` — no cross-user data leakage.
- Cache keys are per-user — no shared cache poisoning risk.
- No raw SQL interpolation found.
