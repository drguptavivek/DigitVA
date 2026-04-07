---
title: Security Audit — config.py + app/__init__.py
doc_type: security-report
status: draft
owner: vivek
last_updated: 2026-04-07
---

# `config.py` + `app/__init__.py` — Security Audit

---

## SEC-002 — Hardcoded `SECRET_KEY` fallback

**Severity:** HIGH  
**File:** `config.py`  
**Line:** 26

**Description:**  
The Flask `SECRET_KEY` has a hardcoded fallback:

```python
SECRET_KEY = os.environ.get("SECRET_KEY") or "5Ag92#2g]oLIHEk"
```

If the `SECRET_KEY` environment variable is not set (e.g., missing `.env`, misconfigured
container), the application silently falls back to this known value. An attacker who knows
this fallback (it is in the source code) can:

- Forge Flask session cookies.
- Bypass CSRF token validation.
- Forge "remember me" cookies.

The `_require_env()` helper already exists in `config.py` (lines 12–19) for exactly this
purpose. The pattern for `ODK_CREDENTIAL_PEPPER` shows the correct model to follow.

**Recommendation:**  
Replace with:

```python
SECRET_KEY = _require_env("SECRET_KEY")
```

This causes the application to refuse to start if the key is absent, which is the correct
behaviour in both production and CI.

---

## SEC-003 — Hardcoded database URL fallback exposes credentials

**Severity:** HIGH  
**File:** `config.py`  
**Line:** 46–48

**Description:**  
```python
SQLALCHEMY_DATABASE_URI = (
    os.environ.get("DATABASE_URL")
    or "postgresql://minerva:minerva@localhost:5432/minerva"
)
```

The fallback URL contains username and password (`minerva:minerva`). If `DATABASE_URL` is
not set, the application connects to a local PostgreSQL instance with these credentials.
More importantly, the credentials are visible in source code.

**Risk assessment:** The fallback only matters in misconfigured environments. In Docker, the
`.env` file always provides `DATABASE_URL`. But the credentials appearing in source code
creates a risk if the repo is ever made public or if the credentials are reused.

**Recommendation:**  
```python
SQLALCHEMY_DATABASE_URI = _require_env("DATABASE_URL")
```

Or at minimum, use a placeholder that makes it obvious no default exists:

```python
SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or ""
```

If you need a development default, document it in `.env.example` only, not in `config.py`.

---

## SEC-008 — `unsafe-inline` in CSP `script-src`

**Severity:** MEDIUM  
**File:** `app/__init__.py`  
**Line:** 94

**Description:**  
```python
'script-src': "'self' 'unsafe-inline'",  # unsafe-inline needed for HTMX
```

`unsafe-inline` allows any inline `<script>` tag on the page to execute. This substantially
weakens XSS protection because browser-native XSS filtering (and modern CSP) becomes
ineffective even if an attacker injects a script tag via a stored XSS vulnerability.

**Recommendation (short-term):**  
Audit all inline scripts and move them to external `.js` files served from `'self'`. This
is the cleanest solution and also makes the codebase more maintainable.

**Recommendation (if inline scripts cannot be eliminated):**  
Use nonce-based CSP. Flask-Talisman supports nonce generation:

```python
talisman.init_app(app, content_security_policy={
    'script-src': "'self' 'nonce-{nonce}'",
    ...
})
```

Each inline script must then include the nonce attribute. HTMX itself does not require
`unsafe-inline` — only inline scripts used alongside HTMX do.

**Note:** `style-src: unsafe-inline` is also present. Same mitigation applies, though XSS
via CSS is less impactful.

---

## SEC-010 — `REMEMBER_COOKIE_DURATION` too short for "remember me"

**Severity:** LOW  
**File:** `config.py`  
**Line:** 28

**Description:**  
```python
REMEMBER_COOKIE_DURATION = timedelta(minutes=30)
```

"Remember me" cookies are typically expected to persist for days or weeks so users aren't
forced to log in on every browser restart. A 30-minute remember-me duration provides no
practical benefit over a session cookie and may confuse users who check "remember me"
expecting persistence.

**Recommendation:**  
Set to `timedelta(days=30)` if "remember me" is an intentional UX feature, or remove the
`remember_me` field from the login form if not needed.

---

## Positive Controls Verified

- `SESSION_COOKIE_HTTPONLY = True` — prevents JS access to session cookie.
- `SESSION_COOKIE_SECURE = True` — cookie only sent over HTTPS.
- `SESSION_COOKIE_SAMESITE = "Lax"` — CSRF protection for cookie-based state.
- `SESSION_USE_SIGNER = True` — session data cryptographically signed.
- `REMEMBER_COOKIE_HTTPONLY = True` + `REMEMBER_COOKIE_SECURE = True`.
- Flask-Talisman: HSTS (1 year), `X-Content-Type-Options: nosniff`, `X-XSS-Protection`,
  `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: strict-origin-when-cross-origin`.
- `ProxyFix` middleware for correct IP extraction behind a single reverse proxy.
- CSRF globally enabled via `CSRFProtect(app)` with `X-CSRFToken` header support.
- Per-user rate limiting (authenticated) + per-IP (anonymous).
- `_require_env()` helper exists and is already used for `ODK_CREDENTIAL_PEPPER` —
  needs to be applied to `SECRET_KEY` and `DATABASE_URL` as well.
- `TestConfig` never used in production (config selection is explicit in `create_app()`).
