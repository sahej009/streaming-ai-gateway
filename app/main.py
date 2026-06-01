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
app = FastAPI(title="Streaming AI Gateway", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

# 👇 NEW: The Login Route
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