"""
Retrieval Benchmark — runs test cases through all 3 pipelines and compares results.

Usage:
    uv run python -m tests.benchmark_retrieval

Compares:
    1. Traditional Vector DB (Qdrant + FlashRank)
    2. Vectorless RAG (SQLite structured lookup)
    3. Hybrid RAG (Vector + metadata filtering + co-retrieval rules)

Metrics:
    - Accuracy: correct primary article in results
    - Recall: all expected companions found
    - Latency: time per query (ms)
    - Wrong-device rate: articles from wrong device in results
    - Co-retrieval success: companions fetched when expected
"""
import json
import os
import sys
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.services.kb_database import initialize_database
from src.services.vectorless_rag import vectorless_retrieve

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def load_test_cases() -> list[dict]:
    test_file = os.path.join(os.path.dirname(__file__), "retrieval_test_cases.json")
    with open(test_file, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_vectorless(test_cases: list[dict]) -> dict:
    """Run all test cases through the Vectorless RAG pipeline."""
    results = {
        "method": "vectorless",
        "total": len(test_cases),
        "primary_hits": 0,
        "companion_hits": 0,
        "companion_total_expected": 0,
        "wrong_device": 0,
        "total_latency_ms": 0,
        "details": [],
    }

    for tc in test_cases:
        start = time.time()
        docs, _co_meta = vectorless_retrieve(
            query=tc["query"],
            intent=tc["intent"],
            device_type=tc.get("device", ""),
            top_k=6,
        )
        latency = (time.time() - start) * 1000

        retrieved_ids = [d.metadata.get("article_id", "") for d in docs]
        primary_hit = tc["expected_primary"] in retrieved_ids

        companions_expected = tc.get("expected_companions", [])
        companions_found = [c for c in companions_expected if c in retrieved_ids]

        # Wrong device check
        wrong_device_count = 0
        expected_device = tc.get("device", "")
        if expected_device and expected_device != "General":
            for doc in docs:
                doc_device = doc.metadata.get("device_type", "General")
                if doc_device != "General" and doc_device != expected_device:
                    wrong_device_count += 1

        results["primary_hits"] += 1 if primary_hit else 0
        results["companion_hits"] += len(companions_found)
        results["companion_total_expected"] += len(companions_expected)
        results["wrong_device"] += wrong_device_count
        results["total_latency_ms"] += latency

        results["details"].append({
            "id": tc["id"],
            "primary_hit": primary_hit,
            "companions_found": companions_found,
            "companions_expected": companions_expected,
            "retrieved": retrieved_ids[:5],
            "wrong_device": wrong_device_count,
            "latency_ms": round(latency, 1),
        })

    return results


def evaluate_vector(test_cases: list[dict]) -> dict:
    """Run all test cases through the Traditional Vector DB pipeline."""
    try:
        from src.services.rag_service import RAGService
        rag = RAGService()
        if not rag.vectorstore:
            return {"method": "vector", "error": "Qdrant not initialized"}
    except Exception as e:
        return {"method": "vector", "error": str(e)}

    results = {
        "method": "vector",
        "total": len(test_cases),
        "primary_hits": 0,
        "companion_hits": 0,
        "companion_total_expected": 0,
        "wrong_device": 0,
        "total_latency_ms": 0,
        "details": [],
    }

    for tc in test_cases:
        start = time.time()
        all_docs = rag._vector_retrieve_context(tc["query"], metadata_filter=None)
        latency = (time.time() - start) * 1000

        retrieved_ids = [d.metadata.get("article_id", "") for d in all_docs]
        primary_hit = tc["expected_primary"] in retrieved_ids

        companions_expected = tc.get("expected_companions", [])
        companions_found = [c for c in companions_expected if c in retrieved_ids]

        wrong_device_count = 0
        expected_device = tc.get("device", "")
        if expected_device and expected_device != "General":
            for doc in all_docs:
                doc_product = doc.metadata.get("product", "")
                if doc_product and expected_device.lower() not in doc_product.lower() and "general" not in doc_product.lower():
                    wrong_device_count += 1

        results["primary_hits"] += 1 if primary_hit else 0
        results["companion_hits"] += len(companions_found)
        results["companion_total_expected"] += len(companions_expected)
        results["wrong_device"] += wrong_device_count
        results["total_latency_ms"] += latency

        results["details"].append({
            "id": tc["id"],
            "primary_hit": primary_hit,
            "companions_found": companions_found,
            "companions_expected": companions_expected,
            "retrieved": retrieved_ids[:5],
            "wrong_device": wrong_device_count,
            "latency_ms": round(latency, 1),
        })

    return results


def evaluate_hybrid(test_cases: list[dict]) -> dict:
    """Run all test cases through the Hybrid RAG pipeline."""
    try:
        from src.services.rag_service import RAGService, _rerank_documents
        rag = RAGService()
        if not rag.vectorstore:
            return {"method": "hybrid", "error": "Qdrant not initialized"}
    except Exception as e:
        return {"method": "hybrid", "error": str(e)}

    from src.services.hybrid_rag import hybrid_retrieve

    results = {
        "method": "hybrid",
        "total": len(test_cases),
        "primary_hits": 0,
        "companion_hits": 0,
        "companion_total_expected": 0,
        "wrong_device": 0,
        "total_latency_ms": 0,
        "details": [],
    }

    for tc in test_cases:
        start = time.time()
        docs, _co_meta = hybrid_retrieve(
            query=tc["query"],
            vectorstore=rag.vectorstore,
            intent=tc["intent"],
            device_type=tc.get("device", ""),
            top_k=6,
            rerank_fn=_rerank_documents,
        )
        latency = (time.time() - start) * 1000

        retrieved_ids = [d.metadata.get("article_id", "") for d in docs]
        primary_hit = tc["expected_primary"] in retrieved_ids

        companions_expected = tc.get("expected_companions", [])
        companions_found = [c for c in companions_expected if c in retrieved_ids]

        wrong_device_count = 0
        expected_device = tc.get("device", "")
        if expected_device and expected_device != "General":
            for doc in docs:
                doc_device = doc.metadata.get("device_type", "") or doc.metadata.get("product", "")
                if doc_device and expected_device.lower() not in doc_device.lower() and "general" not in doc_device.lower():
                    wrong_device_count += 1

        results["primary_hits"] += 1 if primary_hit else 0
        results["companion_hits"] += len(companions_found)
        results["companion_total_expected"] += len(companions_expected)
        results["wrong_device"] += wrong_device_count
        results["total_latency_ms"] += latency

        results["details"].append({
            "id": tc["id"],
            "primary_hit": primary_hit,
            "companions_found": companions_found,
            "companions_expected": companions_expected,
            "retrieved": retrieved_ids[:5],
            "wrong_device": wrong_device_count,
            "latency_ms": round(latency, 1),
        })

    return results


def print_summary(results: dict):
    """Print formatted summary for one pipeline."""
    if "error" in results:
        print(f"  {results['method'].upper():12} | ERROR: {results['error']}")
        return

    total = results["total"]
    accuracy = results["primary_hits"] / total * 100 if total else 0
    companion_expected = results["companion_total_expected"]
    co_ret_rate = results["companion_hits"] / companion_expected * 100 if companion_expected else 100
    avg_latency = results["total_latency_ms"] / total if total else 0
    wrong_device_rate = results["wrong_device"] / (total * 6) * 100

    print(f"  {results['method'].upper():12} | "
          f"Accuracy: {accuracy:5.1f}% | "
          f"Co-retrieval: {co_ret_rate:5.1f}% | "
          f"Wrong-device: {wrong_device_rate:4.1f}% | "
          f"Avg latency: {avg_latency:7.1f}ms")


def main():
    print("=" * 80)
    print("  RETRIEVAL BENCHMARK — 3 Pipelines Comparison")
    print("=" * 80)
    print()

    initialize_database()
    test_cases = load_test_cases()
    print(f"  Test cases loaded: {len(test_cases)}")
    print()

    # Vectorless RAG (always available — SQLite only)
    print("  Running Vectorless RAG...")
    vectorless_results = evaluate_vectorless(test_cases)

    # Vector DB (requires ChromaDB)
    print("  Running Vector DB RAG...")
    vector_results = evaluate_vector(test_cases)

    # Hybrid (requires ChromaDB)
    print("  Running Hybrid RAG...")
    hybrid_results = evaluate_hybrid(test_cases)

    print()
    print("-" * 80)
    print("  RESULTS SUMMARY")
    print("-" * 80)
    print()
    print_summary(vectorless_results)
    print_summary(vector_results)
    print_summary(hybrid_results)
    print()

    # Save detailed results
    output_path = os.path.join(os.path.dirname(__file__), "benchmark_results.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "vectorless": vectorless_results,
            "vector": vector_results,
            "hybrid": hybrid_results,
        }, f, indent=2)
    print(f"  Detailed results saved to: {output_path}")
    print()

    # Show missed cases for vectorless
    print("-" * 80)
    print("  VECTORLESS MISSES (primary article not found):")
    print("-" * 80)
    for detail in vectorless_results.get("details", []):
        if not detail["primary_hit"]:
            print(f"    {detail['id']}: retrieved {detail['retrieved']}")


if __name__ == "__main__":
    main()
