import os
import time
from fastapi import HTTPException
from app.services.cache import redis_client

async def check_rate_limit(
    client_id: str,
    limit: int | None = None,
    window_seconds: int = 60,
):
    """
    Limits requests using a Redis fixed-window counter.
    """
    effective_limit = (
        limit if limit is not None else int(os.getenv("RATE_LIMIT_PER_MINUTE", "5"))
    )

    current_window = int(time.time() // window_seconds)
    key = f"rate_limit:{client_id}:{current_window}"

    current_requests = await redis_client.incr(key)

    if current_requests == 1:
        await redis_client.expire(key, window_seconds)

    if current_requests > effective_limit:
        print(f"🛑 RATE LIMIT EXCEEDED for {client_id}")
        raise HTTPException(
            status_code=429,
            detail=f"Too Many Requests. You are limited to {effective_limit} requests per minute.",
        )

    print(f"🚦 Rate limit check passed: {current_requests}/{effective_limit}")
    return True