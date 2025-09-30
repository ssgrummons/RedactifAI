from pydantic_settings import BaseSettings
from typing import Optional


class StorageSettings(BaseSettings):
    """Storage configuration for PHI and clean document buckets."""
    
    # Backend selection
    STORAGE_BACKEND: str = "local"  # local | s3
    
    # PHI bucket (uploaded documents - short retention, strict access)
    STORAGE_PHI_BUCKET: str = "redactifai-phi-uploads"
    STORAGE_PHI_PREFIX: str = "uploads/"
    
    # Clean bucket (masked documents - long retention, normal access)
    STORAGE_CLEAN_BUCKET: str = "redactifai-clean-outputs"
    STORAGE_CLEAN_PREFIX: str = "masked/"
    
    # Local backend paths
    STORAGE_LOCAL_PHI_PATH: str = "/tmp/redactifai/phi"
    STORAGE_LOCAL_CLEAN_PATH: str = "/tmp/redactifai/clean"
    
    # S3/MinIO configuration
    STORAGE_S3_ENDPOINT_URL: Optional[str] = None  # Set for MinIO/local S3
    STORAGE_S3_ACCESS_KEY: str = "minioadmin"
    STORAGE_S3_SECRET_KEY: str = "minioadmin"
    STORAGE_S3_REGION: str = "us-east-1"
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore"
    }