---
card_id:
title: "kelvin-support — Add Kelvin conversions"
status: backlog
priority: normal
size: S
difficulty: low
model_exec: sonnet
model_review: sonnet
repos: tempconv-demo
branch:
depends_on:
updated: 2026-01-15
type: task
origin: plan
---

# Add Kelvin conversions

## What

`celsius_to_kelvin` and `kelvin_to_celsius` in `tempconv`, rejecting temperatures below
absolute zero with `ValueError`.

## Why

The demo task for trying the kitchen end to end: small, pure logic, TDD-friendly.

## Acceptance criteria

- [ ] `celsius_to_kelvin(0) == 273.15` (verify: `python3 -m pytest -q`).
- [ ] `kelvin_to_celsius(-0.01)` raises `ValueError`; `kelvin_to_celsius(0)` returns `-273.15`.
- [ ] Boundary covered: a test exactly at absolute zero and one just below it.

## Technical notes

- Entry point: `tempconv/__init__.py`.
- The adapter forbids `print(` in added code — the diff gate will catch it.

## Current state

Not started.

## Session log

### 2026-01-15 — created by /plan

- **Changed:** demo task.
