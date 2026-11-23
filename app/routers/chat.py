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

from app.connectors.jira import JiraConnector
from app.connectors.slack import SlackConnector

# 👇 NEW: Import telemetry
from app.core.telemetry import CACHE_HITS, CACHE_MISSES, LLM_COST_USD

registry = get_registry()
router = APIRouter()

# Pricing constants (adjust as needed)
INPUT_COST = 0.05 / 1_000_000
OUTPUT_COST = 0.08 / 1_000_000

@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    print(f"🔒 Stream requested by User: {current_user.user_id} | Tenant: {current_user.tenant_id}")
    await check_rate_limit(client_id=request.session_id, window_seconds=60)
    prompt_version = await registry.resolve_version(request.prompt_version)
    
    use_cache = not request.jira_ticket and not request.slack_thread

    # --- 1. CACHE CHECK ---
    if use_cache:
        cached_response = await check_semantic_cache(request.message, prompt_version=prompt_version)
        if cached_response:
            CACHE_HITS.inc() # 👈 Track Hit
            async def fake_stream():
                yield f"data: {cached_response}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(fake_stream(), media_type="text/event-stream")

    # --- 2. CACHE MISS & LLM ROUTING ---
    CACHE_MISSES.inc() # 👈 Track Miss

    async def process_and_cache():
        final_prompt = request.message
        injected_context = ""

        if request.jira_ticket:
            jira = JiraConnector()
            jira_data = await jira.fetch(request.jira_ticket)
            injected_context += f"\n[INJECTED JIRA DATA]: {jira_data}"

        if request.slack_thread:
            slack = SlackConnector()
            slack_data = await slack.fetch(request.slack_thread)
            injected_context += f"\n[INJECTED SLACK DATA]: {slack_data}"

        if injected_context:
            final_prompt = f"System Context:{injected_context}\n\nUser Request: {final_prompt}"

        full_response = ""
        
        # 👇 CHANGED: Updated Fallback Model Configuration with active Groq models
        models_to_try = ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
        success = False

        for model in models_to_try:
            try:
                # 👇 NEW: Strict 10-second timeout per model attempt
                async with asyncio.timeout(10.0):
                    # Now we can iterate the generator safely
                    async for chunk in stream_llm_tokens(
                        prompt=final_prompt, 
                        version=prompt_version, 
                        tenant_id=current_user.tenant_id,
                        model=model 
                    ):
                        yield chunk
                        if chunk.startswith("data: ") and chunk != "data: [DONE]\n\n":
                            full_response += chunk[6:].strip("\n")

                success = True
                break # If successful, break out of the fallback loop

            except asyncio.TimeoutError:
                print(f"⚠️ Timeout on model {model}. Attempting fallback...")
                continue # Try the next model
            except Exception as e:
                print(f"⚠️ Error on model {model}: {e}. Attempting fallback...")
                continue
                
        if not success:
            yield f"data: {json.dumps({'error': 'All models failed or timed out.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # --- 3. POST-PROCESSING (Cost & Cache) ---
        # Note: In a streaming setup, calculating exact tokens is tricky without a separate callback.
        # A rough heuristic for cost is (len(full_response) / 4) to estimate tokens.
        estimated_tokens = len(full_response) / 4
        LLM_COST_USD.inc(estimated_tokens * OUTPUT_COST)

        if use_cache:
            asyncio.create_task(save_to_cache(request.message, full_response, prompt_version=prompt_version))

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
        except Exception as e:
            print(f"❌ Failed to save audit log: {e}")

    return StreamingResponse(process_and_cache(), media_type="text/event-stream")