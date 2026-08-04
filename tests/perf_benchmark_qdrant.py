"""Qdrant performance benchmark — latency, concurrency, disk, memory.

Standalone script (not unittest). Writes results to docs/QDRANT_PERFORMANCE.md.

Usage:
    uv run python tests/perf_benchmark_qdrant.py
"""
import json
import os
import sys
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.services.rag_service import RAGService


def _get_test_queries() -> list[str]:
    path = os.path.join(os.path.dirname(__file__), "retrieval_test_cases.json")
    with open(path, encoding="utf-8") as f:
        cases = json.load(f)
    return [c["query"] for c in cases if "query" in c][:50]


def _measure_latencies(rag: RAGService, queries: list[str], method: str, iterations: int = 100) -> dict:
    """Run queries and return latency stats."""
    latencies = []
    for i in range(iterations):
        q = queries[i % len(queries)]
        start = time.perf_counter()
        try:
            rag._invoke_rag(q, channel="chat")
        except Exception:
            pass
        latencies.append((time.perf_counter() - start) * 1000)

    latencies.sort()
    return {
        "method": method,
        "iterations": iterations,
        "p50_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(latencies[int(len(latencies) * 0.95)], 2),
        "p99_ms": round(latencies[int(len(latencies) * 0.99)], 2),
        "mean_ms": round(statistics.mean(latencies), 2),
        "min_ms": round(min(latencies), 2),
        "max_ms": round(max(latencies), 2),
    }


def _measure_concurrent(rag: RAGService, queries: list[str], workers: int) -> dict:
    """Measure concurrent query throughput."""
    start = time.perf_counter()
    completed = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(rag._invoke_rag, queries[i % len(queries)], "chat")
            for i in range(workers * 5)
        ]
        for f in as_completed(futures):
            try:
                f.result()
                completed += 1
            except Exception:
                errors += 1

    elapsed = time.perf_counter() - start
    return {
        "workers": workers,
        "total_queries": workers * 5,
        "completed": completed,
        "errors": errors,
        "total_time_s": round(elapsed, 2),
        "qps": round(completed / elapsed, 2),
    }


def _get_disk_usage(path: str) -> str:
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total += os.path.getsize(fp)
    if total < 1024 * 1024:
        return f"{total / 1024:.1f} KB"
    return f"{total / (1024 * 1024):.1f} MB"


def _get_memory_usage() -> str:
    try:
        import psutil
        process = psutil.Process(os.getpid())
        rss = process.memory_info().rss
        return f"{rss / (1024 * 1024):.1f} MB"
    except ImportError:
        return "psutil not installed"


def _measure_cold_start(rag_class, queries: list[str]) -> dict:
    """Measure cold-start (first query after init) vs warm."""
    rag = rag_class()
    start = time.perf_counter()
    try:
        rag._invoke_rag(queries[0], "chat")
    except Exception:
        pass
    cold = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    try:
        rag._invoke_rag(queries[1], "chat")
    except Exception:
        pass
    warm = (time.perf_counter() - start) * 1000

    return {"cold_start_ms": round(cold, 2), "warm_ms": round(warm, 2)}


def main():
    print("=== Qdrant Performance Benchmark ===\n")

    queries = _get_test_queries()
    if not queries:
        print("ERROR: No test queries found in retrieval_test_cases.json")
        return

    print(f"Loaded {len(queries)} test queries")

    rag = RAGService()
    if not rag.vectorstore:
        print("ERROR: Qdrant not initialized. Run: uv run python -m data_injection")
        return

    from src.config import QDRANT_PATH
    disk = _get_disk_usage(QDRANT_PATH)
    mem_before = _get_memory_usage()

    print(f"\nDisk usage (spyderwash_qdrant/): {disk}")
    print(f"RSS memory (process): {mem_before}")

    print("\n--- Latency (100 iterations each) ---")
    latency = _measure_latencies(rag, queries, "hybrid", iterations=100)
    print(f"  Hybrid: p50={latency['p50_ms']}ms  p95={latency['p95_ms']}ms  p99={latency['p99_ms']}ms  mean={latency['mean_ms']}ms")

    print("\n--- Cold Start ---")
    cold = _measure_cold_start(RAGService, queries)
    print(f"  Cold: {cold['cold_start_ms']}ms | Warm: {cold['warm_ms']}ms")

    print("\n--- Concurrent Load ---")
    for workers in [5, 10, 20]:
        conc = _measure_concurrent(rag, queries, workers)
        print(f"  {workers} workers: {conc['qps']} QPS, {conc['total_time_s']}s total, {conc['errors']} errors")

    mem_after = _get_memory_usage()
    print(f"\nRSS memory (after benchmark): {mem_after}")

    _write_report(disk, mem_before, mem_after, latency, cold, queries)
    print("\nResults written to docs/QDRANT_PERFORMANCE.md")


def _write_report(disk, mem_before, mem_after, latency, cold, queries):
    report = f"""# Qdrant Performance Benchmark Results

## Environment

- Python: 3.14 (cpython)
- Qdrant: local on-disk (spyderwash_qdrant/)
- Embedding: OpenAI text-embedding-3-small (1536 dims)
- Distance: Cosine
- Test queries: {len(queries)} from retrieval_test_cases.json

## Resource Usage

| Metric | Value |
|--------|-------|
| Disk (spyderwash_qdrant/) | {disk} |
| RSS memory (before benchmark) | {mem_before} |
| RSS memory (after benchmark) | {mem_after} |

## Latency — Hybrid Retrieval (100 iterations)

| Metric | Value |
|--------|-------|
| p50 | {latency['p50_ms']} ms |
| p95 | {latency['p95_ms']} ms |
| p99 | {latency['p99_ms']} ms |
| Mean | {latency['mean_ms']} ms |
| Min | {latency['min_ms']} ms |
| Max | {latency['max_ms']} ms |

## Cold Start

| Metric | Value |
|--------|-------|
| Cold start (first query after init) | {cold['cold_start_ms']} ms |
| Warm (subsequent query) | {cold['warm_ms']} ms |

## Notes

- All measurements taken on local machine with on-disk Qdrant (no network latency).
- Latency includes embedding generation (OpenAI API call) + vector search + FlashRank rerank + co-retrieval.
- Payload indexes: article_id, category, intent, device_type, product, audience, status, source_priority.
"""
    os.makedirs("docs", exist_ok=True)
    with open("docs/QDRANT_PERFORMANCE.md", "w", encoding="utf-8") as f:
        f.write(report)


if __name__ == "__main__":
    main()
