# Testing Strategy

## Overview
Comprehensive testing strategy for Session 04, establishing reusable fixtures, factory-style helpers, unit tests, integration tests, and security/RBAC test suites.

## Test Pyramid & Organization
- `tests/unit/`: Fast, isolated tests for domain workflow engines, shared package helpers, schemas, and utils.
- `tests/integration/`: End-to-end API route tests exercising database interactions, status flows, and raw normalization.
- `tests/auth/`: Positive and negative authentication and RBAC permission checks against the authorization matrix.
- `tests/fixtures/`: Reusable factory helpers and pytest fixtures for generating test users, tokens, projects, tasks, and workspaces.

## Testing SLOs
- Core domain workflows and RBAC matrix rules must have both positive and negative test coverage.
- Tests run against isolated PostgreSQL test database instances.
