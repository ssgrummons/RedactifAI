from pathlib import Path
from .base import StorageBackend


class LocalStorageBackend(StorageBackend):
    """Local filesystem storage backend for development."""
    
    def __init__(self, base_path: str = None):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def _get_full_path(self, key: str) -> Path:
        """Convert storage key to full filesystem path."""
        full_path = self.base_path / key
        # Ensure path is within base_path (security check)
        full_path.resolve().relative_to(self.base_path.resolve())
        return full_path
    
    def upload(self, key: str, data: bytes, content_type: str = "image/tiff") -> str:
        """Upload data to local filesystem."""
        full_path = self._get_full_path(key)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(full_path, 'wb') as f:
            f.write(data)
        
        return key
    
    def download(self, key: str) -> bytes:
        """Download data from local filesystem."""
        full_path = self._get_full_path(key)
        
        if not full_path.exists():
            raise FileNotFoundError(f"Key not found: {key}")
        
        with open(full_path, 'rb') as f:
            return f.read()
    
    def exists(self, key: str) -> bool:
        """Check if key exists in local filesystem."""
        full_path = self._get_full_path(key)
        return full_path.exists()
    
    def delete(self, key: str) -> None:
        """Delete key from local filesystem."""
        full_path = self._get_full_path(key)
        if full_path.exists():
            full_path.unlink()