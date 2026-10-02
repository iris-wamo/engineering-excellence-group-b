# Raw Import Normalization

## Overview
Design and implementation notes for ingesting raw task payloads (e.g. from MongoDB or external sources) and processing them into normalized PostgreSQL records.

## Goals & Pipeline
1. **Raw Storage**: Ingest unstructured/semi-structured raw payloads first with an import/trace ID.
2. **Validation & Transformation**: Validate payload format, sanitize fields, resolve foreign keys (users, projects).
3. **Normalized Persistence**: Insert/update normalized relational records in PostgreSQL.
4. **Status & Traceability**: Track processing status (`pending`, `completed`, `failed`), failure reasons, and link raw payloads to relational IDs.

## Data Boundary: Raw vs Relational
- **Raw Document (MongoDB / staging)**: Full original JSON payload, source metadata, ingestion timestamp, raw headers.
- **Relational Record (PostgreSQL)**: Normalized entities (`Task`, `User`, `Project`), typed columns, foreign keys, timestamps.
