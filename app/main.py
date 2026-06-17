import asyncio
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from prometheus_fastapi_instrumentator import Instrumentator
from contextlib import asynccontextmanager
from app.database import engine, Base

from app.routers import chat, tasks, admin
from app.services.watchdog import auto_rollback_watchdog

# 👇 Import the token generator we just built
from app.middleware.auth import create_access_token

import grpc
from concurrent import futures
import uvicorn
from app.grpc import chat_pb2_grpc
from app.grpc.servicer import ChatServicer

# 2. Add the lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 👇 NEW: Create the database tables on startup
    print("🗄️ Initializing database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # Start the watchdog as a background task
    watchdog_task = asyncio.create_task(auto_rollback_watchdog())
    yield
    # Clean up when the server shuts down
    watchdog_task.cancel()

# 3. Attach the lifespan to the FastAPI app
app = FastAPI (title="Streaming AI Gateway", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000","*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Start Prometheus metrics collection
Instrumentator().instrument(app).expose(app)

app.include_router(chat.router)
app.include_router(tasks.router)
app.include_router(admin.router)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# 👇 NEW: The gRPC Server Boot sequence
async def serve_grpc():
    print("🚀 Starting gRPC server on port 50051...")
    # 1. Create an async gRPC server with a thread pool
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    
    # 2. Attach your custom ChatServicer to the server
    chat_pb2_grpc.add_ChatServiceServicer_to_server(ChatServicer(), server)
    
    # 3. Bind it to port 50051 (the standard gRPC port) 
    server.add_insecure_port('[::]:50051')
    
    # 4. Start the server and keep it alive
    await server.start()
    await server.wait_for_termination()

#  NEW: The Login Route
@app.post("/auth/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Mock user verification (In a real app, you would check a Postgres database here)
    if form_data.username == "admin" and form_data.password == "secret123":
        # Create a token and inject our custom Tenant ID and Role
        access_token = create_access_token(
            data={"sub": form_data.username, "tenant_id": "acme-corp", "role": "admin"}
        )
        return {"access_token": access_token, "token_type": "bearer"}
    
    # If the password is wrong, kick them out
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

#  NEW: The Master Dual-Boot Function
async def main():
    # 1. Configure the Uvicorn server for FastAPI
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    fastapi_server = uvicorn.Server(config)
    
    # 2. Run both servers concurrently using asyncio.gather 
    print("🌟 Booting Dual-Transport AI Gateway (REST + gRPC)...")
    await asyncio.gather(
        fastapi_server.serve(),
        serve_grpc()
    )

# 3. If the script is run directly, start the master loop
if __name__ == "__main__":
    asyncio.run(main())