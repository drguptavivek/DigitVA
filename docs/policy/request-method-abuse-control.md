---
title: Request Method Abuse Control Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-15
---

# Request Method Abuse Control Policy

## Purpose

DigitVA must detect and temporarily block IPs that repeatedly send mutating
requests to routes that do not accept those methods. The goal is to reduce
scanner and bot noise without changing normal application semantics.

## Baseline

Current baseline:

- only `405 Method Not Allowed` responses count toward this control
- only configured mutating methods count; the default tracked methods are
  `POST` and `PATCH`
- the control is IP-based and temporary; it is not a permanent denylist
- counters and ban windows must expire automatically without manual cleanup

## Trigger Rules

An IP must be temporarily blocked when all of the following are true:

- the request method is one of the configured tracked methods
- Flask/Werkzeug resolved the request as `405 Method Not Allowed`
- the number of qualifying requests from that IP reaches the configured
  threshold inside the configured rolling time window

Requests that return `404`, `400`, `401`, `403`, `429`, or `500` must not
count toward this method-abuse ban.

## Enforcement Rules

When an IP is temporarily blocked:

- the application must reject subsequent requests from that IP before normal
  route handling
- API and admin API paths must receive a JSON `403` response
- non-API paths may receive a plain `403` response
- the response must include `Retry-After` with the remaining temporary-ban
  duration

The `/health` endpoint and static asset requests may remain exempt from this
ban enforcement so operational health checks and asset serving do not become
coupled to abuse-control state.

## Operational Rules

- the control must be cache-backed so all app workers see the same temporary
  ban state
- ban events and blocked-request events must be logged with the IP, method,
  path, and ban timing context
- the control must be configurable with explicit settings for tracked methods,
  threshold, rolling window, ban duration, and cache-key prefixes
- test configuration must use separate cache-key prefixes from live runtime

## Non-Goals

This control does not replace:

- route-specific rate limits
- CSRF protection
- authentication or authorization
- upstream firewall or reverse-proxy blocking
