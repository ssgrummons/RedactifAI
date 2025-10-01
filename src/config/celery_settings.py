from pydantic_settings import BaseSettings


class CelerySettings(BaseSettings):
    """Celery and Redis configuration."""
    
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    
    # Task configuration
    CELERY_TASK_TIME_LIMIT: int = 3600  # 1 hour max per task
    CELERY_TASK_SOFT_TIME_LIMIT: int = 3300  # 55 minutes soft limit
    CELERY_TASK_MAX_RETRIES: int = 3
    CELERY_TASK_DEFAULT_RETRY_DELAY: int = 60  # seconds
    
    # For testing - set to True to run tasks synchronously
    CELERY_TASK_ALWAYS_EAGER: bool = False
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore"
    }