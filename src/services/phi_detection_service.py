"""
Abstract base class for PHI/PII detection service providers.

This interface allows swapping between different detection providers
(Azure Language, AWS Comprehend Medical, local NER models, Mock).
"""

from abc import ABC, abstractmethod
from typing import List
from src.models.domain import PHIEntity, MaskingLevel


class PHIDetectionError(Exception):
    """Base exception for PHI detection service errors."""
    pass


class PHIDetectionService(ABC):
    """Abstract base class for PHI/PII detection providers."""
    
    @abstractmethod
    async def detect_phi(
        self,
        text: str,
        masking_level: MaskingLevel = MaskingLevel.SAFE_HARBOR,
    ) -> List[PHIEntity]:
        """
        Detect PHI entities in text using ML.
        
        Args:
            text: Full text to analyze for PHI
            masking_level: HIPAA compliance level determining which
                          entities to detect
            
        Returns:
            List of PHIEntity with character offsets, sorted by offset
            
        Raises:
            PHIDetectionError: If detection fails
        """
        pass
    
    def _should_include_entity(
        self,
        category: str,
        masking_level: MaskingLevel,
    ) -> bool:
        """
        Determine if an entity category should be included based on masking level.
        
        Args:
            category: PHI category (Person, Date, SSN, etc.)
            masking_level: HIPAA compliance level
            
        Returns:
            True if entity should be masked, False otherwise
        """
        if masking_level == MaskingLevel.SAFE_HARBOR:
            # Mask everything
            return True
        
        elif masking_level == MaskingLevel.LIMITED_DATASET:
            # Don't mask provider/organization names
            provider_categories = {
                "HealthcareProfessional",
                "Doctor",
                "Physician",
                "Organization",
                "Hospital",
            }
            return category not in provider_categories
        
        else:  # CUSTOM
            # Check against configured categories
            # (This would be loaded from config in real implementation)
            return True  # Placeholder - override in subclass