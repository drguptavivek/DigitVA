---
title: No Builds on Servers
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-23
---

# No Builds on Servers

Owner decision, 2026-10-23: nothing is built on staging or production hosts.

## Rule

- Servers run pinned, prebuilt artifacts only: the Docker image from GHCR
  (`ghcr.io/drguptavivek/digitva-app:<full git sha>`, built by the
  `Server images` workflow), the Expo web export and the SmartVA engine (pinned,
  checksummed release assets baked into that image in CI), and the Android APK
  (built in CI or locally).
- Servers run no `docker build`, `docker compose build`, `make prod-build`,
  Node, Rust or Gradle. A deploy is `scripts/deploy-server.sh <sha>`
  (`make prod-pull`); a rollback is `make prod-rollback TAG=<sha>`.
- The image tag is the git sha of the commit checked out on the host, because
  the checkout is bind-mounted into the app, worker and beat.
- `make prod-build` / `prod-rebuild` exist for developers and emergencies
  only, with the owner's approval.

## Why

A server build on 2026-10-23 left 13 GB of build cache and filled the 29 GB
staging disk. Builds also made deploys slow, non-reproducible and dependent on
the host's network and disk.

Runbook: [Split Production Deploy](../current-state/split-production-deploy.md).
Image sources: [Runtime and Operations](../current-state/runtime-and-operations.md#image-sources).
