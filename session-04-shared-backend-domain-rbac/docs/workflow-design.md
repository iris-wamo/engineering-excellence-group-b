# Domain Workflow Design

## Overview
This document outlines the domain workflow implementation (e.g. Task Status Transition Engine or Assignment Policy Engine).

## Domain Rules
- Tasks transition along the business workflow path:
  `todo` → `in_progress` → `review` → `done`
- Adjacent reverse moves are intentionally allowed so a task can be corrected or reopened without breaking the workflow entirely:
  `in_progress` → `todo` and `review` → `in_progress`
- Non-adjacent or skipping transitions remain invalid (for example, `todo` → `done` still fails).
- Invalid transitions must fail with consistent error models.
- Transitions must record activity/history trails where applicable.
- Assignment policies enforce role-based boundaries (e.g. managers assign tasks within workspace, members update status only for assigned tasks).

This rule balances process discipline with real-world task management: teams can move work backward when it was started prematurely or needs rework, but they cannot bypass required checkpoints by jumping ahead or skipping the normal sequence.

## Architecture & Integration
- Location: `app/workflows/`
- Service coordination: Services invoke workflow engines rather than performing ad-hoc status/field updates.
- Persistence & Audit: State changes are persisted atomically with audit history entries.
