from dotenv import load_dotenv
load_dotenv()
import asyncio
import time # 👈 NEW: Required for calculating request duration
from fastapi import FastAPI, Depends, HTTPException, status, Request # 👈 NEW: Added Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from prometheus_fastapi_instrumentator import Instrumentator
from contextlib import asynccontextmanager
from app.database import engine, Base

from app.routers import chat, tasks, admin
from app.services.watchdog import auto_rollback_watchdog
from app.middleware.auth import create_access_token

# 👇 NEW: Import your custom metric from the telemetry file we discussed
from app.core.telemetry import GATEWAY_LATENCY

import grpc
from concurrent import futures
import uvicorn
from app.grpc import chat_pb2_grpc
from app.grpc.servicer import ChatServicer

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🗄️ Initializing database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    watchdog_task = asyncio.create_task(auto_rollback_watchdog())
    yield
    watchdog_task.cancel()



app = FastAPI(title="Streaming AI Gateway", lifespan=lifespan)

from app.core.telemetry import setup_telemetry

setup_telemetry(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000","*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 👇 NEW: Custom Middleware for p95 Latency Tracking
@app.middleware("http")
async def track_latency_middleware(request: Request, call_next):
    # 1. Skip the /metrics endpoint so Prometheus scraping doesn't skew your latency data
    if request.url.path == "/metrics":
        return await call_next(request)
        
    # 2. Start the stopwatch
    start_time = time.time()
    
    # 3. Process the actual user request
    response = await call_next(request)
    
    # 4. Stop the stopwatch and calculate the duration
    process_time = time.time() - start_time
    
    # 5. Record the duration in your custom Prometheus histogram
    GATEWAY_LATENCY.observe(process_time)
    
    return response

# Start Prometheus metrics collection (This will now also serve GATEWAY_LATENCY)
Instrumentator().instrument(app).expose(app)

app.include_router(chat.router)
app.include_router(tasks.router)
app.include_router(admin.router)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

async def serve_grpc():
    print("🚀 Starting gRPC server on port 50053...")
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServiceServicer_to_server(ChatServicer(), server)
    server.add_insecure_port('[::]:50053')
    await server.start()
    await server.wait_for_termination()

@app.post("/auth/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username == "admin" and form_data.password == "secret123":
        access_token = create_access_token(
            data={"sub": form_data.username, "tenant_id": "acme-corp", "role": "admin"}
        )
        return {"access_token": access_token, "token_type": "bearer"}
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    fastapi_server = uvicorn.Server(config)
    
    print("🌟 Booting Dual-Transport AI Gateway (REST + gRPC)...")
    await asyncio.gather(
        fastapi_server.serve(),
        serve_grpc()
    )

if __name__ == "__main__":
    asyncio.run(main())