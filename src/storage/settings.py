from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal
from datetime import timezone, datetime


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    
    # API Settings
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_WORKERS: int = 1
    
    # Storage
    STORAGE_BACKEND: Literal["s3", "azure", "local"] = "s3"
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_BUCKET: str = "redactify"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_REGION: str = "us-east-1"
    AZURE_STORAGE_CONNECTION_STRING: str = ""
    AZURE_STORAGE_CONTAINER: str = "redactify"
    LOCAL_STORAGE_PATH: str = "/tmp/redactify"
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://redactify:redactify@localhost:5432/redactify"
    
    # Azure Document Intelligence
    AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT: str = ""
    AZURE_DOCUMENT_INTELLIGENCE_KEY: str = ""
    
    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    
    # Processing
    MAX_FILE_SIZE_MB: int = 50
    MASKING_PADDING_PX: int = 5
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_BASE: float = 2.0  # Exponential backoff base
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # json | text


settings = Settings()