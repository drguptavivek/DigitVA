---
title: Security Audit — va_auth.py
doc_type: security-report
status: draft
owner: vivek
last_updated: 2026-04-07
---

# `app/routes/va_auth.py` — Security Audit

## Routes Covered

| Method | Path | Auth | Rate Limit |
|--------|------|------|------------|
| GET/POST | `/valogin` | Anonymous | POST: 10/min |
| GET | `/valogout` | Any | None |
| GET/POST | `/forgot-password` | Anonymous | POST: 3/hr |
| GET/POST | `/reset-password/<token>` | Anonymous | 10/min (all) |
| GET | `/verify-email/<token>` | Anonymous | 10/min |
| GET/POST | `/resend-verification` | Anonymous | POST: 3/hr |

---

## SEC-004 — `reset-password` rate limit too permissive

**Severity:** MEDIUM  
**Route:** `GET/POST /reset-password/<token>`  
**Line:** 88

**Description:**  
The rate limit is `10 per minute` applied to all methods (GET + POST). This means an
attacker can make 600 POST attempts per hour against token-based endpoints. Password reset
tokens are time-limited but the brute-force window is unnecessarily large.

```python
@va_auth.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("10 per minute")   # ← applies to GET too; 600/hr window
def reset_password(token):
```

Compare with `forgot-password` which correctly applies `3 per hour, methods=["POST"]`.

**Recommendation:**  
- Change to `@limiter.limit("5 per minute", methods=["POST"])` to match the intent.
- Alternatively add a per-IP daily cap.

---

## SEC-005 — `verify-email` rate limit too permissive

**Severity:** MEDIUM  
**Route:** `GET /verify-email/<token>`  
**Line:** 140

**Description:**  
Same pattern as SEC-004. The `10 per minute` limit allows 600 token-probing requests per
hour against email-verification tokens. While tokens are cryptographically signed, the
exposure window is larger than necessary.

```python
@va_auth.route("/verify-email/<token>", methods=["GET"])
@limiter.limit("10 per minute")   # ← 600/hr enumeration window
def verify_email(token):
```

**Recommendation:**  
Lower to `3 per minute` or add a per-IP daily budget.

---

## SEC-006 — HTML injected into flash message via string `.format()`

**Severity:** MEDIUM  
**Route:** `POST /valogin`  
**Lines:** 32–38

**Description:**  
The flash message at login contains raw HTML built with `.format()`. The URL comes from
`url_for()` which is safe, but the pattern mixes HTML into Python string formatting.
If this pattern is replicated elsewhere with user-supplied values it becomes an XSS vector.
Templates that render flash messages must mark them `|safe` to show the link, which disables
Jinja2 auto-escaping for the entire message.

```python
flash(
    'Please verify your email address before logging in. '
    '<a href="{}">Resend verification email</a>.'.format(
        url_for("va_auth.resend_verification")
    ),
    "warning",
)
```

**Recommendation:**  
Move the resend link into the Jinja2 template conditional on the flash category, so no HTML
is ever passed through the Python flash system. Example:

```html
{% if category == 'warning' %}
  {{ message }} <a href="{{ url_for('va_auth.resend_verification') }}">Resend</a>.
{% else %}
  {{ message }}
{% endif %}
```

---

## SEC-013 — `valogout` has no CSRF protection (accepted)

**Severity:** INFO  
**Route:** `GET /valogout`  
**Line:** 52–58

**Description:**  
The logout route is a plain `GET` with no CSRF token. This means a malicious page can force
logout via `<img src="/valogout">` (CSRF-logout). This is a low-impact issue as it only
denies service (not escalates privilege) and is standard practice in many frameworks.

**Recommendation:**  
Convert to `POST` with a CSRF-protected form and redirect, or accept as an accepted risk
given the low impact.

---

## Positive Controls Verified

- **Email enumeration prevention:** `forgot_password` and `resend_verification` always
  return the same response regardless of whether the email exists (lines 77–83, 188–193).
- **Open-redirect prevention:** `next` parameter validated with `urlparse().netloc != ''`
  check (lines 44–46).
- **Constant-time password check:** `user.check_password()` uses Werkzeug's `check_password_hash`
  which is timing-safe.
- **No user enumeration on login:** invalid email and invalid password return the same flash
  message (line 23–27).
- **Token validation via `token_service`:** both password reset and email verify use a
  dedicated service that handles expiry.
