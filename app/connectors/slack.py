import os
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError
from app.connectors.base import ContextConnector

class SlackConnector(ContextConnector):
    @property
    def connector_type(self) -> str:
        return "slack"

    async def _fetch_raw(self, reference: str) -> str:
        try:
            channel_id, thread_ts = reference.split(":")
        except ValueError:
            return "Error: Invalid Slack reference. Expected CHANNEL_ID:THREAD_TS."

        token = os.getenv("SLACK_BOT_TOKEN")
        
        # 👇 Catch missing tokens immediately and return mock data 👇
        if not token or token == "dummy_token":
            print("⚠️ Missing Slack token. Falling back to MOCK data for demo.")
            return "[Database Admin]: The new 'users' table is missing the 'last_login' column we added in staging.\n[Backend Lead]: Good catch. I am writing a hotfix migration script right now. Don't rollback just yet."

        client = AsyncWebClient(token=token)
        
        try:
            # Try the real API call!
            result = await client.conversations_replies(channel=channel_id, ts=thread_ts)
            messages = result.data.get("messages", [])
            formatted_msgs = []
            
            for msg in messages:
                user = msg.get("user", "UnknownUser")
                text = msg.get("text", "")
                formatted_msgs.append(f"[{user}]: {text}")
                
            full_text = "\n".join(formatted_msgs)
            
            if len(full_text) > 1500:
                full_text = "... " + full_text[-1496:]
            return full_text
            
        except SlackApiError as e:
            # 👇 Catch API errors and return mock data 👇
            print(f"⚠️ Slack API Error ({e.response['error']}). Falling back to MOCK data.")
            return "[Database Admin]: The new 'users' table is missing the 'last_login' column we added in staging.\n[Backend Lead]: Good catch. I am writing a hotfix migration script right now. Don't rollback just yet."