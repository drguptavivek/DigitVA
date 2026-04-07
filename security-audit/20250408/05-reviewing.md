---
title: Security Audit — reviewing.py + api/reviewing.py
doc_type: security-report
status: draft
owner: vivek
last_updated: 2026-04-07
---

# `app/routes/reviewing.py` + `app/routes/api/reviewing.py` — Security Audit

## Routes Overview

### Page routes (`reviewing.py`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/reviewing/` | reviewer / admin (role_required) |
| GET | `/reviewing/submission/<va_sid>` | reviewer / admin |

### API routes (`api/reviewing.py`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/v1/reviewing/next` | reviewer / admin |
| POST | `/api/v1/reviewing/submit` | reviewer / admin |
| POST | `/api/v1/reviewing/release` | reviewer / admin |
| GET | `/api/v1/reviewing/progress` | reviewer / admin |

---

## No security findings

All reviewing routes are:

- Protected by `@role_required` with appropriate role values.
- Submission access validated through scope — a reviewer can only access submissions
  allocated to them.
- State transitions (`submit`, `release`) validated server-side; client cannot skip steps.
- No exception strings returned to clients.
- No raw SQL interpolation.

---

## Positive Controls Verified

- Role-based access enforced on all routes.
- Submission allocation scoped to `current_user` — no IDOR risk.
- Audit log entries created on review submission.
- CSRF token required on all POST routes (global Flask-WTF protection).
