"""Factory for creating storage backends with two-bucket architecture."""

from typing import Literal
from src.storage.base import StorageBackend
from src.storage.local import LocalStorageBackend
from src.storage.s3 import S3StorageBackend
from src.config.storage import StorageSettings


BucketType = Literal["phi", "clean"]


def create_storage_backend(
    bucket_type: BucketType,
    settings: StorageSettings | None = None
) -> StorageBackend:
    """
    Create a storage backend for either PHI or clean documents.
    
    Args:
        bucket_type: "phi" for input documents (PHI), "clean" for output documents
        settings: Optional settings instance (creates new if not provided)
    
    Returns:
        Configured storage backend
        
    Example:
        # In production
        phi_storage = create_storage_backend("phi")
        clean_storage = create_storage_backend("clean")
        
        # In tests with dependency injection
        test_settings = StorageSettings(STORAGE_BACKEND="local")
        phi_storage = create_storage_backend("phi", settings=test_settings)
    """
    if settings is None:
        settings = StorageSettings()
    
    backend_type = settings.STORAGE_BACKEND.lower()
    
    if backend_type == "local":
        return _create_local_backend(bucket_type, settings)
    elif backend_type == "s3":
        return _create_s3_backend(bucket_type, settings)
    else:
        raise ValueError(f"Unknown storage backend: {backend_type}")


def _create_local_backend(bucket_type: BucketType, settings: StorageSettings) -> LocalStorageBackend:
    """Create local storage backend with appropriate path."""
    if bucket_type == "phi":
        return LocalStorageBackend(base_path=settings.STORAGE_LOCAL_PHI_PATH)
    else:  # clean
        return LocalStorageBackend(base_path=settings.STORAGE_LOCAL_CLEAN_PATH)


def _create_s3_backend(bucket_type: BucketType, settings: StorageSettings) -> S3StorageBackend:
    """Create S3 storage backend with appropriate bucket."""
    bucket_name = (
        settings.STORAGE_PHI_BUCKET if bucket_type == "phi" 
        else settings.STORAGE_CLEAN_BUCKET
    )
    
    return S3StorageBackend(
        endpoint_url=settings.STORAGE_S3_ENDPOINT_URL,  # None for real AWS, set for MinIO
        bucket=bucket_name,
        access_key=settings.STORAGE_S3_ACCESS_KEY,
        secret_key=settings.STORAGE_S3_SECRET_KEY,
        region=settings.STORAGE_S3_REGION
    )