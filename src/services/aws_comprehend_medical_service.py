"""
AWS Comprehend Medical PHI detection service implementation.

Uses AWS Comprehend Medical's DetectPHI API for healthcare-specific
entity detection.
API Documentation: https://docs.aws.amazon.com/comprehend-medical/
"""

import logging
from typing import Optional, List, Set
import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from src.models.domain import PHIEntity, MaskingLevel
from src.services.phi_detection_service import PHIDetectionService, PHIDetectionError
from src.config.aws_settings import AWSSettings, aws_settings

logger = logging.getLogger(__name__)


class AWSComprehendMedicalService(PHIDetectionService):
    """
    AWS Comprehend Medical PHI detection implementation.
    
    Uses DetectPHI API which detects:
    - Names (patient, doctor)
    - Ages
    - Dates
    - Phone numbers, emails
    - Addresses
    - IDs (medical record numbers, SSN)
    - And more healthcare-specific entities
    """
    
    # Categories to exclude in LIMITED_DATASET mode
    PROVIDER_CATEGORIES = {
        "NAME",  # Includes both patient and provider - need to check attribute
    }
    
    # AWS Comprehend Medical text limit (20,000 UTF-8 characters)
    MAX_TEXT_LENGTH = 20000
    
    def __init__(
        self,
        settings: Optional[AWSSettings] = None,
        session: Optional[aioboto3.Session] = None,
        custom_phi_categories: Optional[Set[str]] = None,
    ):
        """
        Initialize AWS Comprehend Medical service.
        
        Args:
            settings: AWS configuration (uses global settings if None)
            session: Pre-configured aioboto3 session for testing
            custom_phi_categories: Set of categories to mask in CUSTOM mode
        """
        self.settings = settings or aws_settings
        self.custom_phi_categories = custom_phi_categories or set()
        
        if session:
            self.session = session
        else:
            # Validate configuration
            self.settings.validate_phi_config()
            
            # Create session
            if self.settings.aws_access_key_id:
                self.session = aioboto3.Session(
                    aws_access_key_id=self.settings.aws_access_key_id,
                    aws_secret_access_key=self.settings.aws_secret_access_key,
                    region_name=self.settings.get_comprehend_region(),
                )
            else:
                # Using IAM role
                self.session = aioboto3.Session(
                    region_name=self.settings.get_comprehend_region(),
                )
    
    async def detect_phi(
        self,
        text: str,
        masking_level: MaskingLevel = MaskingLevel.SAFE_HARBOR,
    ) -> List[PHIEntity]:
        """
        Detect PHI entities using AWS Comprehend Medical.
        
        Args:
            text: Full text to analyze
            masking_level: HIPAA compliance level
            
        Returns:
            List of PHIEntity sorted by offset
            
        Raises:
            PHIDetectionError: If AWS API call fails
        """
        try:
            logger.info(f"Starting Comprehend Medical PHI detection for {len(text)} characters")
            
            # Handle text longer than API limit by chunking
            if len(text) > self.MAX_TEXT_LENGTH:
                return await self._detect_phi_chunked(text, masking_level)
            
            async with self.session.client('comprehendmedical') as comprehend:
                # Call DetectPHI
                response = await comprehend.detect_phi(Text=text)
            
            # Extract entities from response
            entities = self._extract_entities(response, masking_level, offset=0)
            
            # Sort by offset
            entities.sort(key=lambda e: e.offset)
            
            logger.info(f"Comprehend Medical completed: {len(entities)} entities found")
            
            return entities
            
        except (BotoCoreError, ClientError) as e:
            logger.error(f"AWS Comprehend Medical API error: {e}")
            raise PHIDetectionError(f"AWS Comprehend Medical failed: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during PHI detection: {e}")
            raise PHIDetectionError(f"PHI detection failed: {e}") from e
    
    async def _detect_phi_chunked(
        self,
        text: str,
        masking_level: MaskingLevel,
    ) -> List[PHIEntity]:
        """
        Detect PHI in text longer than API limit by chunking.
        
        Args:
            text: Full text (> 20,000 characters)
            masking_level: Compliance level
            
        Returns:
            List of PHIEntity with adjusted offsets
        """
        all_entities = []
        offset = 0
        
        while offset < len(text):
            # Extract chunk
            chunk_end = min(offset + self.MAX_TEXT_LENGTH, len(text))
            chunk = text[offset:chunk_end]
            
            logger.info(f"Processing chunk at offset {offset} ({len(chunk)} chars)")
            
            async with self.session.client('comprehendmedical') as comprehend:
                response = await comprehend.detect_phi(Text=chunk)
            
            # Extract entities with offset adjustment
            chunk_entities = self._extract_entities(response, masking_level, offset=offset)
            all_entities.extend(chunk_entities)
            
            offset = chunk_end
        
        # Sort by offset
        all_entities.sort(key=lambda e: e.offset)
        
        return all_entities
    
    def _extract_entities(
        self,
        response: dict,
        masking_level: MaskingLevel,
        offset: int = 0,
    ) -> List[PHIEntity]:
        """
        Extract PHI entities from Comprehend Medical response.
        
        Args:
            response: API response
            masking_level: Compliance level for filtering
            offset: Offset to add to all entity positions (for chunking)
            
        Returns:
            List of PHIEntity
        """
        entities = []
        
        for aws_entity in response.get('Entities', []):
            category = aws_entity.get('Category')
            
            # Check if we should mask this category
            if not self._should_include_entity_with_attributes(
                aws_entity, masking_level
            ):
                continue
            
            # Extract entity details
            text = aws_entity.get('Text', '')
            begin_offset = aws_entity.get('BeginOffset', 0) + offset
            end_offset = aws_entity.get('EndOffset', 0) + offset
            score = aws_entity.get('Score', 0.0)
            
            # Get entity type (more specific than category)
            entity_type = aws_entity.get('Type')
            
            entities.append(PHIEntity(
                text=text,
                category=category,
                offset=begin_offset,
                length=end_offset - begin_offset,
                confidence=score,
                subcategory=entity_type,
            ))
        
        return entities
    
    def _should_include_entity_with_attributes(
        self,
        aws_entity: dict,
        masking_level: MaskingLevel,
    ) -> bool:
        """
        Determine if entity should be masked based on level and attributes.
        
        For LIMITED_DATASET, we need to check entity attributes to distinguish
        patient names from provider names.
        
        Args:
            aws_entity: AWS entity dict with attributes
            masking_level: Compliance level
            
        Returns:
            True if entity should be masked
        """
        category = aws_entity.get('Category')
        
        if masking_level == MaskingLevel.SAFE_HARBOR:
            # Mask everything
            return True
        
        elif masking_level == MaskingLevel.LIMITED_DATASET:
            # For NAME category, check if it's a provider
            if category == "NAME":
                # Check Traits for provider indicators
                traits = aws_entity.get('Traits', [])
                for trait in traits:
                    trait_name = trait.get('Name', '')
                    if trait_name in ('DIAGNOSIS', 'SIGN', 'SYMPTOM'):
                        # Context suggests this is medical terminology, not a name
                        return False
                
                # Check Attributes for provider role
                attributes = aws_entity.get('Attributes', [])
                for attr in attributes:
                    attr_type = attr.get('Type', '')
                    if attr_type == 'DIRECTION':
                        # Likely a provider if there are directional attributes
                        return False
                
                # Default: mask patient names
                return True
            
            # Mask all other PHI categories
            return True
        
        else:  # CUSTOM
            if not self.custom_phi_categories:
                logger.warning(
                    "CUSTOM masking level but no categories configured. "
                    "Defaulting to SAFE_HARBOR."
                )
                return True
            
            return category in self.custom_phi_categories
    
    async def close(self):
        """Close AWS session (no-op for aioboto3)."""
        pass
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()