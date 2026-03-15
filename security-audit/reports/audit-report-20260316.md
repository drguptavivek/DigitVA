---
title: DigitVA Security Audit Report
date: 2026-03-16
auditor: Claude Security Auditor
scope: Full Application Codebase
status: Complete
---

# DigitVA Security Audit Report

**Application:** DigitVA - Digital Verbal Autopsy System
**Date:** March 16, 2026
**Framework:** Flask 3.1+ with SQLAlchemy 2.0+
**Python Version:** 3.13+

## Executive Summary

This security audit covers the DigitVA Flask application, a medical data management system for verbal autopsies. The application handles sensitive PII (personally identifiable information) and medical records, making security paramount.

### Risk Summary

| Severity | Count | Status |
|----------|-------|--------|
| **CRITICAL** | 1 | Requires Immediate Action |
| **HIGH** | 4 | Requires Urgent Action |
| **MEDIUM** | 6 | Requires Review |
| **LOW** | 3 | Informational |

---

## CRITICAL Findings

### CRIT-001: Hardcoded Secrets in Docker Compose

**Risk Level:** CRITICAL
**CWE:** CWE-798 (Use of Hard-coded Credentials)
**OWASP:** A02:2021 - Cryptographic Failures

**Location:** `docker-compose.yml:13-14, 39-40, 58-59`

**Description:**
The docker-compose.yml file contains hardcoded sensitive credentials:

```yaml
environment:
  - SECRET_KEY=5Ag92#2g]oLIHEk
  - DATABASE_URL=postgresql://minerva:minerva@minerva_db_service:5432/minerva
```

The `SECRET_KEY` is hardcoded and identical across all services. The database credentials are also hardcoded with weak passwords (`minerva:minerva`).

**Attack Vector:**
An attacker with access to the repository can:
1. Forge session cookies using the known SECRET_KEY
2. Bypass CSRF protection
3. Access the database directly using exposed credentials

**Remediation:**
1. Remove all hardcoded secrets from docker-compose.yml
2. Use environment variables or Docker secrets:

```yaml
environment:
  - SECRET_KEY=${SECRET_KEY}
  - DATABASE_URL=${DATABASE_URL}
```

3. Create a `.env` file (already git-ignored) with actual secrets
4. Generate a strong SECRET_KEY: `python -c "import secrets; print(secrets.token_hex(32))"`

---

## HIGH Findings

### HIGH-001: Missing Rate Limiting

**Risk Level:** HIGH
**CWE:** CWE-770 (Allocation of Resources Without Limits)
**OWASP:** A07:2021 - Identification and Authentication Failures

**Location:** All authentication endpoints (`app/routes/va_auth.py`)

**Description:**
The application lacks rate limiting on authentication endpoints, making it vulnerable to:
- Brute force password attacks
- Credential stuffing
- DoS attacks

**Affected Endpoints:**
- `/valogin` - Login endpoint
- `/force-password-change` - Password reset

**Remediation:**
Implement rate limiting using Flask-Limiter:

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

@va_auth.route("/valogin", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def va_login():
    ...
```

---

### HIGH-002: Unauthenticated ICD Search Endpoint

**Risk Level:** HIGH
**CWE:** CWE-284 (Improper Access Control)
**OWASP:** A01:2021 - Broken Access Control

**Location:** `app/routes/va_api.py:912-924`, `app/routes/va_api2.py:330-338`

**Description:**
The `/icd-search` endpoint is accessible without authentication:

```python
@va_api.route("/icd-search")
def icd_search():
    query = request.args.get("q", "")
    results = db.session.execute(
        sa.select(VaIcdCodes.icd_code, VaIcdCodes.icd_to_display)
        .where(VaIcdCodes.icd_to_display.ilike(f"%{query}%"))
        .limit(20)
    ).all()
    ...
```

**Attack Vector:**
- Information disclosure of medical coding data
- Potential SQL injection via LIKE pattern (though SQLAlchemy parameterizes)
- Resource exhaustion through repeated queries

**Remediation:**
Add `@login_required` decorator:

```python
@va_api.route("/icd-search")
@login_required
def icd_search():
    ...
```

---

### HIGH-003: Missing Security Headers

**Risk Level:** HIGH
**CWE:** CWE-693 (Protection Mechanism Failure)
**OWASP:** A05:2021 - Security Misconfiguration

**Location:** `app/__init__.py`

**Description:**
The application does not set essential security headers:
- `Content-Security-Policy` (CSP)
- `X-Frame-Options`
- `X-Content-Type-Options`
- `Strict-Transport-Security` (HSTS)
- `X-XSS-Protection`

**Attack Vector:**
- Clickjacking attacks (missing X-Frame-Options)
- XSS attacks (missing CSP)
- MIME type sniffing attacks
- Man-in-the-middle attacks (missing HSTS)

**Remediation:**
Add security headers middleware:

```python
from flask_talisman import Talisman

# In create_app():
Talisman(app, {
    'content_security_policy': {
        'default-src': "'self'",
        'script-src': "'self'",
        'style-src': "'self' 'unsafe-inline'",
    },
    'force_https': True,
    'strict_transport_security': True,
    'x_content_type_options': True,
    'x_frame_options': 'DENY',
    'x_xss_protection': True,
})
```

---

### HIGH-004: Path Traversal Risk in Media Serving

**Risk Level:** HIGH
**CWE:** CWE-22 (Path Traversal)
**OWASP:** A01:2021 - Broken Access Control

**Location:** `app/routes/va_api.py:900-908`, `app/routes/va_api2.py:318-327`

**Description:**
The media serving endpoints construct paths using user-supplied `va_form_id` and `va_filename` without proper validation:

```python
@va_api.route('/vaservemedia/<va_form_id>/<va_filename>')
@login_required
def va_servemedia(va_form_id, va_filename):
    if not current_user.has_va_form_access(va_form_id):
        va_permission_abortwithflash(...)
    media_base = os.path.join(
        current_app.config["APP_DATA"], va_form_id, "media"
    )
    return send_from_directory(media_base, va_filename)
```

**Attack Vector:**
While `send_from_directory` provides some protection, an attacker could potentially:
1. Use path traversal in `va_filename` (e.g., `../../../etc/passwd`)
2. Access files outside the intended directory if `va_form_id` contains path separators

**Remediation:**
1. Validate `va_form_id` against a whitelist of valid form IDs
2. Sanitize `va_filename` to prevent path traversal:

```python
import os
from werkzeug.utils import secure_filename

@va_api.route('/vaservemedia/<va_form_id>/<va_filename>')
@login_required
def va_servemedia(va_form_id, va_filename):
    # Validate form_id format
    if not re.match(r'^[A-Za-z0-9_-]+$', va_form_id):
        abort(400, "Invalid form ID format")

    # Sanitize filename
    safe_filename = secure_filename(va_filename)
    if not safe_filename:
        abort(400, "Invalid filename")

    # Additional check to prevent path traversal
    if '..' in va_filename or va_filename.startswith('/'):
        abort(400, "Invalid filename")

    media_base = os.path.join(current_app.config["APP_DATA"], va_form_id, "media")
    return send_from_directory(media_base, safe_filename)
```

---

## MEDIUM Findings

### MED-001: Weak Password Policy

**Risk Level:** MEDIUM
**CWE:** CWE-521 (Weak Password Requirements)
**OWASP:** A07:2021 - Identification and Authentication Failures

**Location:** `app/forms/va_pwresettnc_form.py`, `app/models/va_users.py`

**Description:**
The password change form only requires:
- Password match confirmation
- DataRequired validation

No complexity requirements, minimum length, or common password checks are enforced.

**Remediation:**
Add password strength validation:

```python
from wtforms.validators import ValidationError
import re

def validate_password_strength(form, field):
    password = field.data
    if len(password) < 12:
        raise ValidationError('Password must be at least 12 characters long')
    if not re.search(r'[A-Z]', password):
        raise ValidationError('Password must contain at least one uppercase letter')
    if not re.search(r'[a-z]', password):
        raise ValidationError('Password must contain at least one lowercase letter')
    if not re.search(r'[0-9]', password):
        raise ValidationError('Password must contain at least one digit')
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise ValidationError('Password must contain at least one special character')
```

---

### MED-002: Session Configuration Issues

**Risk Level:** MEDIUM
**CWE:** CWE-613 (Insufficient Session Expiration)
**OWASP:** A07:2021 - Identification and Authentication Failures

**Location:** `config.py:24`

**Description:**
Session lifetime is set to 30 minutes, which is reasonable, but:
- No session regeneration after login
- No concurrent session limiting
- Session stored in SQLAlchemy without cleanup of expired sessions

```python
PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
```

**Remediation:**
1. Implement session regeneration after login:

```python
from flask import session
import secrets

@va_auth.route("/valogin", methods=["GET", "POST"])
def va_login():
    ...
    if user and user.check_password(form.password.data):
        session.clear()  # Clear old session data
        session.permanent = True
        session['session_id'] = secrets.token_hex(32)  # New session ID
        login_user(user, remember=form.remember_me.data)
```

2. Implement periodic cleanup of expired sessions in the database

---

### MED-003: Open Redirect Potential

**Risk Level:** MEDIUM
**CWE:** CWE-601 (URL Redirection to Untrusted Site)
**OWASP:** A01:2021 - Broken Access Control

**Location:** `app/routes/va_auth.py:31-35`

**Description:**
The login flow uses a `next` parameter for redirect:

```python
next_page = request.args.get('next')
if not next_page or urlparse(next_page).netloc != '':
    next_page = current_user.landing_url()
return redirect(next_page)
```

**Issue:**
The validation `urlparse(next_page).netloc != ''` prevents external redirects when there IS a netloc, but allows relative paths that could be manipulated.

**Remediation:**
Use Flask-Login's built-in `is_safe_url` or implement stricter validation:

```python
from urllib.parse import urlparse, urljoin

def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

next_page = request.args.get('next')
if not next_page or not is_safe_url(next_page):
    next_page = current_user.landing_url()
```

---

### MED-004: Database Exposed on Host Port

**Risk Level:** MEDIUM
**CWE:** CWE-284 (Improper Access Control)
**OWASP:** A05:2021 - Security Misconfiguration

**Location:** `docker-compose.yml:90-91`

**Description:**
PostgreSQL database port is exposed to the host:

```yaml
ports:
  - "8450:5432"
```

Combined with weak credentials (`minerva:minerva`), this allows direct database access from the host machine.

**Remediation:**
1. Remove port exposure if not needed for development
2. Use stronger database credentials
3. If port exposure is required, bind to localhost only:

```yaml
ports:
  - "127.0.0.1:8450:5432"
```

---

### MED-005: Redis Exposed Without Authentication

**Risk Level:** MEDIUM
**CWE:** CWE-284 (Improper Access Control)
**OWASP:** A05:2021 - Security Misconfiguration

**Location:** `docker-compose.yml:72-73`

**Description:**
Redis is exposed on port 6379 without authentication:

```yaml
minerva_redis_service:
  image: redis:7
  ports:
    - "6379:6379"
```

**Attack Vector:**
An attacker could access Redis to:
- Read/modify session data
- Inject malicious Celery tasks
- Access cached sensitive data

**Remediation:**
1. Remove port exposure if not needed
2. Enable Redis authentication:

```yaml
command: redis-server --requirepass ${REDIS_PASSWORD}
```

---

### MED-006: SQL Query Logging Enabled

**Risk Level:** MEDIUM
**CWE:** CWE-532 (Insertion of Sensitive Information into Log File)
**OWASP:** A09:2021 - Security Logging and Monitoring Failures

**Location:** `app/logging/va_logger.py:107-118`

**Description:**
SQL queries are logged at INFO level, which may include sensitive data:

```python
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
```

**Remediation:**
1. Set SQL logging to WARNING in production
2. Ensure log files have restricted permissions
3. Consider log rotation and retention policies

---

## LOW Findings

### LOW-001: Verbose Error Messages

**Risk Level:** LOW
**CWE:** CWE-209 (Generation of Error Message Containing Sensitive Information)
**OWASP:** A05:2021 - Security Misconfiguration

**Location:** Various route handlers

**Description:**
Some error messages may reveal internal application details. The error handler logs full exception information.

**Remediation:**
In production, return generic error messages to users while logging detailed errors server-side.

---

### LOW-002: Missing Account Lockout

**Risk Level:** LOW
**CWE:** CWE-307 (Improper Restriction of Excessive Authentication Attempts)
**OWASP:** A07:2021 - Identification and Authentication Failures

**Location:** `app/routes/va_auth.py`

**Description:**
No account lockout mechanism after failed login attempts.

**Remediation:**
Implement account lockout after N failed attempts (e.g., 5 failed attempts = 15-minute lockout).

---

### LOW-003: Debug Mode Considerations

**Risk Level:** LOW
**CWE:** CWE-215 (Insertion of Sensitive Information into Debugging Code)
**OWASP:** A05:2021 - Security Misconfiguration

**Location:** `config.py`

**Description:**
Ensure `DEBUG = False` in production. The test configuration has hardcoded test secrets.

**Remediation:**
Add explicit DEBUG=False check in production configuration.

---

## Positive Security Findings

The application implements several good security practices:

1. **CSRF Protection** - Flask-WTF CSRF is enabled (`app/__init__.py:43`)
2. **Password Hashing** - Uses Werkzeug's `generate_password_hash` / `check_password_hash` (bcrypt/pbkdf2)
3. **Credential Encryption** - ODK credentials are encrypted with Fernet + PBKDF2 (`app/utils/credential_crypto.py`)
4. **Sensitive Data Logging** - Passwords and tokens are masked in logs (`app/logging/va_logger.py:9, 77-79`)
5. **SQL Injection Prevention** - Uses SQLAlchemy ORM with parameterized queries
6. **Role-Based Access Control** - Comprehensive permission system (`app/decorators/va_validate_permissions.py`)
7. **Session Management** - Uses Flask-Session with SQLAlchemy backend
8. **Login Required** - Most routes are protected with `@login_required`

---

## OWASP Top 10 (2021) Compliance

| Category | Status | Notes |
|----------|--------|-------|
| A01: Broken Access Control | PARTIAL | ICD search unauthenticated, path traversal risk |
| A02: Cryptographic Failures | PARTIAL | Hardcoded secrets in docker-compose |
| A03: Injection | GOOD | SQLAlchemy ORM prevents SQL injection |
| A04: Insecure Design | GOOD | RBAC implemented |
| A05: Security Misconfiguration | PARTIAL | Missing security headers, exposed ports |
| A06: Vulnerable Components | REVIEW | Dependencies should be scanned |
| A07: Authentication Failures | PARTIAL | No rate limiting, weak password policy |
| A08: Software/Data Integrity | GOOD | Dependencies via uv with lockfile |
| A09: Logging/Monitoring Failures | PARTIAL | SQL queries log sensitive data |
| A10: SSRF | GOOD | No user-controlled URL fetching |

---

## Recommendations Summary

### Immediate Actions (Critical/High)
1. Remove hardcoded secrets from docker-compose.yml
2. Add rate limiting to authentication endpoints
3. Add `@login_required` to `/icd-search` endpoints
4. Implement security headers
5. Add path validation for media file serving

### Short-Term Actions (Medium)
1. Strengthen password policy
2. Fix open redirect validation
3. Remove or secure exposed database/Redis ports
4. Implement session regeneration

### Long-Term Actions (Low/General)
1. Implement account lockout
2. Add dependency vulnerability scanning
3. Security awareness training for developers
4. Regular penetration testing

---

## Appendix: Files Reviewed

- `app/__init__.py` - Application factory
- `app/routes/va_auth.py` - Authentication routes
- `app/routes/va_api.py` - API routes
- `app/routes/va_api2.py` - API routes (HTMX)
- `app/routes/admin.py` - Admin panel
- `app/routes/va_main.py` - Main routes
- `app/models/va_users.py` - User model
- `app/decorators/va_validate_permissions.py` - Permission decorators
- `app/utils/credential_crypto.py` - Credential encryption
- `app/logging/va_logger.py` - Logging configuration
- `config.py` - Configuration
- `docker-compose.yml` - Docker configuration
- `pyproject.toml` - Dependencies
- `.env.example` - Environment template
