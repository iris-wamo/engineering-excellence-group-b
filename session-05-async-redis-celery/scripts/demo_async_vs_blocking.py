"""Demonstration and benchmark: Async non-blocking vs Blocking task summary endpoint.

Compares how FastAPI handles concurrent I/O-bound requests:
1. Non-blocking async version (/api/v1/tasks/summary)
2. Blocking synchronous simulation (/api/v1/tasks/summary/blocking)
3. Timeout handling demonstration (HTTP 504 Gateway Timeout)

Requires a seeded dev DB with at least workspace 1 and user 1,
because AUTH_HEADERS mints a token for user 1.
"""

import argparse
import asyncio
import json
import time
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.auth.security import create_access_token
from app.main import app

AUTH_HEADERS = {
    "Authorization": f"Bearer {create_access_token(1)}",
    "X-Workspace-ID": "1",
}


async def run_concurrent_requests(
    client: AsyncClient,
    path: str,
    concurrency: int,
    delay: float,
    timeout: float,
) -> tuple[float, list[float], list[int], Any]:
    """Execute concurrent GET requests to the specified endpoint path."""
    latencies: list[float] = []
    status_codes: list[int] = []
    sample_response: Any = None

    async def single_request() -> None:
        nonlocal sample_response
        req_start = time.perf_counter()
        resp = await client.get(
            f"{path}?external_delay={delay}&external_timeout={timeout}",
            headers=AUTH_HEADERS,
        )
        req_elapsed = time.perf_counter() - req_start
        latencies.append(req_elapsed)
        status_codes.append(resp.status_code)
        if sample_response is None and resp.status_code == 200:
            sample_response = resp.json()

    start_total = time.perf_counter()
    tasks = [asyncio.create_task(single_request()) for _ in range(concurrency)]
    await asyncio.gather(*tasks)
    total_time = time.perf_counter() - start_total

    return total_time, latencies, status_codes, sample_response


async def run_timeout_demo(
    client: AsyncClient,
    delay: float = 1.2,
    timeout: float = 0.5,
) -> None:
    """Demonstrate timeout behavior when an external service is slow."""
    print(f"\n{'=' * 75}")
    print(" DEMO 3: EXTERNAL SERVICE TIMEOUT ENFORCEMENT")
    print(f"{'=' * 75}")

    print(f"Configured delay: {delay}s | Timeout threshold: {timeout}s")
    print("Calling: GET /api/v1/tasks/summary with external_delay > external_timeout...")

    start = time.perf_counter()
    response = await client.get(
        f"/api/v1/tasks/summary?external_delay={delay}&external_timeout={timeout}",
        headers=AUTH_HEADERS,
    )

    elapsed = time.perf_counter() - start

    print(f"Status Code: {response.status_code}")
    print(f"Elapsed Time: {elapsed:.3f}s")
    print("Response Headers:")
    if "x-request-id" in response.headers:
        print(f"  X-Request-ID: {response.headers['x-request-id']}")
    print(f"  Content-Type: {response.headers.get('content-type')}")
    print("\nResponse Body:")
    print(json.dumps(response.json(), indent=2))


async def main() -> None:
    parser = argparse.ArgumentParser(description="Async vs Blocking Task Summary Benchmark")
    parser.add_argument(
        "--concurrency", type=int, default=10, help="Number of concurrent requests (default: 10)"
    )
    parser.add_argument(
        "--delay", type=float, default=0.2, help="Simulated external delay (default: 0.2s)"
    )
    parser.add_argument(
        "--timeout", type=float, default=1.0, help="External call timeout threshold (default: 1.0s)"
    )
    parser.add_argument(
        "--base-url", type=str, default="", help="Optional base URL for running server"
    )
    args = parser.parse_args()

    print(f"\n{'#' * 75}")
    print(" TASKFLOW SESSION 05: ASYNC VS BLOCKING TASK SUMMARY BENCHMARK")
    print(f"{'#' * 75}")
    print(f"Concurrency: {args.concurrency} concurrent requests")
    print(f"External simulated delay per request: {args.delay}s")
    print(f"External call timeout: {args.timeout}s")
    print(f"Expected sequential time (10 * {args.delay}s): ~{args.concurrency * args.delay:.2f}s")

    client_kwargs: dict[str, Any] = {}
    if args.base_url:
        print(f"Target: Live HTTP server at {args.base_url}")
        client_kwargs["base_url"] = args.base_url
    else:
        print("Target: In-process ASGI FastAPI app via ASGITransport")
        client_kwargs["transport"] = ASGITransport(app=app)
        client_kwargs["base_url"] = "http://test"

    async with AsyncClient(**client_kwargs) as client:
        # Warmup
        try:
            await client.get(
                "/api/v1/tasks/summary?external_delay=0.0&external_timeout=1.0",
                headers=AUTH_HEADERS,
            )
        except Exception:
            pass

        # 1. Benchmark Async Endpoint
        print(f"\n{'-' * 75}")
        print(" [1/3] Benchmarking NON-BLOCKING Async Endpoint: GET /api/v1/tasks/summary")
        print(f"{'-' * 75}")
        async_total, async_latencies, async_codes, async_sample = await run_concurrent_requests(
            client=client,
            path="/api/v1/tasks/summary",
            concurrency=args.concurrency,
            delay=args.delay,
            timeout=args.timeout,
        )
        async_avg = sum(async_latencies) / len(async_latencies) if async_latencies else 0.0
        success_async = async_codes.count(200)
        print(f"  -> Total Elapsed Time: {async_total:.3f}s")
        print(f"  -> Average Request Latency: {async_avg:.3f}s")
        print(f"  -> Successful Responses (HTTP 200): {success_async} / {len(async_codes)}")

        # 2. Benchmark Blocking Endpoint
        print(f"\n{'-' * 75}")
        print(" [2/3] Benchmarking BLOCKING Endpoint: GET /api/v1/tasks/summary/blocking")
        print(f"{'-' * 75}")
        block_total, block_latencies, block_codes, block_sample = await run_concurrent_requests(
            client=client,
            path="/api/v1/tasks/summary/blocking",
            concurrency=args.concurrency,
            delay=args.delay,
            timeout=args.timeout,
        )
        block_avg = sum(block_latencies) / len(block_latencies) if block_latencies else 0.0
        success_block = block_codes.count(200)
        print(f"  -> Total Elapsed Time: {block_total:.3f}s")
        print(f"  -> Average Request Latency: {block_avg:.3f}s")
        print(f"  -> Successful Responses (HTTP 200): {success_block} / {len(block_codes)}")

        # Comparison Table
        speedup = block_total / async_total if async_total > 0 else 0.0
        print(f"\n{'=' * 75}")
        print(" SIDE-BY-SIDE PERFORMANCE COMPARISON SUMMARY")
        print(f"{'=' * 75}")
        print(f"{'Endpoint':<34} | {'Requests':<8} | {'Total Time':<12} | {'Avg Latency':<12}")
        print(f"{'-' * 34}-+-{'-' * 8}-+-{'-' * 12}-+-{'-' * 12}")
        print(
            f"{'GET /api/v1/tasks/summary (Async)':<34} | "
            f"{args.concurrency:<8} | {async_total:>9.3f}s  | {async_avg:>9.3f}s"
        )
        print(
            f"{'GET /tasks/summary/blocking (Sync)':<34} | "
            f"{args.concurrency:<8} | {block_total:>9.3f}s  | {block_avg:>9.3f}s"
        )
        print(f"{'-' * 75}")
        print(f"Concurreny Speedup: {speedup:.2f}x faster with non-blocking async!")

        if async_sample:
            print("\nSample Successful Response Body (all 4 required pieces of data):")
            print(json.dumps(async_sample, indent=2))

        # 3. Timeout Demo
        await run_timeout_demo(client=client, delay=1.2, timeout=0.5)

    print(f"\n{'#' * 75}")
    print(" KEY ENGINEERING TAKEAWAYS")
    print(f"{'#' * 75}")
    print("""
1. Cooperative Concurrency for I/O:
   - Async endpoints yield execution to the event loop on I/O wait (`await asyncio.sleep()`).
   - All 10 concurrent requests sleep simultaneously, completing in ~delay seconds total.

2. Event Loop Starvation:
   - Synchronous blocking calls (`time.sleep()`) block the thread running the asyncio event
   - Note: while `time.sleep()` releases the GIL for other OS threads, it completely
     blocks the single thread executing this event loop. In single-threaded asyncio, all
     other coroutines freeze.
   - 10 concurrent requests take ~10 * delay seconds because they are forced to run sequentially.


3. Timeouts Prevent Cascading Failures:
   - An external call wrapped with `asyncio.wait_for(..., timeout=timeout)` terminates
     hung requests and returns HTTP 504 Gateway Timeout within the deadline.
   - Synchronous blocking code cannot be interrupted by `asyncio.wait_for`.

4. Where Async is NOT Enough:
   - CPU-bound work (image processing, encryption, large data parsing) blocks the loop.
   - Long-running jobs (> 2-3s) should NOT be kept open in HTTP request-response cycles.
   - Asynchronous workers (Celery + Redis) are the proper solution for heavy or decoupled jobs.
""")


if __name__ == "__main__":
    asyncio.run(main())
