import os
import re
import sys
import json
import time
import asyncio
import argparse
import httpx
from groq import AsyncGroq, RateLimitError
from dotenv import load_dotenv

load_dotenv()

TEST_SET_PATH = "evals/test_set.json"
REPORT_PATH = "evals/eval_report.json"
SPOT_CHECK_PATH = "evals/spot_check.json"

GATEWAY_BASE_URL = os.getenv("GATEWAY_BASE_URL", "http://127.0.0.1:8000")
GATEWAY_URL = f"{GATEWAY_BASE_URL}/chat/stream"
METRICS_URL = f"{GATEWAY_BASE_URL}/metrics"

JUDGE_MODEL = "qwen/qwen3.8-27b"
PASS_THRESHOLD = 0.75
REQUEST_DELAY_SEC = float(os.getenv("EVAL_DELAY_SEC", "0.25"))

# Groq openai/gpt-oss-20b list pricing (USD per 1M tokens)
INPUT_PRICE_PER_1M = 0.075
OUTPUT_PRICE_PER_1M = 0.30
SYSTEM_PROMPT_OVERHEAD_TOKENS = 60

judge_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))


def reconstruct_sse(raw_content: str) -> str:
    """Reassemble fragmented Server-Sent Events (SSE) chunks into plain text."""
    return "".join(
        line[6:]
        for line in raw_content.split("\n")
        if line.startswith("data: ") and "[DONE]" not in line
    ).strip()


def percentile(values: list[float], p: float) -> float:
    """Compute linear-interpolated percentile (e.g., p=50 or p=95)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


async def fetch_cache_counters(client: httpx.AsyncClient) -> tuple[float, float] | None:
    """Read Prometheus cache_hits_total and cache_misses_total counters from /metrics."""
    try:
        resp = await client.get(METRICS_URL, timeout=5.0)
        if resp.status_code != 200:
            return None
        text = resp.text
        hits = sum(
            float(m)
            for m in re.findall(
                r'^cache_hits_total(?:\{[^}]*\})?\s+([0-9.eE+-]+)', text, re.MULTILINE
            )
        )
        misses = sum(
            float(m)
            for m in re.findall(
                r'^cache_misses_total(?:\{[^}]*\})?\s+([0-9.eE+-]+)', text, re.MULTILINE
            )
        )
        return hits, misses
    except Exception:
        return None


async def grade_response(
    user_payload: dict, expected_facts: list, actual_response: str
) -> dict:
    """Ask a secondary LLM to score semantic faithfulness with retry on 429s."""
    system_prompt = (
        "You are a strict QA evaluator for an AI Gateway. "
        "Grade the ACTUAL RESPONSE against the EXPECTED FACTS based on semantic accuracy. "
        "Ignore minor formatting, markdown, or punctuation differences (such as Unicode hyphens). "
        "You MUST respond with a valid JSON object matching this exact schema:\n"
        '{"score": <float between 0.0 and 1.0>, "verdict": "<PASS or FAIL>", "reason": "<one concise sentence>"}'
    )

    user_prompt = (
        f"REQUEST PAYLOAD: {json.dumps(user_payload)}\n"
        f"EXPECTED FACTS / CONCEPTS: {json.dumps(expected_facts)}\n"
        f"ACTUAL RESPONSE: {actual_response}"
    )

    for attempt in range(4):
        try:
            completion = await judge_client.chat.completions.create(
                model=JUDGE_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                reasoning_effort="none",
                temperature=0.0,
                max_completion_tokens=512,
            )
            result = json.loads(completion.choices[0].message.content)
            score = max(0.0, min(1.0, float(result.get("score", 0.0))))
            verdict = "PASS" if score >= PASS_THRESHOLD else "FAIL"
            reason = result.get("reason", "No explanation provided.")
            return {"score": score, "verdict": verdict, "reason": reason}
        except RateLimitError:
            wait = 2 ** (attempt + 1)
            print(f"   ⏳ Judge rate-limited (429), retrying in {wait}s...")
            await asyncio.sleep(wait)

    return {"score": 0.0, "verdict": "FAIL", "reason": "Judge exceeded retry limit."}


def build_spot_check_sample(results: list[dict], target_size: int = 10) -> list[dict]:
    """Select up to 10 stratified cases (all failures + spread across categories) for human review."""
    selected = []
    seen_ids = set()

    # Always include failed cases first
    for r in results:
        if r["verdict"] != "PASS" and len(selected) < target_size:
            selected.append(r)
            seen_ids.add(r["id"])

    # Fill remaining slots evenly across categories
    by_category: dict[str, list[dict]] = {}
    for r in results:
        if r["id"] not in seen_ids:
            by_category.setdefault(r["category"], []).append(r)

    while len(selected) < target_size and any(by_category.values()):
        for cat in list(by_category.keys()):
            if by_category[cat] and len(selected) < target_size:
                item = by_category[cat].pop(0)
                selected.append(item)
                seen_ids.add(item["id"])

    return [
        {
            "id": r["id"],
            "category": r["category"],
            "prompt": r["prompt"],
            "expected_keywords": r["expected_keywords"],
            "actual_response": r["actual_response"],
            "judge_score": r["score"],
            "judge_verdict": r["verdict"],
            "judge_reason": r["reason"],
            "human_verdict": "",
            "human_notes": "",
        }
        for r in selected
    ]


async def run_judge(limit: int | None = None):
    with open(TEST_SET_PATH, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    if limit:
        test_cases = test_cases[:limit]

    total_cases = len(test_cases)
    passed_cases = 0
    scores: list[float] = []
    latencies: list[float] = []
    retrieval_total = 0
    retrieval_hits = 0
    fast_cache_hits = 0
    uncached_costs: list[float] = []
    detailed_results: list[dict] = []

    print(f"⚖️  Starting LLM-as-a-Judge Evaluation ({JUDGE_MODEL}) on {total_cases} cases...")

    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = {
            "Authorization": "Bearer YOUR_TEST_TOKEN",
            "Content-Type": "application/json",
        }

        counters_before = await fetch_cache_counters(client)

        for idx, case in enumerate(test_cases, start=1):
            print(f"\n[{idx}/{total_cases}] Running {case['id']} ({case['category']})...")
            start_time = time.time()

            try:
                response = await client.post(
                    GATEWAY_URL,
                    json=case["payload"],
                    headers=headers,
                )
                duration = time.time() - start_time

                # Handle gateway rate limit transparently if triggered during burst
                if response.status_code == 429:
                    print("   ⏳ Gateway rate-limited (429), backing off 5s and retrying once...")
                    await asyncio.sleep(5.0)
                    start_time = time.time()
                    response = await client.post(
                        GATEWAY_URL,
                        json=case["payload"],
                        headers=headers,
                    )
                    duration = time.time() - start_time

                

                if response.status_code != 200:
                    print(f"❌ GATEWAY ERROR | Status: {response.status_code} | Latency: {duration:.2f}s")
                    scores.append(0.0)
                    detailed_results.append({
                        "id": case["id"],
                        "category": case["category"],
                        "prompt": case["payload"]["message"],
                        "expected_keywords": case["expected_keywords"],
                        "actual_response": f"HTTP {response.status_code}",
                        "score": 0.0,
                        "verdict": "FAIL",
                        "reason": f"Gateway returned HTTP {response.status_code}",
                        "latency_sec": round(duration, 3),
                    })
                    continue

                reconstructed_text = reconstruct_sse(response.text)
                if not reconstructed_text:
                    print(f"❌ EMPTY RESPONSE | Latency: {duration:.2f}s")
                    scores.append(0.0)
                    continue

                latencies.append(duration)

                # Estimate token cost (as if uncached)
                in_tokens = estimate_tokens(case["payload"]["message"]) + SYSTEM_PROMPT_OVERHEAD_TOKENS
                out_tokens = estimate_tokens(reconstructed_text)
                req_cost = (in_tokens * INPUT_PRICE_PER_1M + out_tokens * OUTPUT_PRICE_PER_1M) / 1_000_000
                uncached_costs.append(req_cost)

                if duration < 0.25:
                    fast_cache_hits += 1

                # Deterministic retrieval hit check for connector/context cases
                retrieval_expected = case.get("retrieval_expected")
                if retrieval_expected:
                    retrieval_total += 1
                    normalized_resp = re.sub(r"[\u2010-\u2015\u2212]", "-", reconstructed_text).lower()
                    if all(term.lower() in normalized_resp for term in retrieval_expected):
                         retrieval_hits += 1

                # Grade with LLM Judge
                grade = await grade_response(
                    case["payload"],
                    case["expected_keywords"],
                    reconstructed_text,
                )
                scores.append(grade["score"])

                if grade["verdict"] == "PASS":
                    passed_cases += 1
                    print(f"✅ PASS | Score: {grade['score']:.2f} | Latency: {duration:.2f}s")
                else:
                    print(f"❌ FAIL | Score: {grade['score']:.2f} | Latency: {duration:.2f}s")
                    print(f"   🔍 Output: {reconstructed_text[:140]}")

                print(f"   💬 Judge: {grade['reason']}")

                detailed_results.append({
                    "id": case["id"],
                    "category": case["category"],
                    "prompt": case["payload"]["message"],
                    "expected_keywords": case["expected_keywords"],
                    "actual_response": reconstructed_text,
                    "score": grade["score"],
                    "verdict": grade["verdict"],
                    "reason": grade["reason"],
                    "latency_sec": round(duration, 3),
                })

            except Exception as e:
                print(f"⚠️  EVAL ERROR: {type(e).__name__}: {e}")
                scores.append(0.0)

            if REQUEST_DELAY_SEC > 0 and idx < total_cases:
                await asyncio.sleep(REQUEST_DELAY_SEC)

        counters_after = await fetch_cache_counters(client)

    # Aggregate Metrics
    mean_score = sum(scores) / total_cases if total_cases else 0.0
    success_rate = (passed_cases / total_cases) * 100 if total_cases else 0.0
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    p50_latency = percentile(latencies, 50)
    p95_latency = percentile(latencies, 95)

    retrieval_hit_rate = (
        (retrieval_hits / retrieval_total) * 100 if retrieval_total else 0.0
    )

    # Exact cache hit rate from Prometheus /metrics delta (with latency fallback)
    if counters_before and counters_after:
        delta_hits = max(0.0, counters_after[0] - counters_before[0])
        delta_misses = max(0.0, counters_after[1] - counters_before[1])
        total_cache_checks = delta_hits + delta_misses
        cache_hit_rate = (delta_hits / total_cache_checks) if total_cache_checks else 0.0
        cache_source = f"Prometheus ({int(delta_hits)} hits / {int(total_cache_checks)} lookups)"
    else:
        cache_hit_rate = (fast_cache_hits / total_cases) if total_cases else 0.0
        cache_source = f"Latency <0.25s fallback ({fast_cache_hits}/{total_cases})"

    avg_uncached_cost = (
        sum(uncached_costs) / len(uncached_costs) if uncached_costs else 0.0
    )
    uncached_cost_per_1k = avg_uncached_cost * 1000
    effective_cost_per_1k = uncached_cost_per_1k * (1.0 - cache_hit_rate)

    summary = {
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "success_rate_pct": round(success_rate, 1),
        "mean_faithfulness": round(mean_score, 3),
        "retrieval_hit_rate_pct": round(retrieval_hit_rate, 1),
        "cache_hit_rate_pct": round(cache_hit_rate * 100, 1),
        "cache_metric_source": cache_source,
        "avg_latency_sec": round(avg_latency, 3),
        "p50_latency_sec": round(p50_latency, 3),
        "p95_latency_sec": round(p95_latency, 3),
        "uncached_cost_per_1k_usd": round(uncached_cost_per_1k, 4),
        "effective_cost_per_1k_usd": round(effective_cost_per_1k, 4),
    }

    # Save full report + 10-case spot-check sheet
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": detailed_results}, f, indent=2)

    spot_check = build_spot_check_sample(detailed_results, target_size=10)
    with open(SPOT_CHECK_PATH, "w", encoding="utf-8") as f:
        json.dump(spot_check, f, indent=2)

    print("\n====================================================")
    print("⚖️  LLM JUDGE & GATEWAY BENCHMARK RESULTS")
    print("====================================================")
    print(f"Total Cases:               {total_cases}")
    print(f"Success Rate:              {success_rate:.1f}% ({passed_cases}/{total_cases})")
    print(f"Mean Faithfulness Score:   {mean_score:.2f} (Threshold: {PASS_THRESHOLD:.2f})")
    print(f"Retrieval Hit Rate (Jira): {retrieval_hit_rate:.1f}% ({retrieval_hits}/{retrieval_total})")
    print(f"Semantic Cache Hit Rate:   {cache_hit_rate * 100:.1f}% [{cache_source}]")
    print(f"Latency (Avg / p50 / p95): {avg_latency:.2f}s / {p50_latency:.2f}s / {p95_latency:.2f}s")
    print(f"Cost / 1,000 req (0% hit): ${uncached_cost_per_1k:.4f}")
    print(f"Cost / 1,000 req (actual): ${effective_cost_per_1k:.4f}")
    print("====================================================")
    print(f"📄 Full report saved:      {REPORT_PATH}")
    print(f"📝 Spot-check file saved:  {SPOT_CHECK_PATH}")

    if mean_score < PASS_THRESHOLD:
        print(f"🚨 QUALITY GATE FAILED: {mean_score:.2f} < {PASS_THRESHOLD:.2f}")
        sys.exit(1)

    print("🟢 QUALITY GATE PASSED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N test cases")
    args = parser.parse_args()
    asyncio.run(run_judge(limit=args.limit))