"""Unit tests for the load-test script's error rate."""

from scripts.load_test import Results


def test_server_errors_are_counted_once_in_the_error_rate() -> None:
    # 98 OK and 2 x 5xx responses: 2% errors, not 2 / 102
    results = Results(latencies=[0.01] * 100, server_errors=2)

    assert results.error_rate == 0.02


def test_requests_without_a_response_count_as_errors() -> None:
    # 99 responses (1 of them 5xx) and 1 request that got no response
    results = Results(latencies=[0.01] * 99, server_errors=1, failed=1)

    assert results.attempts == 100
    assert results.error_rate == 0.02


def test_client_errors_do_not_count_as_errors() -> None:
    results = Results(latencies=[0.01] * 10, client_errors=3)

    assert results.error_rate == 0.0


def test_no_attempts_has_no_error_rate() -> None:
    assert Results().error_rate == 0.0
