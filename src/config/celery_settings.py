from pydantic import SecretStr, computed_field, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from enum import Enum
from urllib.parse import quote_plus

class ResultBackendType(str, Enum):
    REDIS = "redis"
    POSTGRES = "postgres"

class CelerySettings(BaseSettings):
    """Celery and Redis configuration."""
    
    RESULT_BACKEND_TYPE: ResultBackendType = Field(
        default=ResultBackendType.REDIS,
        alias="CELERY_RESULT_BACKEND_TYPE"
    )

    # Redis connection parameters
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_USER: str | None = None
    REDIS_PASSWORD: SecretStr | None = None
    REDIS_USE_SSL: bool = False
    
    # Database selection (support both patterns)
    REDIS_BROKER_DB: int = 0
    REDIS_RESULT_DB: int = 0  # Same as broker by default

    # POSTGRES parameters
    DB_USER: str = "db-user"
    DB_PASSWORD: str = "db-password"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "postgres"
    DB_SCHEMA: str = "public"
    
    # Task configuration
    CELERY_TASK_MAX_RETRIES: int = 3
    CELERY_TASK_TIME_LIMIT: int = 3600
    CELERY_TASK_SOFT_TIME_LIMIT: int = 3300
    CELERY_TASK_DEFAULT_RETRY_DELAY: int = 60
    CELERY_TASK_ACKS_LATE: bool  = True
    CELERY_TASK_REJECT_ON_WORKER_LOST: bool = True
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # TIMEZONE
    timezone: str = "UTC"
    CELERY_enable_utc: bool = True

    # FORMAT SETTINGS
    task_serializer: str = "json"
    result_serializer: str = "json"
    accept_content: list = ["json"]

    # Cluster mode protection
    result_backend_transport_options: dict = {'global_keyprefix': '{celery}'}

    # Result configuration
    CELERY_RESULT_EXPIRES: int = 86400  # 24 hours
    
    # Connection pooling and retry settings
    CELERY_BROKER_POOL_LIMIT: int = 10
    CELERY_RESULT_BACKEND_POOL_LIMIT: int = 10
    CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP: bool = True
    CELERY_RESULT_BACKEND_ALWAYS_RETRY: bool = True
    CELERY_BROKER_CONNECTION_RETRY: bool = True
    CELERY_RESULT_BACKEND_RETRY_ON_STARTUP: bool = True
    
    # Database connection settings for PostgreSQL
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_PRE_PING: bool = True
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
        populate_by_name=True
    )
    
    @computed_field
    @property
    def broker_url(self) -> str:
        """Construct Redis URL for Celery broker."""
        return self._build_redis_url(self.REDIS_BROKER_DB, "broker")
    
    # Backward compatibility aliases
    @property
    def CELERY_broker_url(self) -> str:
        """Backward compatibility alias for broker_url."""
        return self.broker_url
    
    @property
    def result_backend(self) -> str:
        """Backward compatibility alias for result_backend."""
        return self.result_backend
    
    @computed_field
    @property
    def result_backend(self) -> str:
        """Construct URL for Celery result backend."""
        if self.RESULT_BACKEND_TYPE == ResultBackendType.REDIS:
            return self._build_redis_url(self.REDIS_RESULT_DB, "result")
        else:
            return f"db+{self._build_postgres_url()}"
    
    def _build_redis_url(self, db: int, purpose: str) -> str:
        """Build Redis connection URL with all parameters.
        
        Args:
            db: Redis database number
            purpose: 'broker' or 'result' for key prefixing
        """
        protocol = "rediss" if self.REDIS_USE_SSL else "redis"
        
        password_part = ""
        if self.REDIS_PASSWORD:
            password_part = f"{self.REDIS_USER}:{self.REDIS_PASSWORD.get_secret_value()}@"
        
        base_url = f"{protocol}://{password_part}{self.REDIS_HOST}:{self.REDIS_PORT}/{db}"
        
        # Key prefix includes both service name and purpose
        params = []
        if self.REDIS_USE_SSL:
            params.append("ssl_cert_reqs=required")

        if params:
            query_string = "&".join(params)
            return f"{base_url}?{query_string}"
        
        return base_url
    
    def _build_postgres_url(self) -> str:
        """Build PostgreSQL connection URL for result backend"""
        user = quote_plus(self.DB_USER)
        password = quote_plus(self.DB_PASSWORD)
        base_url = f"postgresql://{user}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        return base_url