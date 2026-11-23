import pytest
import asyncio
from httpx import AsyncClient
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch
import os
# 👇 NEW: Inject a fake key BEFORE importing the app
os.environ["GROQ_API_KEY"] = "mock_key_for_testing_purposes"

from app.main import app

# If your routes use Depends() for auth or DB, mock them out for isolated testing

from app.middleware.auth import get_current_user, TokenData

# Override the auth dependency so we don't need a real JWT for the test
app.dependency_overrides[get_current_user] = lambda: TokenData(user_id="test_user", tenant_id="acme-corp", role="admin")

@pytest.mark.asyncio
@patch("app.routers.chat.stream_llm_tokens") # Intercept the LLM call
async def test_fallback_routing_on_primary_timeout(mock_stream_llm):
    
    # 1. Define the Chaos: How the mock should behave
    async def mock_llm_generator(*args, **kwargs):
        model = kwargs.get("model")
        
        if model == "llama3-8b-8192":
            # Simulate the primary model hanging and timing out
            raise asyncio.TimeoutError()
            
        elif model == "llama-3.1-8b-instant":
            # Simulate the fallback model succeeding
            yield "data: This is the fallback saving the day\n\n"
            yield "data: [DONE]\n\n"

    # Assign our chaotic generator to the mock
    mock_stream_llm.side_effect = mock_llm_generator

    # 2. Fire the Request
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/chat/stream",
            json={
                "message": "Write a python script", 
                "session_id": "test_123", 
                "prompt_version": "v1"
            }
        )
        
        # 3. Assert the results
        assert response.status_code == 200
        
        # Read the streaming response content
        content = response.content.decode()
        
        # Verify the user actually got the fallback text
        assert "This is the fallback saving the day" in content
        
        # Verify the router actually tried both models
        assert mock_stream_llm.call_count == 2