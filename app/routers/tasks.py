import json
from fastapi import APIRouter, HTTPException, Depends
import asyncpg
from app.models.schemas import TaskIngestRequest
from app.services.db import get_db

router = APIRouter()

@router.post("/tasks/ingest")
async def ingest_task(request: TaskIngestRequest):
    pool = await get_db()
    
    try:
        async with pool.acquire() as conn:
            # Insert the task, returning the newly generated UUID
            task_id = await conn.fetchval("""
                INSERT INTO tasks (idempotency_key, payload)
                VALUES ($1, $2)
                RETURNING id
            """, request.idempotency_key, json.dumps({"text": request.document_text}))
            
            return {"status": "accepted", "task_id": str(task_id), "message": "Task queued for background processing."}
            
    except asyncpg.exceptions.UniqueViolationError:
        # IDEMPOTENCY IN ACTION: If the key already exists, we reject the duplicate!
        raise HTTPException(status_code=409, detail="Task with this idempotency key already exists.")