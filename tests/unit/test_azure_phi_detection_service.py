"""
Unit tests for AzurePHIDetectionService.

These tests mock the Azure SDK to verify our adapter logic.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from azure.core.exceptions import AzureError

from src.services import AzurePHIDetectionService, PHIDetectionError
from src.models import MaskingLevel


class MockAzurePIIEntity:
    """Mock Azure PII entity."""
    def __init__(self, text, category, offset, length, confidence_score, subcategory=None):
        self.text = text
        self.category = category
        self.offset = offset
        self.length = length
        self.confidence_score = confidence_score
        self.subcategory = subcategory


class MockAzureDocumentResult:
    """Mock Azure document result."""
    def __init__(self, entities, is_error=False, error=None):
        self.entities = entities
        self.is_error = is_error
        self.error = error


@pytest.mark.asyncio
class TestAzurePHIDetectionService:
    """Unit tests for Azure PHI detection service."""
    
    async def test_successful_phi_detection(self):
        """Test successful PHI detection with mocked Azure response."""
        # Create mock entities
        mock_entities = [
            MockAzurePIIEntity(
                text="John Smith",
                category="Person",
                offset=0,
                length=10,
                confidence_score=0.95,
                subcategory="PersonName"
            ),
            MockAzurePIIEntity(
                text="03/15/2023",
                category="DateTime",
                offset=20,
                length=10,
                confidence_score=0.98,
                subcategory="Date"
            ),
        ]
        
        # Create mock document result
        mock_doc = MockAzureDocumentResult(entities=mock_entities)
        
        # Create mock client
        mock_client = AsyncMock()
        mock_client.recognize_pii_entities = AsyncMock(return_value=[mock_doc])
        
        # Test with injected mock client
        service = AzurePHIDetectionService(client=mock_client)
        entities = await service.detect_phi("John Smith was born on 03/15/2023")
        
        # Verify results
        assert len(entities) == 2
        
        assert entities[0].text == "John Smith"
        assert entities[0].category == "Person"
        assert entities[0].offset == 0
        assert entities[0].length == 10
        assert entities[0].confidence == 0.95
        
        assert entities[1].text == "03/15/2023"
        assert entities[1].category == "DateTime"
        assert entities[1].offset == 20
        assert entities[1].length == 10
    
    async def test_safe_harbor_masking_level(self):
        """Test that SAFE_HARBOR masks all entities."""
        mock_entities = [
            MockAzurePIIEntity("John", "Person", 0, 4, 0.95),
            MockAzurePIIEntity("Hospital", "Organization", 10, 8, 0.90),
        ]
        
        mock_doc = MockAzureDocumentResult(entities=mock_entities)
        mock_client = AsyncMock()
        mock_client.recognize_pii_entities = AsyncMock(return_value=[mock_doc])
        
        service = AzurePHIDetectionService(client=mock_client)
        entities = await service.detect_phi(
            "test text",
            masking_level=MaskingLevel.SAFE_HARBOR
        )
        
        # Both entities should be included
        assert len(entities) == 2
    
    async def test_limited_dataset_masking_level(self):
        """Test that LIMITED_DATASET excludes provider names."""
        mock_entities = [
            MockAzurePIIEntity("John Smith", "Person", 0, 10, 0.95),
            MockAzurePIIEntity("Dr. Jones", "PersonType", 20, 9, 0.92),
            MockAzurePIIEntity("City Hospital", "Organization", 40, 13, 0.88),
        ]
        
        mock_doc = MockAzureDocumentResult(entities=mock_entities)
        mock_client = AsyncMock()
        mock_client.recognize_pii_entities = AsyncMock(return_value=[mock_doc])
        
        service = AzurePHIDetectionService(client=mock_client)
        entities = await service.detect_phi(
            "test text",
            masking_level=MaskingLevel.LIMITED_DATASET
        )
        
        # Only patient name should be included (provider and org excluded)
        assert len(entities) == 1
        assert entities[0].text == "John Smith"
        assert entities[0].category == "Person"
    
    async def test_custom_masking_level(self):
        """Test CUSTOM mode with specified categories."""
        mock_entities = [
            MockAzurePIIEntity("John", "Person", 0, 4, 0.95),
            MockAzurePIIEntity("03/15/2023", "DateTime", 10, 10, 0.98),
            MockAzurePIIEntity("123-45-6789", "SSN", 25, 11, 0.99),
        ]
        
        mock_doc = MockAzureDocumentResult(entities=mock_entities)
        mock_client = AsyncMock()
        mock_client.recognize_pii_entities = AsyncMock(return_value=[mock_doc])
        
        # Only mask Person and SSN, not DateTime
        service = AzurePHIDetectionService(
            client=mock_client,
            custom_phi_categories={"Person", "SSN"}
        )
        entities = await service.detect_phi(
            "test text",
            masking_level=MaskingLevel.CUSTOM
        )
        
        # Should only include Person and SSN
        assert len(entities) == 2
        categories = {e.category for e in entities}
        assert categories == {"Person", "SSN"}
    
    async def test_entities_sorted_by_offset(self):
        """Test that entities are returned sorted by offset."""
        mock_entities = [
            MockAzurePIIEntity("last", "Person", 30, 4, 0.95),
            MockAzurePIIEntity("first", "Person", 0, 5, 0.95),
            MockAzurePIIEntity("middle", "Person", 10, 6, 0.95),
        ]
        
        mock_doc = MockAzureDocumentResult(entities=mock_entities)
        mock_client = AsyncMock()
        mock_client.recognize_pii_entities = AsyncMock(return_value=[mock_doc])
        
        service = AzurePHIDetectionService(client=mock_client)
        entities = await service.detect_phi("test text")
        
        # Should be sorted by offset
        assert entities[0].text == "first"
        assert entities[1].text == "middle"
        assert entities[2].text == "last"
    
    async def test_azure_error_handling(self):
        """Test error handling when Azure API fails."""
        mock_client = AsyncMock()
        mock_client.recognize_pii_entities = AsyncMock(
            side_effect=AzureError("API error")
        )
        
        service = AzurePHIDetectionService(client=mock_client)
        
        with pytest.raises(PHIDetectionError, match="Azure PHI detection failed"):
            await service.detect_phi("test text")
    
    async def test_azure_document_error(self):
        """Test handling of document-level errors from Azure."""
        mock_error = MagicMock()
        mock_error.message = "Document processing failed"
        
        mock_doc = MockAzureDocumentResult(
            entities=[],
            is_error=True,
            error=mock_error
        )
        
        mock_client = AsyncMock()
        mock_client.recognize_pii_entities = AsyncMock(return_value=[mock_doc])
        
        service = AzurePHIDetectionService(client=mock_client)
        
        with pytest.raises(PHIDetectionError, match="Document processing failed"):
            await service.detect_phi("test text")
    
    async def test_empty_text_handling(self):
        """Test handling of empty text input."""
        mock_doc = MockAzureDocumentResult(entities=[])
        
        mock_client = AsyncMock()
        mock_client.recognize_pii_entities = AsyncMock(return_value=[mock_doc])
        
        service = AzurePHIDetectionService(client=mock_client)
        entities = await service.detect_phi("")
        
        assert len(entities) == 0
    
    async def test_context_manager(self):
        """Test async context manager protocol."""
        mock_client = AsyncMock()
        mock_client.close = AsyncMock()
        
        async with AzurePHIDetectionService(client=mock_client) as service:
            assert service is not None
        
        # Verify close was called
        mock_client.close.assert_called_once()