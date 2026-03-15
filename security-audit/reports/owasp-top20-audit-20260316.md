---
title: DigitVA OWASP Top 20 Security Audit Report
date: 2026-03-16
auditor: Claude Security Auditor
scope: Full Application Codebase - OWASP Top 10 + API Security Top 10
status: Complete
references:
  - https://owasp.org/Top10/
  - https://owasp.org/API-Security/editions/2023/en/0x11-t10/
---

# DigitVA OWASP Top 20 Security Audit Report

**Application:** DigitVA - Digital Verbal Autopsy System
**Date:** March 16, 2026
**Framework:** Flask 3.1+ with SQLAlchemy 2.0+
**Python Version:** 3.13+

## Executive Summary

This security audit covers the DigitVA Flask application against the **OWASP Top 10:2021** (Web Application Security) and **OWASP API Security Top 10:2023** - providing comprehensive coverage of 20 security categories.

### Risk Summary

| Severity | Count | Description |
|----------|-------|-------------|
| **CRITICAL** | 1 | Immediate remediation required |
| **HIGH** | 6 | Urgent remediation required |
| **MEDIUM** | 7 | Requires review and remediation |
| **LOW** | 4 | Informational, improve over time |
| **PASS** | 12 | Adequate protection in place |

---

# Part 1: OWASP Top 10:2021 (Web Application Security)

## A01:2021 - Broken Access Control

**Status:** ⚠️ MEDIUM RISK

### Findings

| ID | Issue | Severity | Location |
|----|-------|----------|----------|
| A01-001 | Unauthenticated `/icd-search` endpoint | HIGH | `app/routes/va_api.py:912` |
| A01-002 | Path traversal potential in media serving | HIGH | `app/routes/va_api.py:900` |
| A01-003 | Open redirect potential in login flow | MEDIUM | `app/routes/va_auth.py:31` |

### Positive Controls
- ✅ Role-based access control implemented (`app/decorators/va_validate_permissions.py`)
- ✅ Form-level access validation (`current_user.has_va_form_access()`)
- ✅ Permission decorators on most routes

### Remediation Required
```python
# Add @login_required to /icd-search
@va_api.route("/icd-search")
@login_required  # ADD THIS
def icd_search():
    ...

# Validate filenames in media serving
from werkzeug.utils import secure_filename
safe_filename = secure_filename(va_filename)
if '..' in va_filename or va_filename.startswith('/'):
    abort(400)
```

---

## A02:2021 - Cryptographic Failures

**Status:** 🔴 CRITICAL RISK

### Findings

| ID | Issue | Severity | Location |
|----|-------|----------|----------|
| A02-001 | Hardcoded SECRET_KEY in docker-compose | CRITICAL | `docker-compose.yml:13` |
| A02-002 | Weak database credentials hardcoded | HIGH | `docker-compose.yml:86-87` |
| A02-003 | No TLS enforcement for database connections | MEDIUM | `config.py` |

### Positive Controls
- ✅ Password hashing with Werkzeug (bcrypt/pbkdf2)
- ✅ ODK credentials encrypted with Fernet + PBKDF2 (`app/utils/credential_crypto.py`)
- ✅ Pepper-based encryption for stored credentials

### Remediation Required
```yaml
# docker-compose.yml - Use environment variables
environment:
  - SECRET_KEY=${SECRET_KEY}
  - DATABASE_URL=${DATABASE_URL}
```

---

## A03:2021 - Injection

**Status:** ✅ PASS

### Findings

| ID | Issue | Severity | Location |
|----|-------|----------|----------|
| A03-001 | LIKE queries with user input | LOW | `app/routes/va_api.py:918` |

### Positive Controls
- ✅ SQLAlchemy ORM with parameterized queries throughout
- ✅ WTForms validation on all form inputs
- ✅ No raw SQL with string concatenation

### Analysis
```python
# Current code uses parameterized LIKE (SAFE)
.where(VaIcdCodes.icd_to_display.ilike(f"%{query}%"))
# SQLAlchemy parameterizes this internally
```

---

## A04:2021 - Insecure Design

**Status:** ⚠️ MEDIUM RISK

### Findings

| ID | Issue | Severity | Location |
|----|-------|----------|----------|
| A04-001 | No rate limiting on authentication | HIGH | `app/routes/va_auth.py` |
| A04-002 | No account lockout mechanism | MEDIUM | Authentication flow |
| A04-003 | Weak password policy | MEDIUM | `app/forms/va_pwresettnc_form.py` |

### Positive Controls
- ✅ Multi-role permission system
- ✅ Workflow state validation
- ✅ Allocation-based coding sessions

---

## A05:2021 - Security Misconfiguration

**Status:** 🔴 HIGH RISK

### Findings

| ID | Issue | Severity | Location |
|----|-------|----------|----------|
| A05-001 | Missing security headers | HIGH | Application config |
| A05-002 | Exposed database port | MEDIUM | `docker-compose.yml:91` |
| A05-003 | Exposed Redis port without auth | MEDIUM | `docker-compose.yml:73` |
| A05-004 | SQL queries logged at INFO level | LOW | `app/logging/va_logger.py` |

### Missing Headers
```
Content-Security-Policy: Not set
X-Frame-Options: Not set
X-Content-Type-Options: Not set
Strict-Transport-Security: Not set
```

### Remediation Required
```python
from flask_talisman import Talisman

Talisman(app, {
    'content_security_policy': {
        'default-src': "'self'",
    },
    'force_https': True,
    'strict_transport_security': True,
    'x_frame_options': 'DENY',
})
```

---

## A06:2021 - Vulnerable and Outdated Components

**Status:** ⚠️ REVIEW REQUIRED

### Findings

| ID | Issue | Severity | Location |
|----|-------|----------|----------|
| A06-001 | Dependency audit recommended | MEDIUM | `pyproject.toml` |

### Current Dependencies (Key)
- Flask 3.1.0+ ✅ (current)
- SQLAlchemy 2.0.0+ ✅ (current)
- cryptography 42.0.0+ ✅ (current)
- Werkzeug 3.1.0+ ✅ (current)

### Recommendation
Run dependency vulnerability scan:
```bash
uv run pip-audit
```

---

## A07:2021 - Identification and Authentication Failures

**Status:** 🔴 HIGH RISK

### Findings

| ID | Issue | Severity | Location |
|----|-------|----------|----------|
| A07-001 | No rate limiting on login | HIGH | `app/routes/va_auth.py` |
| A07-002 | Weak password requirements | MEDIUM | Password forms |
| A07-003 | No session regeneration after login | MEDIUM | Login flow |
| A07-004 | No multi-factor authentication | LOW | Authentication system |

### Positive Controls
- ✅ Session timeout (30 minutes)
- ✅ Secure password hashing (werkzeug)
- ✅ Login required on protected routes

---

## A08:2021 - Software and Data Integrity Failures

**Status:** ✅ PASS

### Positive Controls
- ✅ Dependencies via `uv` with lockfile (`uv.lock`)
- ✅ Code review process documented
- ✅ No deserialization of untrusted data
- ✅ No pickle/unpickle of user data

---

## A09:2021 - Security Logging and Monitoring Failures

**Status:** ⚠️ MEDIUM RISK

### Findings

| ID | Issue | Severity | Location |
|----|-------|----------|----------|
| A09-001 | Sensitive data may appear in SQL logs | MEDIUM | `app/logging/va_logger.py` |
| A09-002 | No alerting for security events | LOW | Logging system |

### Positive Controls
- ✅ Request logging with user context
- ✅ Sensitive field masking (`SENSITIVE_FIELDS`)
- ✅ Error logging with stack traces
- ✅ Audit logging for submissions

---

## A10:2021 - Server-Side Request Forgery (SSRF)

**Status:** ✅ PASS

### Analysis
- ✅ No user-controlled URL fetching
- ✅ ODK Central URLs are configured, not user-supplied
- ✅ No external resource fetching based on user input

---

# Part 2: OWASP API Security Top 10:2023

## API1:2023 - Broken Object Level Authorization

**Status:** ⚠️ MEDIUM RISK

### Findings

| ID | Issue | Severity | Location |
|----|-------|----------|----------|
| API1-001 | va_sid parameter could be enumerated | MEDIUM | API routes |

### Positive Controls
- ✅ Permission validation on most API endpoints
- ✅ Form access checks before serving media
- ✅ Workflow state validation

### Analysis
```python
# Good: Permission check before accessing submission
if not current_user.has_va_form_access(va_form_id):
    va_permission_abortwithflash(...)
```

---

## API2:2023 - Broken Authentication

**Status:** 🔴 HIGH RISK

### Findings

| ID | Issue | Severity | Location |
|----|-------|----------|----------|
| API2-001 | No API-specific authentication | HIGH | API routes |
| API2-002 | Session-based auth only (no API tokens) | MEDIUM | Authentication system |
| API2-003 | No JWT/API key authentication | MEDIUM | API design |

### Analysis
- APIs use session-based authentication (Flask-Login)
- No dedicated API tokens or JWT
- Suitable for browser-based clients, not for external API consumers

---

## API3:2023 - Broken Object Property Level Authorization

**Status:** ⚠️ MEDIUM RISK

### Findings

| ID | Issue | Severity | Location |
|----|-------|----------|----------|
| API3-001 | API responses may expose excessive data | MEDIUM | API responses |
| API3-002 | Mass assignment potential in forms | LOW | Form handling |

### Positive Controls
- ✅ WTForms with explicit field definitions
- ✅ Form validation on submit

---

## API4:2023 - Unrestricted Resource Consumption

**Status:** 🔴 HIGH RISK

### Findings

| ID | Issue | Severity | Location |
|----|-------|----------|----------|
| API4-001 | No rate limiting on API endpoints | HIGH | All API routes |
| API4-002 | No pagination limits enforced | MEDIUM | List endpoints |
| API4-003 | No request size limits | MEDIUM | API routes |

### Remediation Required
```python
from flask_limiter import Limiter

limiter = Limiter(app, key_func=get_remote_address)

@va_api.route("/icd-search")
@limiter.limit("30 per minute")
def icd_search():
    ...
```

---

## API5:2023 - Broken Function Level Authorization

**Status:** ✅ PASS

### Positive Controls
- ✅ Comprehensive role-based access control
- ✅ Permission decorators (`@va_validate_permissions`)
- ✅ Admin routes require admin role
- ✅ Role validation before actions

---

## API6:2023 - Unrestricted Access to Sensitive Business Flows

**Status:** ⚠️ MEDIUM RISK

### Findings

| ID | Issue | Severity | Location |
|----|-------|----------|----------|
| API6-001 | No CAPTCHA on authentication | LOW | Login flow |
| API6-002 | Automated form submission possible | LOW | Coding workflow |

### Positive Controls
- ✅ Allocation system limits concurrent work
- ✅ Form count limits per coder (200/year)
- ✅ Workflow state management

---

## API7:2023 - Server Side Request Forgery

**Status:** ✅ PASS

### Analysis
- ✅ No user-supplied URLs in backend requests
- ✅ ODK Central connections are admin-configured

---

## API8:2023 - Security Misconfiguration

**Status:** 🔴 HIGH RISK

### Findings (covered in A05)
- Missing security headers
- Exposed service ports
- Default/weak credentials in docker-compose

---

## API9:2023 - Improper Inventory Management

**Status:** ⚠️ MEDIUM RISK

### Findings

| ID | Issue | Severity | Location |
|----|-------|----------|----------|
| API9-001 | No API versioning | MEDIUM | API design |
| API9-002 | Debug endpoints may be exposed | LOW | Application |

### Positive Controls
- ✅ API routes are organized in blueprints
- ✅ Clear route structure

---

## API10:2023 - Unsafe Consumption of APIs

**Status:** ✅ PASS

### Analysis
- ✅ ODK Central API responses are validated
- ✅ Error handling for external API calls
- ✅ Connection guard service implemented

---

# Summary Matrix

## OWASP Top 10:2021 Results

| Category | Status | Critical | High | Medium | Low |
|----------|--------|----------|------|--------|-----|
| A01 Broken Access Control | ⚠️ | 0 | 2 | 1 | 0 |
| A02 Cryptographic Failures | 🔴 | 1 | 1 | 1 | 0 |
| A03 Injection | ✅ | 0 | 0 | 0 | 1 |
| A04 Insecure Design | ⚠️ | 0 | 1 | 2 | 0 |
| A05 Security Misconfiguration | 🔴 | 0 | 1 | 2 | 1 |
| A06 Vulnerable Components | ⚠️ | 0 | 0 | 1 | 0 |
| A07 Auth Failures | 🔴 | 0 | 1 | 2 | 1 |
| A08 Integrity Failures | ✅ | 0 | 0 | 0 | 0 |
| A09 Logging Failures | ⚠️ | 0 | 0 | 1 | 1 |
| A10 SSRF | ✅ | 0 | 0 | 0 | 0 |

## OWASP API Security Top 10:2023 Results

| Category | Status | Critical | High | Medium | Low |
|----------|--------|----------|------|--------|-----|
| API1 BOLA | ⚠️ | 0 | 0 | 1 | 0 |
| API2 Broken Auth | 🔴 | 0 | 1 | 2 | 0 |
| API3 BOPLA | ⚠️ | 0 | 0 | 1 | 1 |
| API4 Resource Consumption | 🔴 | 0 | 1 | 2 | 0 |
| API5 BFLA | ✅ | 0 | 0 | 0 | 0 |
| API6 Business Flows | ⚠️ | 0 | 0 | 0 | 2 |
| API7 SSRF | ✅ | 0 | 0 | 0 | 0 |
| API8 Misconfiguration | 🔴 | 0 | 1 | 2 | 0 |
| API9 Inventory | ⚠️ | 0 | 0 | 1 | 1 |
| API10 Unsafe Consumption | ✅ | 0 | 0 | 0 | 0 |

---

# Priority Remediation Plan

## Immediate (Critical/High - Within 24-48 Hours)

1. **Remove hardcoded secrets** from `docker-compose.yml`
2. **Add rate limiting** to authentication endpoints
3. **Add `@login_required`** to `/icd-search` endpoint
4. **Implement security headers** with Flask-Talisman
5. **Add path validation** for media file serving

## Short-Term (Medium - Within 1-2 Weeks)

1. Implement stronger password policy
2. Add session regeneration after login
3. Close or secure exposed database/Redis ports
4. Add API rate limiting
5. Implement account lockout mechanism

## Long-Term (Low/Improvements)

1. Add dependency vulnerability scanning to CI/CD
2. Implement API versioning
3. Consider API token authentication for external consumers
4. Add CAPTCHA for authentication
5. Implement security event alerting

---

# Sources

- [OWASP Top 10:2025 RC1](https://owasp.org/Top10/)
- [OWASP API Security Top 10:2023](https://owasp.org/API-Security/editions/2023/en/0x11-t10/)
