"""FastAPI dependency injection for database, storage, and auth."""

from typing import Generator
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.db.session import DatabaseSessionManager
from src.config.database import DatabaseSettings
from src.config.storage import StorageSettings
from src.config.provider import ProviderSettings
from src.config.settings import Settings
from src.storage.factory import create_storage_backend
from src.storage.base import StorageBackend
from src.api.auth import SecurityScheme, NoOpAuth


# Global instances (initialized on startup)
_db_manager: DatabaseSessionManager | None = None
_general_settings: Settings | None = None
_storage_settings: StorageSettings | None = None
_provider_settings: ProviderSettings | None = None


def initialize_dependencies():
    """
    Initialize global dependencies on application startup.
    
    Call this in FastAPI lifespan/startup event.
    """
    global _db_manager, _general_settings, _storage_settings, _provider_settings
    
    db_settings = DatabaseSettings()
    _db_manager = DatabaseSessionManager(
        database_url=db_settings.connection_string,
        echo=False
    )
    
    _general_settings = Settings()
    _storage_settings = StorageSettings()
    _provider_settings = ProviderSettings()


async def cleanup_dependencies():
    """
    Cleanup dependencies on application shutdown.
    
    Call this in FastAPI lifespan/shutdown event.
    """
    global _db_manager
    if _db_manager:
        await _db_manager.close()


def get_db_session() -> Generator[Session, None, None]:
    """
    Dependency for database session.
    
    Usage:
        @app.get("/jobs/{job_id}")
        def get_job(job_id: str, db: Session = Depends(get_db_session)):
            ...
    """
    if not _db_manager:
        raise RuntimeError("Dependencies not initialized. Call initialize_dependencies() on startup.")
    
    with _db_manager.get_sync_session() as session:
        yield session


def get_phi_storage() -> StorageBackend:
    """
    Dependency for PHI storage backend.
    
    Usage:
        @app.post("/jobs")
        def create_job(phi_storage: StorageBackend = Depends(get_phi_storage)):
            ...
    """
    if not _storage_settings:
        raise RuntimeError("Dependencies not initialized.")
    
    return create_storage_backend("phi", settings=_storage_settings)


def get_clean_storage() -> StorageBackend:
    """
    Dependency for clean storage backend.
    
    Usage:
        @app.get("/jobs/{job_id}/download")
        def download_result(clean_storage: StorageBackend = Depends(get_clean_storage)):
            ...
    """
    if not _storage_settings:
        raise RuntimeError("Dependencies not initialized.")
    
    return create_storage_backend("clean", settings=_storage_settings)


def get_general_settings() -> Settings:
    """Dependency for general application settings."""
    if not _general_settings:
        raise RuntimeError("Dependencies not initialized.")
    return _general_settings


def get_provider_settings() -> ProviderSettings:
    """Dependency for provider settings."""
    if not _provider_settings:
        raise RuntimeError("Dependencies not initialized.")
    return _provider_settings


def get_current_auth() -> SecurityScheme:
    """
    Dependency for authentication.
    
    Returns NoOpAuth for MVP. Swap this out later for real auth:
    - return APIKeyAuth(valid_keys=settings.API_KEYS)
    - return JWTAuth(secret_key=settings.JWT_SECRET)
    
    Usage:
        @app.post("/jobs")
        async def create_job(
            auth: SecurityScheme = Depends(get_current_auth),
            request: Request = ...
        ):
            await auth.verify(request)
            ...
    """
    return NoOpAuth()


async def verify_authentication(
    request: Request,
    auth: SecurityScheme = Depends(get_current_auth)
) -> bool:
    """
    Dependency that verifies authentication.
    
    Can be used directly in endpoints that need auth:
        @app.post("/jobs")
        async def create_job(
            authenticated: bool = Depends(verify_authentication),
            ...
        ):
            # If we get here, auth passed
    """
    return await auth.verify(request)
