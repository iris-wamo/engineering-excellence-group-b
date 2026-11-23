# Demo 01 — WebSocket Authentication and Access

## Loom Video

- **Status**: 
- **Loom Link**: `[Add the recorded Loom URL here]`



## Protocol and evidence

See [websocket-security.md](../../../docs/session-06/websocket-security.md) for the token
exposure tradeoff, Origin policy, message contract, limits, authorization checks, close
codes, and deployment requirements.

Run the automated security and lifecycle evidence with:

```bash
uv run pytest tests/unit/websockets/test_task_activity.py -v
```

The test module covers Origin rejection, missing/invalid/expired credentials, inactive
users, workspace authorization, project nonmembership, authorization revalidation after
membership removal, invalid and oversized messages, heartbeat timeout, rate limiting,
registry cleanup, and gauge values.

Latest run: `14 passed` (100%); all `10/10` documented unauthorized cases were rejected.
The tests use mocked repositories and exercise the real ASGI endpoint without requiring
PostgreSQL or MongoDB.
