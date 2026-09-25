---
card_id:
title: "rate-limit-login — Rate-limit the login endpoint"
status: backlog
priority: high
size: M
difficulty: medium
model_exec: sonnet
model_review: opus
repos: my-app
branch:
depends_on:
epic: auth-hardening
updated: 2026-01-15
type: task
origin: plan
---

# Rate-limit the login endpoint

<!-- An example task doc, the format `/plan` writes and `/dotask` executes.
     Save it as <vault.cards>/<slug>.md; the file name is the id. -->

## What

`POST /api/login` answers 429 after 5 failed attempts per account per 15 minutes, with a
`Retry-After` header.

## Why

Credential-stuffing bursts showed up in last week's logs; today the endpoint has no limit
at all.

## Acceptance criteria

- [ ] 5 failed attempts for the same account → the 6th returns 429 with `Retry-After`
      (verify: `npm test -- login.rate-limit`).
- [ ] A successful login resets the counter (same test file).
- [ ] The limit is per account, not per IP: two accounts from one IP are independent.
- [ ] No change to the response shape of a successful login (the mobile client depends on it).

## Technical notes

- Entry point: `src/api/auth/login.ts:42` (`handleLogin`).
- A rate-limit helper already exists for the password-reset route: `src/api/lib/limiter.ts`.
- Collision: `harden-session-cookies` also touches `login.ts` — not in the same batch.

## Current state

Not started.

## Links

- Related: harden-session-cookies

## Session log

### 2026-01-15 — created by /plan

- **Changed:** task created from the incident review.
