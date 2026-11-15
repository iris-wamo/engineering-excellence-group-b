"""Controlled load against one endpoint, checked against a p95 latency and error-rate target.

N clients each send requests back to back for a fixed time. Errors are 5xx responses and
requests that failed outright (timeouts, refused connections); 4xx are counted separately.
The same traffic shows up on the Grafana dashboard, so client-side and server-side numbers
can be compared. The targets are teaching targets (docs/session-06/slo-and-deliverables.md).

    uv run python -m scripts.load_test --clients 20 --duration 60
"""

import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class Results:
    latencies: list[float] = field(default_factory=list)
    errors: int = 0
    client_errors: int = 0


async def _client(client: httpx.AsyncClient, url: str, deadline: float, results: Results) -> None:
    while time.perf_counter() < deadline:
        started = time.perf_counter()
        try:
            response = await client.get(url)
        except httpx.HTTPError:
            results.errors += 1
            continue
        results.latencies.append(time.perf_counter() - started)
        if response.status_code >= 500:
            results.errors += 1
        elif response.status_code >= 400:
            results.client_errors += 1


async def run(url: str, clients: int, duration: float) -> Results:
    results = Results()
    deadline = time.perf_counter() + duration
    limits = httpx.Limits(max_connections=clients)
    async with httpx.AsyncClient(timeout=10.0, limits=limits) as client:
        await asyncio.gather(*(_client(client, url, deadline, results) for _ in range(clients)))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000/api/v1/projects")
    parser.add_argument("--clients", type=int, default=20)
    parser.add_argument("--duration", type=float, default=60.0, help="seconds")
    parser.add_argument("--p95-target-ms", type=float, default=200.0)
    parser.add_argument("--error-target", type=float, default=0.01, help="share, e.g. 0.01 = 1%%")
    args = parser.parse_args()

    print(f"GET {args.url} with {args.clients} clients for {args.duration:.0f}s ...")
    results = asyncio.run(run(args.url, args.clients, args.duration))

    requests = len(results.latencies)
    if requests < 2:
        print("Too few responses to compute percentiles; is the API running?")
        return 1
    cuts = statistics.quantiles(results.latencies, n=100)
    p50, p95, p99 = (cuts[49] * 1000, cuts[94] * 1000, cuts[98] * 1000)
    error_rate = results.errors / (requests + results.errors)

    print(f"requests: {requests}  ({requests / args.duration:.1f}/s)")
    print(f"latency ms: p50 {p50:.1f}  p95 {p95:.1f}  p99 {p99:.1f}")
    print(f"errors: {results.errors} ({error_rate:.2%})  4xx: {results.client_errors}")

    p95_ok = p95 <= args.p95_target_ms
    errors_ok = error_rate <= args.error_target
    print(f"target p95 <= {args.p95_target_ms:.0f} ms: {'met' if p95_ok else 'MISSED'}")
    print(f"target errors <= {args.error_target:.0%}: {'met' if errors_ok else 'MISSED'}")
    return 0 if p95_ok and errors_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
