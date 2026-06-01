import os
import asyncpg

# Global connection pool
pool = None

async def init_db():
    global pool
    db_url = os.getenv("DATABASE_URL")
    pool = await asyncpg.create_pool(db_url)
    
    # Automatically create the tasks table on startup
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                idempotency_key VARCHAR(255) UNIQUE NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                payload JSONB NOT NULL,
                retries INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("🗄️ Postgres database initialized and tasks table verified.")

async def get_db():
    return pool