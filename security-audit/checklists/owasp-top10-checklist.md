---
title: OWASP Top 10 (2021) Security Checklist
date: 2026-03-16
status: Active
owner: Security Team
---

# OWASP Top 10 (2021) Security Checklist

Use this checklist during code reviews and security assessments.

## A01:2021 - Broken Access Control

- [ ] All endpoints have appropriate authentication checks
- [ ] Role-based access control is enforced consistently
- [ ] User cannot access resources they don't own (IDOR protection)
- [ ] API endpoints validate user permissions before operations
- [ ] Directory traversal is prevented in file access
- [ ] CORS is configured properly
- [ ] Admin routes require admin role
- [ ] URL parameters are validated

### DigitVA Specific Checks

- [ ] `/icd-search` endpoint requires authentication
- [ ] Media file serving validates form access
- [ ] All `va_api` routes have `@login_required`
- [ ] Permission decorators are applied correctly

---

## A02:2021 - Cryptographic Failures

- [ ] Sensitive data is encrypted at rest
- [ ] TLS/HTTPS is enforced for all connections
- [ ] Passwords are hashed with strong algorithms (bcrypt, Argon2)
- [ ] No hardcoded secrets in source code
- [ ] Secrets are stored in environment variables or secret managers
- [ ] Encryption keys are rotated periodically
- [ ] Sensitive data is not logged

### DigitVA Specific Checks

- [ ] `SECRET_KEY` is not hardcoded
- [ ] ODK credentials use Fernet encryption with pepper
- [ ] Database passwords are not in docker-compose.yml
- [ ] Sensitive fields are masked in logs (`SENSITIVE_FIELDS`)

---

## A03:2021 - Injection

- [ ] All database queries use parameterized queries or ORM
- [ ] User input is sanitized before use in commands
- [ ] No raw SQL with string concatenation
- [ ] NoSQL injection is prevented if applicable
- [ ] LDAP injection is prevented if applicable
- [ ] Command injection is prevented

### DigitVA Specific Checks

- [ ] SQLAlchemy ORM is used (not raw SQL)
- [ ] LIKE queries use parameterized patterns
- [ ] No `os.system()` with user input
- [ ] Form validation with WTForms

---

## A04:2021 - Insecure Design

- [ ] Threat modeling is performed
- [ ] Security requirements are defined
- [ ] Rate limiting is implemented
- [ ] Business logic is validated
- [ ] Secure development lifecycle is followed

### DigitVA Specific Checks

- [ ] RBAC system is properly designed
- [ ] Workflow state transitions are validated
- [ ] Multi-step forms maintain state integrity

---

## A05:2021 - Security Misconfiguration

- [ ] Default credentials are changed
- [ ] Unnecessary features are disabled
- [ ] Error messages don't reveal sensitive info
- [ ] Security headers are set
- [ ] Debug mode is off in production
- [ ] Directory listing is disabled
- [ ] Cloud storage permissions are minimal

### DigitVA Specific Checks

- [ ] `DEBUG = False` in production
- [ ] Flask `SECRET_KEY` is unique and strong
- [ ] Security headers (CSP, X-Frame-Options, etc.) are set
- [ ] Database/Redis ports are not exposed externally

---

## A06:2021 - Vulnerable and Outdated Components

- [ ] Dependencies are regularly updated
- [ ] Vulnerability scanning is automated
- [ ] Unused dependencies are removed
- [ ] Components are from trusted sources
- [ ] End-of-life components are replaced

### DigitVA Specific Checks

- [ ] `uv lock` is up to date
- [ ] Run `pip-audit` or `safety check` regularly
- [ ] Python version is supported (3.13)

---

## A07:2021 - Identification and Authentication Failures

- [ ] Password strength requirements enforced
- [ ] Account lockout after failed attempts
- [ ] Session management is secure
- [ ] Multi-factor authentication available
- [ ] Password recovery is secure
- [ ] Session IDs are not in URLs
- [ ] Sessions expire appropriately

### DigitVA Specific Checks

- [ ] Password validation requires complexity
- [ ] Rate limiting on login endpoint
- [ ] Session lifetime is 30 minutes
- [ ] Session regeneration after login
- [ ] Remember me functionality is secure

---

## A08:2021 - Software and Data Integrity Failures

- [ ] CI/CD pipeline is secured
- [ ] Code reviews are required
- [ ] Dependencies are verified (SRI, signatures)
- [ ] Auto-update mechanisms are secure
- [ ] Deserialization of untrusted data is avoided

### DigitVA Specific Checks

- [ ] Dependencies via `uv` with lockfile
- [ ] No pickle/unpickle of user data
- [ ] Code changes require review

---

## A09:2021 - Security Logging and Monitoring Failures

- [ ] Authentication events are logged
- [ ] Access control failures are logged
- [ ] Input validation failures are logged
- [ ] Logs don't contain sensitive data
- [ ] Logs are protected from tampering
- [ ] Alerting is configured for anomalies

### DigitVA Specific Checks

- [ ] `SENSITIVE_FIELDS` masking is complete
- [ ] Request logging captures user context
- [ ] Error logging includes stack traces (internal only)
- [ ] SQL query logging doesn't log sensitive data

---

## A10:2021 - Server-Side Request Forgery (SSRF)

- [ ] User-supplied URLs are validated
- [ ] Internal network access is restricted
- [ ] URL schemes are whitelisted
- [ ] Response content is validated

### DigitVA Specific Checks

- [ ] ODK Central URLs are configured, not user-supplied
- [ ] No arbitrary URL fetching from user input

---

## Quick Reference: Security Headers

Ensure these headers are set:

```
Content-Security-Policy: default-src 'self'
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
```

## Quick Reference: Flask Security Config

```python
# Essential security settings
app.config['SESSION_COOKIE_SECURE'] = True  # HTTPS only
app.config['SESSION_COOKIE_HTTPONLY'] = True  # No JS access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['WTF_CSRF_TIME_LIMIT'] = None  # Or set appropriate limit
```
