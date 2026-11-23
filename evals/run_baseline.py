from email.mime import application
import json
import time
import asyncio
import httpx
from sympy import content

# Configuration
GATEWAY_URL = "http://127.0.0.1:8000/chat/stream"
TEST_SET_PATH = "evals/test_set.json"

async def run_evaluation():
    print("🚀 Starting Eval Harness Baseline Run...")
    
    with open(TEST_SET_PATH, "r") as f:
        test_cases = json.load(f)

    total_cases = len(test_cases)
    passed_cases = 0
    latencies = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Mock auth token (update if your route requires a real one)
        headers = {"Authorization": "Bearer YOUR_TEST_TOKEN", "Content-Type": "application/json"}
        
        for case in test_cases:
            print(f"\nRunning {case['id']} ({case['category']})...")
            start_time = time.time()
            
            try:
                response = await client.post(
                    GATEWAY_URL, 
                    json=case["payload"],
                    headers=headers
                )
                
                duration = time.time() - start_time
                latencies.append(duration)
                raw_content = response.text
                reconstructed_text = "".join([
                    line[6:] for line in raw_content.split("\n") 
                    if line.startswith("data: ") and "[DONE]" not in line
                ])
                reconstructed_text = reconstructed_text.replace("‑", "-").replace("–", "-").replace("—", "-")
                # Baseline validation: Did the LLM include expected facts?
# 👇 FIX: Use reconstructed_text instead of content
                keywords_found = [kw for kw in case["expected_keywords"] if kw.lower() in reconstructed_text.lower()]                
                if response.status_code == 200 and keywords_found:
                    print(f"✅ PASS | Latency: {duration:.2f}s | Found: {keywords_found}")
                    passed_cases += 1
                else:
                    print(f"❌ FAIL | Latency: {duration:.2f}s | Status: {response.status_code}")
                    # 👇 FIX: Print the reconstructed_text instead of content
                    print(f"   🔍 Reconstructed text: {reconstructed_text[:250]}")
            except Exception as e:
                print(f"⚠️ ERROR: {e}")

    # Calculate and record baseline metrics
    success_rate = (passed_cases / total_cases) * 100 if total_cases > 0 else 0
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    
    print("\n" + "="*40)
    print("📊 BASELINE EVALUATION RESULTS")
    print("="*40)
    print(f"Total Cases: {total_cases}")
    print(f"Success Rate: {success_rate:.1f}%")
    print(f"Average Latency: {avg_latency:.2f}s")
    print("="*40)

if __name__ == "__main__":
    asyncio.run(run_evaluation())