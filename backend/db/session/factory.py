from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.env_loader import EnvLoader


class AsyncSessionFactory:
    def __init__(self) -> None:
        self._engine: AsyncEngine = create_async_engine(
            EnvLoader.get("SUPABASE_POSTGRES_URI"),
            echo=False,
            future=True,
            pool_pre_ping=True,  # 💡 Checks connections before using them
            pool_recycle=1800,  # 🔄 Recycles conns after 30 min (prevents timeouts)
            pool_size=5,  # 🎛️ Set if you want a fixed pool size
            max_overflow=5,  # ⬆️ Allow extra conns temporarily
            connect_args={"prepare_threshold": None},
        )
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    @asynccontextmanager
    async def new_session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self._sessionmaker() as session:
            try:
                yield session
            finally:
                await session.close()

    def engine(self) -> AsyncEngine:
        return self._engine
