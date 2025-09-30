"""
Azure service configuration using Pydantic BaseSettings.

Environment variables:
- AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
- AZURE_DOCUMENT_INTELLIGENCE_KEY
- AZURE_LANGUAGE_ENDPOINT
- AZURE_LANGUAGE_KEY
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class AzureSettings(BaseSettings):
    """
    Azure service credentials and endpoints.
    
    Setup Instructions:
    
    1. Create Azure Document Intelligence resource:
       az cognitiveservices account create \
         --name redactifai-ocr \
         --resource-group redactifai-rg \
         --kind FormRecognizer \
         --sku S0 \
         --location eastus
    
    2. Create Azure Language resource:
       az cognitiveservices account create \
         --name redactifai-phi \
         --resource-group redactifai-rg \
         --kind TextAnalytics \
         --sku S \
         --location eastus
    
    3. Get credentials:
       az cognitiveservices account keys list \
         --name redactifai-ocr \
         --resource-group redactifai-rg
    
    4. Set environment variables in .env file:
       AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://redactifai-ocr.cognitiveservices.azure.com/
       AZURE_DOCUMENT_INTELLIGENCE_KEY=your_key_here
       AZURE_LANGUAGE_ENDPOINT=https://redactifai-phi.cognitiveservices.azure.com/
       AZURE_LANGUAGE_KEY=your_key_here
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # Document Intelligence (OCR)
    azure_document_intelligence_endpoint: Optional[str] = None
    azure_document_intelligence_key: Optional[str] = None
    
    # Language Service (PHI Detection)
    azure_language_endpoint: Optional[str] = None
    azure_language_key: Optional[str] = None
    
    def validate_ocr_config(self) -> None:
        """Validate that OCR credentials are set."""
        if not self.azure_document_intelligence_endpoint:
            raise ValueError(
                "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT not set. "
                "See AzureSettings docstring for setup instructions."
            )
        if not self.azure_document_intelligence_key:
            raise ValueError(
                "AZURE_DOCUMENT_INTELLIGENCE_KEY not set. "
                "See AzureSettings docstring for setup instructions."
            )
    
    def validate_phi_config(self) -> None:
        """Validate that PHI detection credentials are set."""
        if not self.azure_language_endpoint:
            raise ValueError(
                "AZURE_LANGUAGE_ENDPOINT not set. "
                "See AzureSettings docstring for setup instructions."
            )
        if not self.azure_language_key:
            raise ValueError(
                "AZURE_LANGUAGE_KEY not set. "
                "See AzureSettings docstring for setup instructions."
            )


# Global settings instance
azure_settings = AzureSettings()