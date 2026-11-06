---
card_id:
title: "rate-limit-login — Rate-limit the login endpoint"
status: in-progress
priority: high
size: M
difficulty: medium
model_exec: sonnet
model_review: opus
repos: my-app
branch: feat/rate-limit-login
depends_on:
epic: auth-hardening
updated: 2026-01-16
type: task
origin: plan
sync_pending: true
---

# Rate-limit the login endpoint

<!-- The same doc as task.md, after one /save at the end of a session: `updated` moved,
     `sync_pending: true` was set, Current state was rewritten, a Pending checklist appeared,
     and a new Session log entry went on TOP of the one /plan wrote. What /save leaves
     alone: What, Why, Acceptance criteria, Technical notes. Nothing was committed, pushed
     or sent to a tracker — `sync_pending` is the only signal that the tracker is behind.
     A later /resume reads Current state, Pending and the newest log entry. -->

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

The per-account counter works and the 6th attempt returns 429, but `Retry-After` is not set
yet and a successful login does not reset the counter. Work is on `feat/rate-limit-login`,
uncommitted in `src/api/auth/login.ts`.

## Pending

- [x] Reuse `limiter.ts` keyed by account id instead of IP.
- [ ] Set the `Retry-After` header from the limiter's reset time.
- [ ] Reset the counter on a successful login.
- [ ] Test: two accounts from one IP stay independent.

## Links

- Related: harden-session-cookies
- Repo: my-app

## Session log

### 2026-01-16 — saved by /save ⏳ to sync

- **Changed:** `src/api/auth/login.ts:58` calls the limiter per account; the 429 path
  returns a JSON body in the existing error shape.
- **Decisions:** key by account id, not by IP — an office behind one NAT must not lock
  everyone out; the criteria already say so.
- **Pending:** `Retry-After`, counter reset on success, the two-accounts test.

### 2026-01-15 — created by /plan

- **Changed:** task created from the incident review.
