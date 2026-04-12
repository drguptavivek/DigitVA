---
title: Email Delivery Resilience Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-12
---

# Email Delivery Resilience Policy

## Purpose

Define safe operational behavior for outbound authentication emails
(verification and password reset) to avoid SMTP provider abuse, bounce storms,
and accidental delivery from tests.

## Scope

Applies to:

- verification emails
- password reset/setup emails
- Celery email dispatch in `app/services/email_service.py`

## Baseline Rules

1. Outbound delivery is controlled by `EMAIL_DELIVERY_ENABLED`.
2. In tests, real SMTP sends are suppressed with `MAIL_SUPPRESS_SEND=True`.
3. Permanent SMTP recipient failures (5xx, including `SMTPRecipientsRefused`)
   must not be retried.
4. Permanent recipient failures must be written to Redis/cache as a suppression
   entry using `EMAIL_SUPPRESSION_CACHE_PREFIX` and
   `EMAIL_SUPPRESSION_TTL_SECONDS`.
5. While a suppression entry exists, further sends to that recipient are
   skipped at both enqueue-time and task execution time.
6. Transient SMTP failures remain retryable via Celery task retries.

## Operational Notes

- Suppression entries are TTL-bound and expire automatically.
- Suppression cache read/write failures must fail open (do not break request
  flow), with warning logs for observability.
- This policy does not change account security behavior: users still require
  verification and password setup to complete onboarding.
