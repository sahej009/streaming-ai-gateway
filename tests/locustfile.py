import os
import time
import jwt
from dotenv import load_dotenv
from locust import HttpUser, between, task

# Load your actual secret key from .env if present
load_dotenv()
SECRET_KEY = (
    os.getenv("JWT_SECRET_KEY")
    or os.getenv("SECRET_KEY")
    or os.getenv("JWT_SECRET")
    or "super-secret-key-change-this-in-production-99887766"
)
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")


def generate_locust_token(user_id: str) -> str:
    """Generate a valid signed JWT for FastAPI auth middleware."""
    payload = {
        "sub": f"locust-user-{user_id}",
        "tenant_id": "acme-corp",
        "role": "admin",
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


class GatewayUser(HttpUser):
    # Hardcode the FastAPI backend host so Locust never hits port 8090
    host = "http://localhost:8000"
    wait_time = between(0.1, 0.5)

    def on_start(self):
        # First try fetching a token from FastAPI's /auth/token endpoint
        token = None
        try:
            res = self.client.post(
                "/auth/token",
                json={"tenant_id": "acme-corp", "sub": "locust-user"},
            )
            if res.status_code == 200 and "access_token" in res.json():
                token = res.json()["access_token"]
        except Exception:
            pass

        # Fallback to locally signed JWT
        if not token:
            user_id = (
                self.environment.runner.user_count
                if self.environment.runner
                else "1"
            )
            token = generate_locust_token(str(user_id))

        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

    @task
    def stream_chat(self):
        payload = {
            "message": "Explain microservice architecture in 2 sentences.",
            "session_id": f"locust-session-{time.time()}",
            "prompt_version": "v1",
            "jira_ticket": None,
            "slack_thread": None,
        }

        with self.client.post(
            "/chat/stream",
            json=payload,
            headers=self.headers,
            stream=True,
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                for _ in response.iter_lines():
                    pass
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}: {response.text}")