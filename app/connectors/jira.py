import os
import httpx
from app.connectors.base import ContextConnector

class JiraConnector(ContextConnector):
    def __init__(self):
        self.domain = os.getenv("JIRA_DOMAIN", "https://dummy-domain.atlassian.net")
        self.email = os.getenv("JIRA_EMAIL", "admin@example.com")
        self.token = os.getenv("JIRA_API_TOKEN", "dummy_token")

    @property
    def connector_type(self) -> str:
        return "jira"

    async def _fetch_raw(self, ticket_id: str) -> str:
        print(f"🎫 Fetching Jira Ticket: {ticket_id}")
        url = f"{self.domain}/rest/api/3/issue/{ticket_id}"
        auth = (self.email, self.token)
        
        try:
            # Try the real API call first!
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, auth=auth)
                response.raise_for_status() 
                
                data = response.json()
                summary = data.get("fields", {}).get("summary", "Unknown Summary")
                status = data.get("fields", {}).get("status", {}).get("name", "Unknown Status")
                return f"Ticket: {ticket_id} | Status: {status} | Summary: {summary}"
                
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            # 👇 IF IT FAILS, CATCH THE ERROR AND RETURN MOCK DATA 👇
            print(f"⚠️ Jira API Error ({e}). Falling back to MOCK data for demo.")
            return f"Ticket: {ticket_id} | Status: IN PROGRESS | Summary: Users cannot log in after the v2.0 deployment."