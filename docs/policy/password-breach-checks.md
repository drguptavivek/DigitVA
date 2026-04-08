---
title: Password Breach Check Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-08
---

# Password Breach Check Policy

## Purpose

DigitVA rejects user-chosen passwords that appear in known breach corpora. The goal is to reduce credential-stuffing risk without adding login-time friction.

## Scope

This policy applies to any flow where an operator or user sets a password that will be used for authentication:

- self-service password reset
- forced password change
- profile password update
- admin password edit
- CLI password reset / create flows that accept a user-entered password

Login verification itself is unchanged.

## Baseline Rules

- password strength validation remains mandatory
- breached passwords must be rejected using the Have I Been Pwned password range API and k-anonymity lookup
- the application must not transmit the full password to the breach service
- the application must not use breach checking as a login challenge or substitute for rate limiting
- if the breach service cannot be reached, the password change should fail with a retryable validation error rather than silently bypassing the check

## Privacy Rules

- only the SHA-1 prefix required by the k-anonymity API may leave the application
- no raw password, full hash, or account identity should be included in the breach lookup request

## Operational Notes

- breach checks are a defense-in-depth layer, not the primary authentication defense
- login rate limiting and account protection controls remain required
- the check may be disabled only in non-production test scaffolding or controlled operational exceptions
