from pydantic import BaseModel
from typing import Optional

class ChatRequest(BaseModel):
    message: str
    session_id: str
    prompt_version: str = "v1"
    slack_thread: Optional[str] = None
    jira_ticket: Optional[str] = None

    # ... keep the existing ChatRequest ...

class TaskIngestRequest(BaseModel):
    document_text: str
    idempotency_key: str