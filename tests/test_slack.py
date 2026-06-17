import asyncio
import httpx

async def test_slack_context():
    print("🔑 1. Logging in to get JWT token...")
    async with httpx.AsyncClient(timeout=None) as client:
        # 1. Hit the login endpoint we created in Phase 4
        login_response = await client.post(
            "http://localhost:8000/auth/token",
            data={"username": "admin", "password": "secret123"}
        )
        token = login_response.json().get("access_token")
        
        if not token:
            print("❌ Login failed!")
            return

        print(f"✅ Token acquired. Sending request with Slack thread...\n")
        
        # 2. Setup headers and payload
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "message": "Summarize the discussion in this thread.",
            "session_id": "test-slack-1",
            # 👇 Put your real Slack Channel ID and Timestamp here!
            "slack_thread": "C12345678:1690000000.000000" 
        }
        
        # 3. Stream the response!
        try:
            async with client.stream("POST", "http://localhost:8000/chat/stream", json=payload, headers=headers) as response:
                
                # 👇 NEW: Print the exact status code and headers before the stream starts!
                print(f"📡 HTTP Status Code: {response.status_code}")
                print(f"📡 Headers: {response.headers}\n")
                
                async for chunk in response.aiter_text():
                    print(chunk, end="", flush=True)
        except Exception as e:
            print(f"\n❌ Error connecting: {e}")
if __name__ == "__main__":
    asyncio.run(test_slack_context())