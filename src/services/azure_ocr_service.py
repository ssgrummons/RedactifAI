"""
Azure Document Intelligence OCR service implementation.

Uses Azure's prebuilt-read model for OCR extraction.
API Documentation: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/
"""

import logging
from typing import Optional, List
from azure.ai.formrecognizer.aio import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError

from .ocr_service import OCRService, OCRServiceError
from src.config import AzureSettings, azure_settings
from src.models import OCRResult, OCRPage, OCRWord, BoundingBox

logger = logging.getLogger(__name__)


class AzureOCRService(OCRService):
    """
    Azure Document Intelligence OCR implementation.
    
    Uses the 'prebuilt-read' model which provides:
    - Word-level text extraction
    - Bounding box coordinates (as polygons)
    - Confidence scores
    - Multi-page support
    """
    
    def __init__(
        self,
        settings: Optional[AzureSettings] = None,
        client: Optional[DocumentAnalysisClient] = None,
    ):
        """
        Initialize Azure OCR service.
        
        Args:
            settings: Azure configuration (uses global settings if None)
            client: Pre-configured DocumentAnalysisClient for testing.
                    If provided, settings are ignored.
        """
        self.settings = settings or azure_settings
        
        if client:
            # Use injected client (for testing)
            self.client = client
        else:
            # Validate configuration
            self.settings.validate_ocr_config()
            
            # Create real client
            self.client = DocumentAnalysisClient(
                endpoint=self.settings.azure_document_intelligence_endpoint,
                credential=AzureKeyCredential(
                    self.settings.azure_document_intelligence_key
                ),
            )
    
    async def analyze_document(
        self,
        document_bytes: bytes,
        file_format: str = "tiff",
        language: Optional[str] = None,
    ) -> OCRResult:
        """
        Extract text and bounding boxes using Azure Document Intelligence.
        
        Args:
            document_bytes: Raw document bytes
            file_format: Document format (tiff, pdf, png, jpg)
            language: Optional language code (e.g., 'en', 'es')
            
        Returns:
            OCRResult with normalized structure
            
        Raises:
            OCRServiceError: If Azure API call fails
        """
        try:
            logger.info(f"Starting OCR analysis for {len(document_bytes)} bytes")
            
            # Call Azure Document Intelligence
            poller = await self.client.begin_analyze_document(
                model_id="prebuilt-read",
                document=document_bytes,
                locale=language,
            )
            
            azure_result = await poller.result()
            
            # Convert Azure format to our domain model
            ocr_result = self._convert_azure_result(azure_result)
            
            logger.info(
                f"OCR completed: {len(ocr_result.pages)} pages, "
                f"{len(ocr_result.full_text)} characters"
            )
            
            return ocr_result
            
        except AzureError as e:
            logger.error(f"Azure Document Intelligence API error: {e}")
            raise OCRServiceError(f"Azure OCR failed: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during OCR: {e}")
            raise OCRServiceError(f"OCR failed: {e}") from e
    
    def _convert_azure_result(self, azure_result) -> OCRResult:
        """
        Convert Azure's response format to our OCRResult model.
        
        Azure returns:
        - Pages with dimensions
        - Words with polygons (8 coordinates)
        - Lines with text
        - Full content as concatenated text
        
        We normalize to:
        - Pages with words and bounding boxes
        - Bounding boxes as (x, y, width, height)
        """
        pages: List[OCRPage] = []
        
        for page in azure_result.pages:
            words = self._extract_words_from_page(page)
            
            pages.append(OCRPage(
                page_number=page.page_number,
                width=page.width,
                height=page.height,
                words=words,
            ))
        
        # Azure provides full text content
        full_text = azure_result.content
        
        return OCRResult(pages=pages, full_text=full_text)
    
    def _extract_words_from_page(self, azure_page) -> List[OCRWord]:
        """Extract words with bounding boxes from Azure page."""
        words = []
        
        for word in azure_page.words:
            # Convert polygon to bounding box
            bbox = self._polygon_to_bbox(
                polygon=word.polygon,
                page_number=azure_page.page_number,
            )
            
            words.append(OCRWord(
                text=word.content,
                confidence=word.confidence,
                bounding_box=bbox,
            ))
        
        return words
    
    def _polygon_to_bbox(self, polygon: List[float], page_number: int) -> BoundingBox:
        """
        Convert Azure polygon (8 coordinates) to bounding box.
        
        Azure polygon format: [x1, y1, x2, y2, x3, y3, x4, y4]
        Represents four corners of a rectangle (may be rotated).
        
        We simplify to axis-aligned bounding box by taking:
        - min/max of x coordinates
        - min/max of y coordinates
        """
        if len(polygon) != 8:
            raise ValueError(f"Expected 8 polygon coordinates, got {len(polygon)}")
        
        # Extract x and y coordinates
        xs = [polygon[i] for i in range(0, 8, 2)]  # [x1, x2, x3, x4]
        ys = [polygon[i] for i in range(1, 8, 2)]  # [y1, y2, y3, y4]
        
        # Calculate bounding box
        min_x = min(xs)
        min_y = min(ys)
        max_x = max(xs)
        max_y = max(ys)
        
        return BoundingBox(
            page=page_number,
            x=min_x,
            y=min_y,
            width=max_x - min_x,
            height=max_y - min_y,
        )
    
    async def close(self):
        """Close the Azure client connection."""
        await self.client.close()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()