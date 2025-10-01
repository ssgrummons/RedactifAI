from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import AsyncContextManager
import contextlib
import logging

logger = logging.getLogger(__name__)

class DatabaseSessionManager:
    """Manages both async and sync database sessions with dual interface"""
    
    def __init__(self, database_url: str, echo: bool = False):
        """
        Initialize session manager with both async and sync engines
        
        Args:
            database_url: PostgreSQL connection string - will be converted as needed
            echo: Whether to echo SQL statements for debugging
        """
        if 'sqlite' in database_url:
            if '+aiosqlite' in database_url:
                self.async_database_url = database_url
                self.sync_database_url = database_url.replace('+aiosqlite', '')
            else:
                # Assume sync SQLite, create async version
                self.sync_database_url = database_url
                self.async_database_url = database_url.replace('sqlite://', 'sqlite+aiosqlite://')
        # Handle PostgreSQL
        elif 'postgresql' in database_url:
            if not database_url.startswith('postgresql+asyncpg://'):
                self.async_database_url = database_url.replace('postgresql://', 'postgresql+asyncpg://')
            else:
                self.async_database_url = database_url
            
            self.sync_database_url = database_url.replace('postgresql+asyncpg://', 'postgresql+psycopg2://')
        else:
            raise ValueError(f"Unsupported database URL: {database_url}")
        
        # For sync: postgresql+psycopg2://... (or just postgresql://)
        self.sync_database_url = database_url.replace('postgresql+asyncpg://', 'postgresql+psycopg2://')
        
        # Async engine and session factory
        self.async_engine = create_async_engine(
            self.async_database_url, 
            echo=echo,
            future=True
        )
        self.async_session_factory = async_sessionmaker(
            bind=self.async_engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # Sync engine and session factory
        self.sync_engine = create_engine(
            self.sync_database_url,
            echo=echo,
            future=True
        )
        self.sync_session_factory = sessionmaker(
            bind=self.sync_engine,
            class_=Session,
            expire_on_commit=False
        )
    
    @contextlib.asynccontextmanager
    async def get_session(self):
        """
        Get async database session as context manager
        
        Usage:
            async with session_manager.get_session() as session:
                await session.commit()
        """
        async with self.async_session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    
    @contextlib.contextmanager
    def get_sync_session(self):
        """
        Get sync database session as context manager
        
        Usage:
            with session_manager.get_sync_session() as session:
                session.commit()
        """
        with self.sync_session_factory() as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise
    
    async def close(self):
        """Close both async and sync engines"""
        await self.async_engine.dispose()
        self.sync_engine.dispose()
    
    async def create_tables(self):
        """Create all tables defined in Base metadata (async version)"""
        from .models import Base  # Adjust import as needed
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    def create_tables_sync(self):
        """Create all tables defined in Base metadata (sync version)"""
        from .models import Base  # Adjust import as needed
        Base.metadata.create_all(self.sync_engine)