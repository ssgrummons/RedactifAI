"""
Azure Language Service PHI detection implementation.

Uses Azure's PII detection with healthcare domain for HIPAA-compliant entity detection.
API Documentation: https://learn.microsoft.com/en-us/azure/ai-services/language-service/
"""

import logging
from typing import Optional, List, Set
from azure.ai.textanalytics.aio import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError

from src.models import PHIEntity, MaskingLevel
from .phi_detection_service import PHIDetectionService, PHIDetectionError
from src.config import AzureSettings, azure_settings

logger = logging.getLogger(__name__)


class AzurePHIDetectionService(PHIDetectionService):
    """
    Azure Language Service PHI detection implementation.
    
    Uses Azure's recognize_pii_entities with domain='phi' for
    healthcare-specific PII detection.
    
    Detects HIPAA-relevant entities:
    - Person names
    - Dates (except year-only)
    - Phone numbers, emails
    - SSN, medical record numbers
    - Addresses
    - Organization names
    - And more...
    """
    
    # Categories to exclude in LIMITED_DATASET mode
    PROVIDER_CATEGORIES = {
        "PersonType",  # Doctor, Physician, etc.
        "Organization",  # Hospitals, clinics
    }
    
    def __init__(
        self,
        settings: Optional[AzureSettings] = None,
        client: Optional[TextAnalyticsClient] = None,
        custom_phi_categories: Optional[Set[str]] = None,
    ):
        """
        Initialize Azure PHI detection service.
        
        Args:
            settings: Azure configuration (uses global settings if None)
            client: Pre-configured TextAnalyticsClient for testing
            custom_phi_categories: Set of categories to mask in CUSTOM mode
        """
        self.settings = settings or azure_settings
        self.custom_phi_categories = custom_phi_categories or set()
        
        if client:
            # Use injected client (for testing)
            self.client = client
        else:
            # Validate configuration
            self.settings.validate_phi_config()
            
            # Create real client
            self.client = TextAnalyticsClient(
                endpoint=self.settings.azure_language_endpoint,
                credential=AzureKeyCredential(
                    self.settings.azure_language_key
                ),
            )
    
    async def detect_phi(
        self,
        text: str,
        masking_level: MaskingLevel = MaskingLevel.SAFE_HARBOR,
    ) -> List[PHIEntity]:
        """
        Detect PHI entities using Azure Language Service.
        
        Args:
            text: Full text to analyze
            masking_level: HIPAA compliance level
            
        Returns:
            List of PHIEntity sorted by offset
            
        Raises:
            PHIDetectionError: If Azure API call fails
        """
        try:
            logger.info(f"Starting PHI detection for {len(text)} characters")
            
            # Call Azure Language Service
            # domain='phi' enables healthcare-specific PII detection
            response = await self.client.recognize_pii_entities(
                documents=[text],
                domain="phi",
                language="en",
            )
            
            # Extract entities from response
            entities = []
            for doc in response:
                if doc.is_error:
                    raise PHIDetectionError(
                        f"Azure PHI detection error: {doc.error.message}"
                    )
                
                for azure_entity in doc.entities:
                    # Filter based on masking level
                    if self._should_include_entity(azure_entity.category, masking_level):
                        entities.append(PHIEntity(
                            text=azure_entity.text,
                            category=azure_entity.category,
                            offset=azure_entity.offset,
                            length=azure_entity.length,
                            confidence=azure_entity.confidence_score,
                            subcategory=azure_entity.subcategory,
                        ))
            
            # Sort by offset
            entities.sort(key=lambda e: e.offset)
            
            logger.info(f"PHI detection completed: {len(entities)} entities found")
            
            return entities
            
        except AzureError as e:
            logger.error(f"Azure Language Service API error: {e}")
            raise PHIDetectionError(f"Azure PHI detection failed: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during PHI detection: {e}")
            raise PHIDetectionError(f"PHI detection failed: {e}") from e
    
    def _should_include_entity(
        self,
        category: str,
        masking_level: MaskingLevel,
    ) -> bool:
        """
        Determine if entity should be masked based on HIPAA compliance level.
        
        Args:
            category: Azure PII category
            masking_level: Compliance level
            
        Returns:
            True if entity should be masked
        """
        if masking_level == MaskingLevel.SAFE_HARBOR:
            # Mask everything for maximum de-identification
            return True
        
        elif masking_level == MaskingLevel.LIMITED_DATASET:
            # Exclude provider/organization names
            # Keep for research use under data use agreement
            return category not in self.PROVIDER_CATEGORIES
        
        else:  # CUSTOM
            # Only mask configured categories
            if not self.custom_phi_categories:
                # If no custom categories configured, default to SAFE_HARBOR
                logger.warning(
                    "CUSTOM masking level selected but no categories configured. "
                    "Defaulting to SAFE_HARBOR mode."
                )
                return True
            
            return category in self.custom_phi_categories
    
    async def close(self):
        """Close the Azure client connection."""
        await self.client.close()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()