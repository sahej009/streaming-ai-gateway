import os
import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Text, DateTime

# Grab the connection URL from Docker
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://admin:secretpassword@localhost:5432/ai_gateway")

# Create the async engine
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# Define the Audit Log table blueprint
class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    tenant_id = Column(String, index=True)
    user_id = Column(String, index=True)
    prompt_version = Column(String)
    user_message = Column(Text)
    llm_response = Column(Text)

# Dependency to use in our FastAPI routes
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session