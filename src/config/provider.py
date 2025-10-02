from pydantic_settings import BaseSettings
from typing import Literal


class ProviderSettings(BaseSettings):
    """Configuration for OCR and PHI service providers."""
    
    # Default provider for production
    OCR_PROVIDER: Literal["azure", "aws", "mock"] = "azure"
    PHI_PROVIDER: Literal["azure", "aws", "mock"] = "azure"
    
    # Default masking level
    DEFAULT_MASKING_LEVEL: Literal["safe_harbor", "limited_dataset", "custom"] = "safe_harbor"
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore"
    }