import asyncio
import httpx
import json
from app.services.prompt_registry import redis_client

async def auto_rollback_watchdog():
    print("🐕 Watchdog started. Monitoring canary health...")
    
    # Run forever in the background
    while True:
        try:
            # 1. Check if there is an active canary deployment
            canary_raw = await redis_client.get("prompt:canary")
            
            if canary_raw:
                canary_config = json.loads(canary_raw.decode("utf-8"))
                canary_version = canary_config.get("version")

                # 2. Query Prometheus API for this version's score
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "http://prometheus:9090/api/v1/query", # Use 'prometheus' hostname inside Docker
                        params={"query": f'hallucination_score{{prompt_version="{canary_version}"}}'}
                    )
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        results = data.get("data", {}).get("result", [])
                        
                        if results:
                            # Prometheus returns values as a string list: [timestamp, "0.08"]
                            score = float(results[0]["value"][1])
                            print(f"🐕 Watchdog check: Canary {canary_version} score is {score:.2f}")

                            # 3. The Executioner's Block
                            if score < 0.75:
                                print(f"🚨 ALERT! Canary {canary_version} failed evaluation (Score: {score:.2f})!")
                                print("🔄 ROLLING BACK TO STABLE VERSION...")
                                await redis_client.delete("prompt:canary")
                                
        except Exception as e:
            print(f"⚠️ Watchdog encountered an error: {e}")

        # Sleep for 10 seconds before checking again (in production, this would be 5 minutes)
        await asyncio.sleep(10)