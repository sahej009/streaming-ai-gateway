import asyncio
import json
from app.services.db import get_db
from app.services.llm import stream_llm_tokens

async def process_background_tasks():
    print("👷 Background worker started. Polling for tasks...")
    
    while True:
        try:
            pool = await get_db()
            if not pool:
                await asyncio.sleep(5)
                continue
                
            async with pool.acquire() as conn:
                # Find ONE pending task and immediately mark it as 'processing' so no other worker grabs it
                task = await conn.fetchrow("""
                    UPDATE tasks 
                    SET status = 'processing', updated_at = CURRENT_TIMESTAMP
                    WHERE id = (
                        SELECT id FROM tasks WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED
                    )
                    RETURNING id, payload, retries
                """)
                
                if task:
                    task_id = task['id']
                    payload = json.loads(task['payload'])
                    print(f"⚙️ Worker processing task: {task_id}")
                    
                    # 1. Ask the LLM to summarize the document (we just gather the stream into a string)
                    prompt = f"Summarize this document: {payload['text'][:500]}"
                    summary = ""
                    async for chunk in stream_llm_tokens(prompt):
                        if chunk.startswith("data: ") and chunk != "data: [DONE]\n\n":
                            summary += chunk[6:].strip("\n")
                    
                    # 2. Mark the task as completed and save the summary!
                    await conn.execute("""
                        UPDATE tasks 
                        SET status = 'completed', payload = payload || $2::jsonb, updated_at = CURRENT_TIMESTAMP
                        WHERE id = $1
                    """, task_id, json.dumps({"summary": summary}))
                    
                    print(f"✅ Worker finished task: {task_id}")
                    
        except Exception as e:
            print(f"❌ Worker error: {e}")
            
        # Wait 5 seconds before checking the database again
        await asyncio.sleep(5)