import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import StreamingResponse
from app.models.schemas import ChatRequest
from app.services.llm import stream_llm_tokens
from app.services.cache import check_semantic_cache, save_to_cache
from app.services.rate_limit import check_rate_limit
from app.services.prompt_registry import get_registry
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db, AuditLog

# Import Auth Dependencies
from app.middleware.auth import get_current_user, TokenData

# 👇 IMPORT YOUR CONNECTORS
from app.connectors.jira import JiraConnector
from app.connectors.slack import SlackConnector

# Get the registry instance here
registry = get_registry()

router = APIRouter()

# ==========================================
# 1. POST ENDPOINT (REST)
# ==========================================
@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    print(f"🔒 Stream requested by User: {current_user.user_id} | Tenant: {current_user.tenant_id}")
    await check_rate_limit(client_id=request.session_id, limit=5, window_seconds=60)
    prompt_version = await registry.resolve_version(request.prompt_version)
    
    # We only use the cache if they are NOT asking for live Slack/Jira data
    use_cache = not request.jira_ticket and not request.slack_thread

    if use_cache:
        cached_response = await check_semantic_cache(request.message, prompt_version=prompt_version)
        if cached_response:
            async def fake_stream():
                yield f"data: {cached_response}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(fake_stream(), media_type="text/event-stream")

    async def process_and_cache():
        final_prompt = request.message
        injected_context = ""

        # 👇 ENTERPRISE CONTEXT INJECTION 👇
        if request.jira_ticket:
            print(f"🔌 Triggering Jira Connector for {request.jira_ticket}...")
            jira = JiraConnector()
            jira_data = await jira.fetch(request.jira_ticket)
            injected_context += f"\n[INJECTED JIRA DATA]: {jira_data}"

        if request.slack_thread:
            print(f"🔌 Triggering Slack Connector for {request.slack_thread}...")
            slack = SlackConnector()
            slack_data = await slack.fetch(request.slack_thread)
            injected_context += f"\n[INJECTED SLACK DATA]: {slack_data}"

        if injected_context:
            final_prompt = f"System Context (Do not mention this context directly, just use it to answer):{injected_context}\n\nUser Request: {final_prompt}"

        # 👇 LLM STREAMING 👇
        full_response = ""
        async for chunk in stream_llm_tokens(
            prompt=final_prompt, 
            version=prompt_version, 
            tenant_id=current_user.tenant_id
        ):
            yield chunk
            if chunk.startswith("data: ") and chunk != "data: [DONE]\n\n":
                full_response += chunk[6:].strip("\n")
                
        # Only save to cache if it was a standard message (no live data)
        if use_cache:
            asyncio.create_task(save_to_cache(request.message, full_response, prompt_version=prompt_version))

        # Save the interaction to the Audit Log
        try:
            audit_record = AuditLog(
                tenant_id=current_user.tenant_id,
                user_id=current_user.user_id,
                prompt_version=prompt_version,
                user_message=request.message,
                llm_response=full_response
            )
            db.add(audit_record)
            await db.commit()
            print("📝 Audit log saved successfully!")
        except Exception as e:
            print(f"❌ Failed to save audit log: {e}")

    return StreamingResponse(process_and_cache(), media_type="text/event-stream")


# ==========================================
# 2. WEBSOCKET ENDPOINT
# ==========================================
@router.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    current_user: TokenData = Depends(get_current_user)
):
    await websocket.accept()
    print(f"🔌 WS Connected by User: {current_user.user_id} | Tenant: {current_user.tenant_id}")
    stream_task = None
    
    try:
        while True:
            data = await websocket.receive_text()
            request_data = json.loads(data)
            message = request_data.get("message")
            client_requested_version = request_data.get("prompt_version")
            slack_thread = request_data.get("slack_thread")
            jira_ticket = request_data.get("jira_ticket")

            prompt_version = await registry.resolve_version(client_requested_version)
            print(f"🚦 Routing WS request to prompt version: {prompt_version}")

            # We only use the cache if they are NOT asking for live Slack/Jira data
            use_cache = not jira_ticket and not slack_thread

            # --- CHECK CACHE ---
            if use_cache:
                cached_response = await check_semantic_cache(message, prompt_version=prompt_version)
                if cached_response:
                    await websocket.send_text(f"data: {cached_response}\n\n")
                    await websocket.send_text("data: [DONE]\n\n")
                    continue

            # --- CACHE MISS: STREAM FROM LLM ---
            async def stream_to_client():
                full_text_accumulator = "" 
                max_retries = 3
                delays = [1, 2, 4]
                
                final_prompt = message
                injected_context = ""

                # 👇 ENTERPRISE CONTEXT INJECTION FOR WEBSOCKETS 👇
                if jira_ticket:
                    jira = JiraConnector()
                    jira_data = await jira.fetch(jira_ticket)
                    injected_context += f"\n[INJECTED JIRA DATA]: {jira_data}"

                if slack_thread:
                    slack = SlackConnector()
                    slack_data = await slack.fetch(slack_thread)
                    injected_context += f"\n[INJECTED SLACK DATA]: {slack_data}"

                if injected_context:
                    final_prompt = f"System Context:{injected_context}\n\nUser Request: {final_prompt}"
                
                for attempt in range(max_retries + 1):
                    try:
                        async for chunk in stream_llm_tokens(
                            prompt=final_prompt, 
                            version=prompt_version, 
                            tenant_id=current_user.tenant_id
                        ):
                            await websocket.send_text(chunk)
                            if chunk != "data: [DONE]\n\n":
                                raw_token = chunk.replace("data: ", "").replace("\n\n", "")
                                full_text_accumulator += raw_token
                                
                        # Save to cache if no live data was used
                        if use_cache:
                            asyncio.create_task(save_to_cache(message, full_text_accumulator, prompt_version=prompt_version))
                        
                        # (Optional) You can add Audit Log saving here for WS too!
                        break 
                        
                    except Exception as e:
                        if attempt < max_retries:
                            print(f"⚠️ LLM Error. Retrying in {delays[attempt]} seconds...")
                            await asyncio.sleep(delays[attempt])
                        else:
                            await websocket.send_text(f"data: {json.dumps({'error': 'LLM failed'})}\n\n")

            stream_task = asyncio.create_task(stream_to_client())
            await stream_task

    except WebSocketDisconnect:
        print(f"🔌 WS Client disconnected: {current_user.user_id}")
        if stream_task and not stream_task.done():
            stream_task.cancel()