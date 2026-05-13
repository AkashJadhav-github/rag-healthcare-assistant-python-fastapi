"""
Load test: simulate 500 concurrent users hitting the /ask endpoint.
Run: python scripts/performance_test.py

Requires: pip install locust
Or run directly to simulate N concurrent asyncio tasks.
"""

import asyncio
import httpx
import time
import statistics
import os

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@healthcare.local")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@12345!")
CONCURRENT_USERS = int(os.getenv("CONCURRENT_USERS", "50"))
TOTAL_REQUESTS = int(os.getenv("TOTAL_REQUESTS", "200"))

SAMPLE_QUERIES = [
    "What are the first-line treatments for hypertension?",
    "What is the recommended HbA1c target for type 2 diabetes?",
    "What are common drug interactions with warfarin?",
    "Describe the diagnostic criteria for heart failure.",
    "What are the HIPAA privacy rule requirements?",
    "Explain the HL7 FHIR Patient resource structure.",
    "What is the treatment protocol for STEMI?",
    "What are the contraindications for metformin?",
    "Describe chronic kidney disease staging.",
    "What are the signs of sepsis according to Sepsis-3 criteria?",
]


async def single_request(client: httpx.AsyncClient, token: str, query: str) -> dict:
    start = time.time()
    try:
        r = await client.post(
            "/knowledge/ask",
            json={"query": query},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        latency = (time.time() - start) * 1000
        return {
            "success": r.status_code == 200,
            "latency_ms": latency,
            "status": r.status_code,
        }
    except Exception as e:
        return {
            "success": False,
            "latency_ms": (time.time() - start) * 1000,
            "error": str(e),
        }


async def main():
    print(
        f"Performance test: {TOTAL_REQUESTS} requests, {CONCURRENT_USERS} concurrent users"
    )
    print(f"Target: {API_BASE}")

    async with httpx.AsyncClient(base_url=API_BASE, timeout=30) as client:
        r = await client.post(
            "/auth/login", data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        print(f"Authenticated as {ADMIN_EMAIL}\n")

        queries = [
            SAMPLE_QUERIES[i % len(SAMPLE_QUERIES)] for i in range(TOTAL_REQUESTS)
        ]
        semaphore = asyncio.Semaphore(CONCURRENT_USERS)

        async def bounded_request(query):
            async with semaphore:
                return await single_request(client, token, query)

        start_time = time.time()
        results = await asyncio.gather(*[bounded_request(q) for q in queries])
        total_time = time.time() - start_time

    successful = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    latencies = [r["latency_ms"] for r in successful]

    print("=" * 60)
    print(f"Total requests   : {TOTAL_REQUESTS}")
    print(
        f"Successful       : {len(successful)} ({len(successful) / TOTAL_REQUESTS * 100:.1f}%)"
    )
    print(f"Failed           : {len(failed)}")
    print(f"Total time       : {total_time:.2f}s")
    print(f"Throughput       : {TOTAL_REQUESTS / total_time:.1f} req/s")

    if latencies:
        print("\nLatency (ms):")
        print(f"  min p50    : {statistics.median(latencies):.0f}")
        print(f"  p95        : {sorted(latencies)[int(len(latencies) * 0.95)]:.0f}")
        print(f"  p99        : {sorted(latencies)[int(len(latencies) * 0.99)]:.0f}")
        print(f"  max        : {max(latencies):.0f}")
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        print(f"\nSLA check (p95 < 2000ms): {'✓ PASS' if p95 < 2000 else '✗ FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
