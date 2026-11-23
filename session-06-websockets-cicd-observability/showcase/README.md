# Session 06 — Showcase

Placeholder for the Sessions 1–6 leadership showcase package.

## Slide Deck
Link or file (PPTX or PDF).

## Demo Index
| Member | Topic | Loom | Fallback |
|---|---|---|---|

## Live Demo Sequence
Order of the live demos and the fallback recording for each.

## Scorecard
Targets, workload and method, observed results, known limitations and top risks. See [`../docs/session-06/slo-and-deliverables.md`](../docs/session-06/slo-and-deliverables.md).

### WebSocket authorization baseline

| Measure | Observed result | Evidence |
|---|---:|---|
| Documented unauthorized cases rejected | 10/10 (100%) | `tests/unit/websockets/test_task_activity.py` |
| WebSocket security and lifecycle tests passed | 14/14 (100%) | `uv run pytest tests/unit/websockets/test_task_activity.py -q` |

This is an isolated protocol/RBAC test baseline using mocked repositories; it does not
measure Redis fan-out or live event delivery.

## Incident Summary
See [`../docs/session-06/incident-report.md`](../docs/session-06/incident-report.md).

## Key Session 1–6 PRs
PRs that show review discussions and changes made after feedback.
