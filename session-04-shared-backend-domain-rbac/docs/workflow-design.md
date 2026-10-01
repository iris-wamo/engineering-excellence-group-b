# Domain Workflow Design

## Overview
This document outlines the domain workflow implementation (e.g. Task Status Transition Engine or Assignment Policy Engine).

## Domain Rules
- Tasks transition strictly along allowed paths:
  `todo` → `in_progress` → `review` → `done`
- Invalid transitions must fail with consistent error models.
- Transitions must record activity/history trails where applicable.
- Assignment policies enforce role-based boundaries (e.g. managers assign tasks within workspace, members update status only for assigned tasks).

## Architecture & Integration
- Location: `app/workflows/`
- Service coordination: Services invoke workflow engines rather than performing ad-hoc status/field updates.
- Persistence & Audit: State changes are persisted atomically with audit history entries.
