# WebSocket Authentication and Access

## Endpoint and authentication

The task-activity endpoint is `ws(s)://<api-host>/api/v1/ws/task-activity`. A browser
connects with an optional `workspace_id` query parameter and sends its existing access
JWT in the first JSON message:

```json
{"type":"authenticate","token":"<access-token>"}
```

The server validates the JWT with the same decoder used by HTTP bearer authentication,
loads the active user, and resolves the workspace with the same rules as
`X-Workspace-ID`. The WebSocket's `workspace_id` query parameter is the browser-compatible
equivalent of that header; when omitted, the HTTP API's default-workspace behavior applies,
but the socket additionally requires actual membership in the resolved workspace.

The token is deliberately sent as the first WebSocket data frame rather than in the URL or
subprotocol. URLs commonly appear in access logs, browser history, and proxy telemetry;
subprotocols can be recorded in handshake metadata. A first frame avoids those routine
URL/handshake exposures, but it is still a bearer credential visible to the client,
application process, and any frame-inspecting proxy or diagnostic tool. The app does not
log authentication frames or their contents. Authentication must arrive within five
seconds. Missing, invalid, expired, inactive-user, or unauthorized-workspace credentials
are rejected with close code `4401` or `4403`.

The automated rejection cases are: missing, malformed, or cross-origin `Origin`; no token;
malformed/invalid JWT; expired JWT; inactive user; user outside the selected workspace;
invalid workspace selection; and a workspace member without a role in the subscribed
project. The tests assert the handshake denial, close code, or error frame for each case.

## Origin and transport requirements

Every connection must include an `Origin` matching the request's scheme and host. Missing
or different origins are rejected before the WebSocket upgrade; ASGI servers return an
HTTP `403` handshake denial, not a WebSocket close code. This is a same-origin policy;
cross-origin frontends need an explicit, reviewed allowlist rather than a permissive
reflection rule.

This application does not terminate TLS. A real deployment must expose only `wss://` to
clients, terminate TLS at a trusted ingress, restrict accepted hosts, and configure
forwarded scheme/host handling so Origin validation sees the external origin. Plain
`ws://` is suitable only for local development. WebSocket itself does not provide
authentication, authorization, encryption, or protection against cross-site WebSocket
hijacking; the application and deployment must supply those controls.

## Message contract and limits

After connection, the server sends `{"type":"ready","requires":"authenticate"}`. On
successful authentication it sends `{"type":"authenticated","workspace_id":...}`. A
client requests a project subscription with:

```json
{"type":"subscribe","project_id":123}
```

An accepted request is acknowledged with `{"type":"subscribed","project_id":123}`.
Clients must answer each server `heartbeat` frame with a `pong` containing the same nonce:

```json
{"type":"pong","nonce":"<server nonce>"}
```

The server sends a heartbeat every 20 seconds and closes stale connections with code
`1013` if the matching pong is not received within 10 seconds. Invalid, malformed, and
oversized messages return an error frame and do not by themselves disconnect the client:

```json
{"type":"error","code":"INVALID_MESSAGE","message":"Expected a valid JSON object."}
{"type":"error","code":"MESSAGE_TOO_LARGE","message":"Messages must not exceed 4096 bytes."}
```

The protocol caps a message at 4,096 bytes and accepts at most 30 client messages per
connection in any rolling 10-second window. Rate-limit violations return a `RATE_LIMITED`
error frame. Other error codes include `AUTHENTICATION_REQUIRED` and `PROJECT_FORBIDDEN`.
Close code `4400` indicates an invalid workspace selection; `4401` indicates authentication
failure; `4403` indicates a workspace or project access failure after upgrade.

## Authorization and lifecycle

The connection must belong to the resolved workspace. A project subscription is accepted
only when the project belongs to that workspace and the user still has a project role.
Workspace membership and project role/membership are checked again by
`connection_registry.authorize_event` immediately before an event sender may deliver each
event. A failed recheck closes the socket with code `4403`; periodic heartbeat checks also
remove revoked subscribers even when no events are flowing.

This change provides the authorization gate and connection lifecycle only. It does not
connect Redis or deliver task events; Redis fan-out and event delivery remain out of scope
for this issue. Open sockets are tracked in-process and reflected by the
`taskflow_websocket_connections` Prometheus gauge. A disconnect, auth rejection, stale
heartbeat, or revoked subscription removes that socket from the registry.

No token or message payload is logged by the WebSocket handler. Production deployments
must also disable or redact credential/frame logging in ingress, proxy, tracing, and
debugging systems. The Prometheus gauge is registered for the existing/future metrics
endpoint; this issue does not add a `/metrics` route.
