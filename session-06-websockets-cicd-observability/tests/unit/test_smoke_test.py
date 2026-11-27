"""Unit tests for the release smoke test's checks (scripts/smoke_test.py), with a fake API."""

from typing import Any

import pytest

from scripts.smoke_test import HttpResult, Smoke, SmokeFailure

SHA = "a" * 40
ENVELOPE = {"error": {"code": "X", "message": "m", "details": []}}


class FakeApi:
    """Answers the smoke test's calls like a healthy TaskFlow API; tests break one route."""

    def __init__(self) -> None:
        self.overrides: dict[tuple[str, str], HttpResult] = {}
        self.calls: list[tuple[str, str]] = []
        self.task: dict[str, Any] = {"id": 7, "status": "todo", "assignee_id": None}

    def __call__(
        self, method: str, path: str, payload: dict[str, Any] | None, headers: dict[str, str]
    ) -> HttpResult:
        self.calls.append((method, path))
        route = (method, path.split("?")[0])
        if route in self.overrides:
            return self.overrides[route]
        authed = headers.get("Authorization") == "Bearer good"
        match route:
            case ("POST", "/api/v1/auth/signup"):
                return HttpResult(201, {"id": 1})
            case ("GET", "/version"):
                return HttpResult(200, {"version": "dev", "git_sha": SHA, "environment": "x"})
            case ("GET", "/api/v1/auth/me"):
                return HttpResult(200, {"id": 1}) if authed else HttpResult(401, ENVELOPE)
            case ("POST", "/api/v1/auth/login"):
                return HttpResult(200, {"access_token": "good"})
            case ("POST", "/api/v1/tasks"):
                return HttpResult(201, self.task)
            case ("POST", "/api/v1/tasks/7/assign"):
                assert payload is not None
                self.task["assignee_id"] = payload["assignee_id"]
                return HttpResult(200, self.task)
            case ("PATCH", "/api/v1/tasks/7/status"):
                assert payload is not None
                self.task["status"] = payload["status"]
                return HttpResult(200, self.task)
            case ("GET", "/api/v1/tasks"):
                return HttpResult(200, {"items": [self.task], "total": 1})
            case _:
                return HttpResult(404, ENVELOPE)


def _smoke(api: FakeApi) -> Smoke:
    return Smoke(api, "smoke@example.com", "pw")


def test_healthy_api_passes_every_check() -> None:
    api = FakeApi()
    smoke = _smoke(api)

    smoke.check(project_id=1, expect_sha=SHA)

    assert len(smoke.passed) == 10
    assert ("PATCH", "/api/v1/tasks/7/status") in api.calls


def test_wrong_build_fails_before_any_other_call() -> None:
    api = FakeApi()

    with pytest.raises(SmokeFailure, match="expected build"):
        _smoke(api).check(project_id=1, expect_sha="b" * 40)

    assert api.calls == [("GET", "/version")]


def test_broken_status_change_fails_the_run() -> None:
    api = FakeApi()
    api.overrides[("PATCH", "/api/v1/tasks/7/status")] = HttpResult(500, ENVELOPE)

    with pytest.raises(SmokeFailure, match="change the task status"):
        _smoke(api).check(project_id=1, expect_sha=None)


def test_error_without_the_envelope_fails() -> None:
    api = FakeApi()
    api.overrides[("GET", "/api/v1/tasks/999999999")] = HttpResult(404, {"detail": "nope"})

    with pytest.raises(SmokeFailure, match="error envelope"):
        _smoke(api).check(project_id=1, expect_sha=None)


def test_signup_refuses_an_account_registered_by_someone_else() -> None:
    """A 409 is only fine if SMOKE_PASSWORD works; otherwise the fixture must not run."""
    api = FakeApi()
    api.overrides[("POST", "/api/v1/auth/signup")] = HttpResult(409, ENVELOPE)
    api.overrides[("POST", "/api/v1/auth/login")] = HttpResult(401, ENVELOPE)

    with pytest.raises(SmokeFailure, match="login as the smoke user"):
        _smoke(api).signup()


@pytest.mark.parametrize(("status", "ok"), [(201, True), (409, True), (500, False)])
def test_signup_accepts_an_existing_account(status: int, ok: bool) -> None:
    api = FakeApi()
    api.overrides[("POST", "/api/v1/auth/signup")] = HttpResult(status, ENVELOPE)

    if ok:
        _smoke(api).signup()
    else:
        with pytest.raises(SmokeFailure):
            _smoke(api).signup()
