"""Release smoke test: a few real API calls against a deployed stack.

Run by scripts/release.sh after every deploy, promote and rollback (and by the release
workflow). Standard library only, so it runs on any host with Python 3.12, with or without
the project's virtualenv. See docs/session-06/ci-cd.md (Release).

Two phases, because the smoke user needs a project it owns and a fresh database has no admin
who could create one over the API (release.sh runs docker/release/smoke-fixture.sql between
them):

    python3 scripts/smoke_test.py signup --url http://127.0.0.1:8001
    python3 scripts/smoke_test.py check --url http://127.0.0.1:8001 --project-id 1 \\
        --expect-sha <git sha>

Credentials come from SMOKE_EMAIL / SMOKE_PASSWORD. Exit code 0 means every check passed.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

TIMEOUT_SECONDS = 10.0


@dataclass
class HttpResult:
    status: int
    body: Any


# (method, path, json body or None, headers) -> result. Swapped for a fake in the unit tests.
Transport = Callable[[str, str, dict[str, Any] | None, dict[str, str]], HttpResult]


def urllib_transport(base_url: str) -> Transport:
    def send(
        method: str, path: str, payload: dict[str, Any] | None, headers: dict[str, str]
    ) -> HttpResult:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            base_url.rstrip("/") + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", **headers},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw.decode(errors="replace")
        return HttpResult(status, body)

    return send


class SmokeFailure(Exception):
    """A check failed; later checks depend on it, so the run stops."""


@dataclass
class Smoke:
    send: Transport
    email: str
    password: str
    passed: list[str] = field(default_factory=list)

    def expect(self, condition: bool, message: str, result: HttpResult | None = None) -> None:
        if not condition:
            detail = f" (HTTP {result.status}: {result.body!r})" if result is not None else ""
            raise SmokeFailure(message + detail)
        self.passed.append(message)
        print(f"  [PASS] {message}")

    def signup(self) -> None:
        result = self.send(
            "POST",
            "/api/v1/auth/signup",
            {"name": "Release Smoke", "email": self.email, "password": self.password},
            {},
        )
        # 409: an earlier deploy already created the account
        self.expect(result.status in (201, 409), "smoke user exists (signup)", result)

    def check(self, project_id: int, expect_sha: str | None) -> None:
        version = self.send("GET", "/version", None, {})
        self.expect(version.status == 200, "GET /version answers", version)
        print(f"         serving {version.body}")
        if expect_sha:
            self.expect(
                version.body.get("git_sha") == expect_sha,
                f"serving the expected build ({expect_sha[:12]})",
                version,
            )

        bad = self.send("GET", "/api/v1/auth/me", None, {"Authorization": "Bearer not-a-token"})
        self.expect(
            bad.status == 401 and _error_code(bad) is not None,
            "a bad token is rejected with 401 and the error envelope",
            bad,
        )

        login = self.send(
            "POST", "/api/v1/auth/login", {"email": self.email, "password": self.password}, {}
        )
        token = login.body.get("access_token") if isinstance(login.body, dict) else None
        self.expect(login.status == 200 and bool(token), "login returns an access token", login)
        auth = {"Authorization": f"Bearer {token}"}

        me = self.send("GET", "/api/v1/auth/me", None, auth)
        self.expect(me.status == 200, "GET /auth/me with the token", me)
        user_id = me.body["id"]

        created = self.send(
            "POST",
            "/api/v1/tasks",
            {"title": f"Release smoke {int(time.time())}", "project_id": project_id},
            auth,
        )
        self.expect(created.status == 201, "create a task", created)
        task_id = created.body["id"]

        assigned = self.send(
            "POST", f"/api/v1/tasks/{task_id}/assign", {"assignee_id": user_id}, auth
        )
        self.expect(
            assigned.status == 200 and assigned.body.get("assignee_id") == user_id,
            "assign the task to the smoke user",
            assigned,
        )

        moved = self.send(
            "PATCH", f"/api/v1/tasks/{task_id}/status", {"status": "in_progress"}, auth
        )
        self.expect(
            moved.status == 200 and moved.body.get("status") == "in_progress",
            "change the task status todo -> in_progress",
            moved,
        )

        listed = self.send(
            "GET", f"/api/v1/tasks?project_id={project_id}&page_size=100", None, auth
        )
        items = listed.body.get("items", []) if isinstance(listed.body, dict) else []
        self.expect(
            listed.status == 200
            and any(t["id"] == task_id and t["status"] == "in_progress" for t in items),
            "list tasks shows the task with its new status",
            listed,
        )

        missing = self.send("GET", "/api/v1/tasks/999999999", None, auth)
        self.expect(
            missing.status == 404 and _error_code(missing) is not None,
            "a missing task answers 404 with the error envelope",
            missing,
        )


def _error_code(result: HttpResult) -> str | None:
    if isinstance(result.body, dict) and isinstance(result.body.get("error"), dict):
        code = result.body["error"].get("code")
        return code if isinstance(code, str) else None
    return None


def wait_until_up(send: Transport, timeout: float) -> bool:
    """Poll /version until the API answers, for up to timeout seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if send("GET", "/version", None, {}).status == 200:
                return True
        except OSError:
            pass
        time.sleep(1)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("phase", choices=["signup", "check"])
    parser.add_argument("--url", default=os.environ.get("API_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--expect-sha", default=None, help="fail unless /version reports it")
    parser.add_argument("--wait", type=float, default=60.0, help="seconds to wait for the API")
    args = parser.parse_args(argv)

    email = os.environ.get("SMOKE_EMAIL", "release-smoke@example.com")
    password = os.environ.get("SMOKE_PASSWORD")
    if not password:
        print("SMOKE_PASSWORD is not set", file=sys.stderr)
        return 2
    if args.phase == "check" and args.project_id is None:
        parser.error("check needs --project-id")

    send = urllib_transport(args.url)
    print(f"Smoke test ({args.phase}) against {args.url}")
    if not wait_until_up(send, args.wait):
        print(f"  [FAIL] API did not answer within {args.wait:.0f}s")
        return 1

    smoke = Smoke(send, email, password)
    try:
        if args.phase == "signup":
            smoke.signup()
        else:
            smoke.check(args.project_id, args.expect_sha)
    except (SmokeFailure, KeyError, TypeError, AttributeError, OSError) as exc:
        print(f"  [FAIL] {exc}")
        print(f"Smoke test FAILED after {len(smoke.passed)} passing check(s)")
        return 1
    print(f"Smoke test passed ({len(smoke.passed)} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
