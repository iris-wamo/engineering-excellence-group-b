# Shared Package Notes (`taskflow_shared`)

## Overview
Documentation for the local installable package `taskflow_shared` located in `packages/taskflow_shared/`.

## Scope & Purpose
The shared backend package provides reusable foundations across TaskFlow modules without duplicating common infrastructure.

## Included Modules
- `config`: Common configuration abstractions
- `errors`: Standard exception classes and error envelope contracts
- `pagination`: Common pagination parameters, page models, and pagination helpers
- `logging`: Request ID tracking and structured logging helpers
- `contracts`: Shared schema contracts / interfaces
- `enums`: Common enums shared across domain boundaries

## Anti-Patterns (What Does NOT Belong Here)
- Domain-specific models (e.g. `User`, `Task`, `Project`)
- Workflow transition logic
- Business rule engines
- Direct database connection pools or migrations
