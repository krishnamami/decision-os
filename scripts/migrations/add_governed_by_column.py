"""Add decision_outputs.governed_by (jsonb). Idempotent."""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    import asyncpg
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("ALTER TABLE decision_outputs ADD COLUMN IF NOT EXISTS governed_by jsonb")
        print("governed_by column ensured")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
