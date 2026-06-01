import uuid
import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import time

# Configure structlog to output JSON
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger()

class StructlogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Generate a unique ID for every single request
        request_id = str(uuid.uuid4())
        
        # 2. Bind the request_id to the logger so it attaches to every log in this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            path=request.url.path,
            method=request.method
        )
        
        start_time = time.time()
        
        # 3. Process the request
        response = await call_next(request)
        
        # 4. Log the completion and latency
        latency_ms = round((time.time() - start_time) * 1000, 2)
        await logger.ainfo("request_finished", status_code=response.status_code, latency_ms=latency_ms)
        
        return response