import time
from fastapi import HTTPException
from app.services.cache import redis_client

async def check_rate_limit(client_id: str, limit: int = 5, window_seconds: int = 60):
    """
    Limits requests using a Redis fixed-window counter.
    """
    # Create a unique time-based key, e.g., "rate_limit:123:2849302"
    current_window = int(time.time() // window_seconds)
    key = f"rate_limit:{client_id}:{current_window}"
    
    # Increment the counter for this specific window
    current_requests = await redis_client.incr(key)
    
    # If this is the very first request in this window, set the key to expire
    if current_requests == 1:
        await redis_client.expire(key, window_seconds)
        
    # If they exceeded the limit, drop the hammer!
    if current_requests > limit:
        print(f"🛑 RATE LIMIT EXCEEDED for {client_id}")
        raise HTTPException(
            status_code=429, 
            detail="Too Many Requests. You are limited to 5 requests per minute."
        )
        
    print(f"🚦 Rate limit check passed: {current_requests}/{limit}")
    return True