from abc import ABC, abstractmethod
from typing import Optional


class StorageBackend(ABC):
    """Abstract base class for storage backends."""
    
    @abstractmethod
    async def upload(self, key: str, data: bytes, content_type: str = "image/tiff") -> str:
        """
        Upload data to storage.
        
        Args:
            key: Storage key/path
            data: Bytes to upload
            content_type: MIME type
            
        Returns:
            Storage key (may be different from input if backend modifies it)
        """
        pass
    
    @abstractmethod
    async def download(self, key: str) -> bytes:
        """
        Download data from storage.
        
        Args:
            key: Storage key/path
            
        Returns:
            File bytes
            
        Raises:
            FileNotFoundError: If key doesn't exist
        """
        pass
    
    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if key exists in storage."""
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete key from storage."""
        pass