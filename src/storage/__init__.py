from .base import StorageBackend
from .s3 import S3StorageBackend
from .local import LocalStorageBackend
from .settings import settings


def get_storage_backend() -> StorageBackend:
    """
    Factory function to get the configured storage backend.
    
    Returns:
        Configured storage backend instance
        
    Raises:
        ValueError: If STORAGE_BACKEND is not recognized
    """
    if settings.STORAGE_BACKEND == "s3":
        return S3StorageBackend()
    elif settings.STORAGE_BACKEND == "local":
        return LocalStorageBackend()
    # elif settings.STORAGE_BACKEND == "azure":
    #     # Import here to avoid requiring azure-storage-blob if not used
    #     from .storage import AzureBlobStorageBackend
    #     return AzureBlobStorageBackend()
    else:
        raise ValueError(f"Unknown storage backend: {settings.STORAGE_BACKEND}")


__all__ = [
    "StorageBackend",
    "S3StorageBackend", 
    "LocalStorageBackend",
    "get_storage_backend"
]