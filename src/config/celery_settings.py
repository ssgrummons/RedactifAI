from pydantic import SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

class CelerySettings(BaseSettings):
    """Celery and Redis configuration."""
    
    # Redis connection parameters
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: SecretStr | None = None
    REDIS_USE_SSL: bool = False
    
    # Database selection (support both patterns)
    REDIS_BROKER_DB: int = 0
    REDIS_RESULT_DB: int = 0  # Same as broker by default
    
    # Service identity for key prefixing
    SERVICE_NAME: str = "orchestrator"
    
    # Task configuration
    CELERY_TASK_TIME_LIMIT: int = 3600
    CELERY_TASK_SOFT_TIME_LIMIT: int = 3300
    CELERY_TASK_MAX_RETRIES: int = 3
    CELERY_TASK_DEFAULT_RETRY_DELAY: int = 60
    
    # Result backend configuration
    CELERY_RESULT_EXPIRES: int = 86400  # 24 hours
    
    # For testing
    CELERY_TASK_ALWAYS_EAGER: bool = False
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )
    
    @computed_field
    @property
    def broker_url(self) -> str:
        """Construct Redis URL for Celery broker."""
        return self._build_redis_url(self.REDIS_BROKER_DB, "broker")
    
    # Backward compatibility aliases
    @property
    def CELERY_BROKER_URL(self) -> str:
        """Backward compatibility alias for broker_url."""
        return self.broker_url
    
    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        """Backward compatibility alias for result_backend."""
        return self.result_backend
    
    @computed_field
    @property
    def result_backend(self) -> str:
        """Construct Redis URL for Celery result backend."""
        return self._build_redis_url(self.REDIS_RESULT_DB, "result")
    
    def _build_redis_url(self, db: int, purpose: str) -> str:
        """Build Redis connection URL with all parameters.
        
        Args:
            db: Redis database number
            purpose: 'broker' or 'result' for key prefixing
        """
        protocol = "rediss" if self.REDIS_USE_SSL else "redis"
        
        password_part = ""
        if self.REDIS_PASSWORD:
            password_part = f":{self.REDIS_PASSWORD.get_secret_value()}@"
        
        base_url = f"{protocol}://{password_part}{self.REDIS_HOST}:{self.REDIS_PORT}/{db}"
        
        # Key prefix includes both service name and purpose
        params = []
        if self.REDIS_USE_SSL:
            params.append("ssl_cert_reqs=required")
        params.append(f"global_keyprefix={self.SERVICE_NAME}:{purpose}:")
        
        query_string = "&".join(params)
        return f"{base_url}?{query_string}"