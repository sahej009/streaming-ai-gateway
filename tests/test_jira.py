import asyncio
import httpx

async def test_jira_context():
    print("🔑 1. Logging in to get JWT token...")
    async with httpx.AsyncClient(timeout=None) as client:
        login_response = await client.post(
            "http://localhost:8000/auth/token",
            data={"username": "admin", "password": "secret123"}
        )
        token = login_response.json().get("access_token")
        
        print(f"✅ Token acquired. Sending request with Jira ticket...\n")
        
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "message": "Can you check the status of this ticket and tell me what it means?",
            "session_id": "test-jira-1",
            # 👇 A fake Jira ticket ID
            "jira_ticket": "PROJ-999" 
        }
        
        try:
            async with client.stream("POST", "http://localhost:8000/chat/stream", json=payload, headers=headers) as response:
                print(f"📡 HTTP Status Code: {response.status_code}\n")
                async for chunk in response.aiter_text():
                    print(chunk, end="", flush=True)
        except Exception as e:
            print(f"\n❌ Error connecting: {e}")

if __name__ == "__main__":
    asyncio.run(test_jira_context())