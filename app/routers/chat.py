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

# 👇 1. IMPORT YOUR AUTH DEPENDENCIES
from app.middleware.auth import get_current_user, TokenData

# Get the registry instance here
registry = get_registry()

router = APIRouter()

# 👇 2. LOCK DOWN THE POST ENDPOINT
@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    current_user: TokenData = Depends(get_current_user), # <-- Security Gate!
    db: AsyncSession = Depends(get_db) # 👇 NEW: Security AND Database!
):
    print(f"🔒 Stream requested by User: {current_user.user_id} | Tenant: {current_user.tenant_id}")

    await check_rate_limit(client_id=request.session_id, limit=5, window_seconds=60)
    prompt_version = await registry.resolve_version(request.prompt_version)
    cached_response = await check_semantic_cache(request.message, prompt_version=prompt_version)
    
    if cached_response:
        async def fake_stream():
            yield f"data: {cached_response}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(fake_stream(), media_type="text/event-stream")

    async def process_and_cache():
        full_response = ""
        
        async for chunk in stream_llm_tokens(request.message, version=prompt_version, tenant_id=current_user.tenant_id):
            yield chunk
            if chunk.startswith("data: ") and chunk != "data: [DONE]\n\n":
                full_response += chunk[6:].strip("\n")
                
        asyncio.create_task(save_to_cache(request.message, full_response, prompt_version=prompt_version))

        # 👇 NEW: Save the interaction to the Audit Log!
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

# 👇 3. LOCK DOWN THE WEBSOCKET ENDPOINT
@router.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    current_user: TokenData = Depends(get_current_user) # <-- Security Gate!
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

            # 1. DYNAMICALLY RESOLVE CANARY OR ACTIVE ROUTING
            prompt_version = await registry.resolve_version(client_requested_version)
            print(f"🚦 Routing WS request to prompt version: {prompt_version}")

            # --- 2. CHECK THE CACHE FIRST ---
            cached_response = await check_semantic_cache(message, prompt_version=prompt_version)
            
            if cached_response:
                # If hit, blast the entire response back instantly and end the stream
                await websocket.send_text(f"data: {cached_response}\n\n")
                await websocket.send_text("data: [DONE]\n\n")
                continue # Skip the LLM completely!

            # --- 3. CACHE MISS: STREAM FROM LLM ---
            async def stream_to_client():
                full_text_accumulator = "" 
                max_retries = 3
                delays = [1, 2, 4]
                
                for attempt in range(max_retries + 1):
                    try:
                        # 👇 Pass the tenant_id to your LLM service here as well
                        async for chunk in stream_llm_tokens(message, version=prompt_version, tenant_id=current_user.tenant_id):
                            await websocket.send_text(chunk)
                            
                            # Strip the "data: \n\n" formatting to just save the raw text
                            if chunk != "data: [DONE]\n\n":
                                raw_token = chunk.replace("data: ", "").replace("\n\n", "")
                                full_text_accumulator += raw_token
                                
                        # --- 4. SAVE THE COMPLETED RESPONSE TO CACHE ---
                        asyncio.create_task(save_to_cache(message, full_text_accumulator, prompt_version=prompt_version))
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