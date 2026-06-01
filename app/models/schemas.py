from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str
    session_id: str
    prompt_version: str = "v1"

    # ... keep the existing ChatRequest ...

class TaskIngestRequest(BaseModel):
    document_text: str
    idempotency_key: str