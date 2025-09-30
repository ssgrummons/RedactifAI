"""
Unit tests for AzureOCRService.

These tests mock the Azure SDK to verify our adapter logic without
hitting real Azure APIs.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from azure.core.exceptions import AzureError

from src.services import AzureOCRService, OCRServiceError


class MockAzureWord:
    """Mock Azure word object."""
    def __init__(self, content, confidence, polygon):
        self.content = content
        self.confidence = confidence
        self.polygon = polygon


class MockAzurePage:
    """Mock Azure page object."""
    def __init__(self, page_number, width, height, words):
        self.page_number = page_number
        self.width = width
        self.height = height
        self.words = words


class MockAzureResult:
    """Mock Azure analyze result."""
    def __init__(self, pages, content):
        self.pages = pages
        self.content = content


@pytest.mark.asyncio
class TestAzureOCRService:
    """Unit tests for Azure OCR service."""
    
    async def test_successful_ocr(self):
        """Test successful OCR with mocked Azure response."""
        # Create mock Azure result
        mock_word = MockAzureWord(
            content="Hello",
            confidence=0.99,
            polygon=[100.0, 200.0, 150.0, 200.0, 150.0, 220.0, 100.0, 220.0]
        )
        mock_page = MockAzurePage(
            page_number=1,
            width=2550.0,
            height=3300.0,
            words=[mock_word]
        )
        mock_result = MockAzureResult(
            pages=[mock_page],
            content="Hello"
        )
        
        # Create mock poller
        mock_poller = AsyncMock()
        mock_poller.result = AsyncMock(return_value=mock_result)
        
        # Create mock client
        mock_client = AsyncMock()
        mock_client.begin_analyze_document = AsyncMock(return_value=mock_poller)
        
        # Test with injected mock client
        service = AzureOCRService(client=mock_client)
        result = await service.analyze_document(b"fake_bytes")
        
        # Verify result structure
        assert len(result.pages) == 1
        assert result.pages[0].page_number == 1
        assert result.pages[0].width == 2550.0
        assert result.pages[0].height == 3300.0
        assert len(result.pages[0].words) == 1
        
        word = result.pages[0].words[0]
        assert word.text == "Hello"
        assert word.confidence == 0.99
        assert word.bounding_box.page == 1
        assert word.bounding_box.x == 100.0
        assert word.bounding_box.y == 200.0
        assert word.bounding_box.width == 50.0
        assert word.bounding_box.height == 20.0
        
        assert result.full_text == "Hello"
    
    async def test_multi_page_document(self):
        """Test OCR with multiple pages."""
        mock_word1 = MockAzureWord(
            content="Page1",
            confidence=0.99,
            polygon=[100.0, 200.0, 160.0, 200.0, 160.0, 220.0, 100.0, 220.0]
        )
        mock_word2 = MockAzureWord(
            content="Page2",
            confidence=0.98,
            polygon=[100.0, 200.0, 160.0, 200.0, 160.0, 220.0, 100.0, 220.0]
        )
        
        mock_page1 = MockAzurePage(1, 2550.0, 3300.0, [mock_word1])
        mock_page2 = MockAzurePage(2, 2550.0, 3300.0, [mock_word2])
        
        mock_result = MockAzureResult(
            pages=[mock_page1, mock_page2],
            content="Page1\nPage2"
        )
        
        mock_poller = AsyncMock()
        mock_poller.result = AsyncMock(return_value=mock_result)
        
        mock_client = AsyncMock()
        mock_client.begin_analyze_document = AsyncMock(return_value=mock_poller)
        
        service = AzureOCRService(client=mock_client)
        result = await service.analyze_document(b"fake_bytes")
        
        assert len(result.pages) == 2
        assert result.pages[0].page_number == 1
        assert result.pages[1].page_number == 2
        assert result.full_text == "Page1\nPage2"
    
    async def test_polygon_to_bbox_conversion(self):
        """Test polygon to bounding box conversion."""
        service = AzureOCRService(client=AsyncMock())
        
        # Regular rectangle
        polygon = [100.0, 200.0, 150.0, 200.0, 150.0, 220.0, 100.0, 220.0]
        bbox = service._polygon_to_bbox(polygon, page_number=1)
        
        assert bbox.page == 1
        assert bbox.x == 100.0
        assert bbox.y == 200.0
        assert bbox.width == 50.0
        assert bbox.height == 20.0
    
    async def test_rotated_polygon_to_bbox(self):
        """Test that rotated polygons are converted to axis-aligned boxes."""
        service = AzureOCRService(client=AsyncMock())
        
        # Rotated rectangle (not axis-aligned)
        polygon = [110.0, 200.0, 160.0, 210.0, 150.0, 230.0, 100.0, 220.0]
        bbox = service._polygon_to_bbox(polygon, page_number=1)
        
        # Should create axis-aligned bounding box
        assert bbox.x == 100.0  # min x
        assert bbox.y == 200.0  # min y
        assert bbox.width == 60.0  # max_x - min_x
        assert bbox.height == 30.0  # max_y - min_y
    
    async def test_azure_error_handling(self):
        """Test error handling when Azure API fails."""
        mock_client = AsyncMock()
        mock_client.begin_analyze_document = AsyncMock(
            side_effect=AzureError("API error")
        )
        
        service = AzureOCRService(client=mock_client)
        
        with pytest.raises(OCRServiceError, match="Azure OCR failed"):
            await service.analyze_document(b"fake_bytes")
    
    async def test_invalid_polygon_length(self):
        """Test error handling for invalid polygon coordinates."""
        service = AzureOCRService(client=AsyncMock())
        
        # Invalid polygon (should have 8 coordinates)
        with pytest.raises(ValueError, match="Expected 8 polygon coordinates"):
            service._polygon_to_bbox([100.0, 200.0, 150.0], page_number=1)
    
    async def test_context_manager(self):
        """Test async context manager protocol."""
        mock_client = AsyncMock()
        mock_client.close = AsyncMock()
        
        async with AzureOCRService(client=mock_client) as service:
            assert service is not None
        
        # Verify close was called
        mock_client.close.assert_called_once()