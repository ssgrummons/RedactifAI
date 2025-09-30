"""
Unit tests for AWS Textract and Comprehend Medical services.

These tests mock the AWS SDK (aioboto3) to verify adapter logic.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.aws_textract_service import AWSTextractService
from src.services.aws_comprehend_medical_service import AWSComprehendMedicalService
from src.services.ocr_service import OCRServiceError
from src.services.phi_detection_service import PHIDetectionError
from src.models.domain import MaskingLevel


@pytest.mark.asyncio
class TestAWSTextractService:
    """Unit tests for AWS Textract OCR service."""
    
    async def test_successful_ocr(self):
        """Test successful OCR with mocked Textract response."""
        # Create mock Textract response
        mock_response = {
            'DocumentMetadata': {'Pages': 1},
            'Blocks': [
                {
                    'BlockType': 'PAGE',
                    'Page': 1,
                },
                {
                    'BlockType': 'LINE',
                    'Page': 1,
                    'Text': 'Hello World',
                },
                {
                    'BlockType': 'WORD',
                    'Page': 1,
                    'Text': 'Hello',
                    'Confidence': 99.5,
                    'Geometry': {
                        'BoundingBox': {
                            'Left': 0.1,
                            'Top': 0.2,
                            'Width': 0.05,
                            'Height': 0.02,
                        }
                    }
                },
                {
                    'BlockType': 'WORD',
                    'Page': 1,
                    'Text': 'World',
                    'Confidence': 98.7,
                    'Geometry': {
                        'BoundingBox': {
                            'Left': 0.16,
                            'Top': 0.2,
                            'Width': 0.05,
                            'Height': 0.02,
                        }
                    }
                },
            ]
        }
        
        # Create mock client
        mock_client = AsyncMock()
        mock_client.detect_document_text = AsyncMock(return_value=mock_response)
        
        # Create mock session
        mock_session = MagicMock()
        mock_session.client = MagicMock()
        mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session.client.return_value.__aexit__ = AsyncMock(return_value=None)
        
        # Test service
        service = AWSTextractService(session=mock_session)
        result = await service.analyze_document(b"fake_bytes")
        
        # Verify result
        assert len(result.pages) == 1
        assert result.pages[0].page_number == 1
        assert len(result.pages[0].words) == 2
        
        word1 = result.pages[0].words[0]
        assert word1.text == "Hello"
        assert word1.confidence == pytest.approx(0.995, rel=0.01)
        assert word1.bounding_box.x == 0.1
        assert word1.bounding_box.y == 0.2
        
        assert "Hello World" in result.full_text
    
    async def test_multi_page_document(self):
        """Test Textract with multi-page document."""
        mock_response = {
            'DocumentMetadata': {'Pages': 2},
            'Blocks': [
                {
                    'BlockType': 'LINE',
                    'Page': 1,
                    'Text': 'Page 1',
                },
                {
                    'BlockType': 'WORD',
                    'Page': 1,
                    'Text': 'Page',
                    'Confidence': 99.0,
                    'Geometry': {'BoundingBox': {'Left': 0.1, 'Top': 0.1, 'Width': 0.05, 'Height': 0.02}}
                },
                {
                    'BlockType': 'LINE',
                    'Page': 2,
                    'Text': 'Page 2',
                },
                {
                    'BlockType': 'WORD',
                    'Page': 2,
                    'Text': 'Page',
                    'Confidence': 98.5,
                    'Geometry': {'BoundingBox': {'Left': 0.1, 'Top': 0.1, 'Width': 0.05, 'Height': 0.02}}
                },
            ]
        }
        
        mock_client = AsyncMock()
        mock_client.detect_document_text = AsyncMock(return_value=mock_response)
        
        mock_session = MagicMock()
        mock_session.client = MagicMock()
        mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session.client.return_value.__aexit__ = AsyncMock(return_value=None)
        
        service = AWSTextractService(session=mock_session)
        result = await service.analyze_document(b"fake_bytes")
        
        assert len(result.pages) == 2
        assert result.pages[0].page_number == 1
        assert result.pages[1].page_number == 2


@pytest.mark.asyncio
class TestAWSComprehendMedicalService:
    """Unit tests for AWS Comprehend Medical service."""
    
    async def test_successful_phi_detection(self):
        """Test successful PHI detection with mocked response."""
        mock_response = {
            'Entities': [
                {
                    'Category': 'NAME',
                    'Type': 'PATIENT',
                    'Text': 'John Smith',
                    'BeginOffset': 0,
                    'EndOffset': 10,
                    'Score': 0.95,
                    'Traits': [],
                    'Attributes': [],
                },
                {
                    'Category': 'DATE',
                    'Type': 'DATE',
                    'Text': '03/15/2023',
                    'BeginOffset': 20,
                    'EndOffset': 30,
                    'Score': 0.98,
                    'Traits': [],
                    'Attributes': [],
                },
            ]
        }
        
        mock_client = AsyncMock()
        mock_client.detect_phi = AsyncMock(return_value=mock_response)
        
        mock_session = MagicMock()
        mock_session.client = MagicMock()
        mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session.client.return_value.__aexit__ = AsyncMock(return_value=None)
        
        service = AWSComprehendMedicalService(session=mock_session)
        entities = await service.detect_phi("John Smith was born on 03/15/2023")
        
        assert len(entities) == 2
        assert entities[0].text == "John Smith"
        assert entities[0].category == "NAME"
        assert entities[0].confidence == 0.95
        
        assert entities[1].text == "03/15/2023"
        assert entities[1].category == "DATE"
    
    async def test_safe_harbor_mode(self):
        """Test SAFE_HARBOR masks all entities."""
        mock_response = {
            'Entities': [
                {
                    'Category': 'NAME',
                    'Type': 'PATIENT',
                    'Text': 'Patient',
                    'BeginOffset': 0,
                    'EndOffset': 7,
                    'Score': 0.95,
                    'Traits': [],
                    'Attributes': [],
                },
            ]
        }
        
        mock_client = AsyncMock()
        mock_client.detect_phi = AsyncMock(return_value=mock_response)
        
        mock_session = MagicMock()
        mock_session.client = MagicMock()
        mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session.client.return_value.__aexit__ = AsyncMock(return_value=None)
        
        service = AWSComprehendMedicalService(session=mock_session)
        entities = await service.detect_phi(
            "test text",
            masking_level=MaskingLevel.SAFE_HARBOR
        )
        
        assert len(entities) == 1
    
    async def test_chunking_for_long_text(self):
        """Test that text > 20k chars is chunked."""
        # Create long text
        long_text = "x" * 25000
        
        mock_response = {
            'Entities': [
                {
                    'Category': 'NAME',
                    'Type': 'PATIENT',
                    'Text': 'Test',
                    'BeginOffset': 0,
                    'EndOffset': 4,
                    'Score': 0.95,
                    'Traits': [],
                    'Attributes': [],
                },
            ]
        }
        
        mock_client = AsyncMock()
        mock_client.detect_phi = AsyncMock(return_value=mock_response)
        
        mock_session = MagicMock()
        mock_session.client = MagicMock()
        mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session.client.return_value.__aexit__ = AsyncMock(return_value=None)
        
        service = AWSComprehendMedicalService(session=mock_session)
        entities = await service.detect_phi(long_text)
        
        # Should have called API twice (25k / 20k = 2 chunks)
        assert mock_client.detect_phi.call_count == 2
    
    async def test_entities_sorted_by_offset(self):
        """Test that entities are returned sorted."""
        mock_response = {
            'Entities': [
                {
                    'Category': 'DATE',
                    'Type': 'DATE',
                    'Text': 'last',
                    'BeginOffset': 30,
                    'EndOffset': 34,
                    'Score': 0.95,
                    'Traits': [],
                    'Attributes': [],
                },
                {
                    'Category': 'NAME',
                    'Type': 'PATIENT',
                    'Text': 'first',
                    'BeginOffset': 0,
                    'EndOffset': 5,
                    'Score': 0.95,
                    'Traits': [],
                    'Attributes': [],
                },
            ]
        }
        
        mock_client = AsyncMock()
        mock_client.detect_phi = AsyncMock(return_value=mock_response)
        
        mock_session = MagicMock()
        mock_session.client = MagicMock()
        mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session.client.return_value.__aexit__ = AsyncMock(return_value=None)
        
        service = AWSComprehendMedicalService(session=mock_session)
        entities = await service.detect_phi("test text")
        
        # Should be sorted by offset
        assert entities[0].text == "first"
        assert entities[1].text == "last"
    
    async def test_custom_masking_level(self):
        """Test CUSTOM mode with specific categories."""
        mock_response = {
            'Entities': [
                {
                    'Category': 'NAME',
                    'Type': 'PATIENT',
                    'Text': 'Name',
                    'BeginOffset': 0,
                    'EndOffset': 4,
                    'Score': 0.95,
                    'Traits': [],
                    'Attributes': [],
                },
                {
                    'Category': 'DATE',
                    'Type': 'DATE',
                    'Text': 'Date',
                    'BeginOffset': 10,
                    'EndOffset': 14,
                    'Score': 0.95,
                    'Traits': [],
                    'Attributes': [],
                },
            ]
        }
        
        mock_client = AsyncMock()
        mock_client.detect_phi = AsyncMock(return_value=mock_response)
        
        mock_session = MagicMock()
        mock_session.client = MagicMock()
        mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session.client.return_value.__aexit__ = AsyncMock(return_value=None)
        
        # Only mask NAME, not DATE
        service = AWSComprehendMedicalService(
            session=mock_session,
            custom_phi_categories={"NAME"}
        )
        entities = await service.detect_phi(
            "test text",
            masking_level=MaskingLevel.CUSTOM
        )
        
        # Should only include NAME
        assert len(entities) == 1
        assert entities[0].category == "NAME"
