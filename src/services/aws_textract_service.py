"""
AWS Textract OCR service implementation.

Uses AWS Textract's DetectDocumentText API for text extraction.
API Documentation: https://docs.aws.amazon.com/textract/
"""

import logging
from typing import Optional, List
import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from src.models.domain import OCRResult, OCRPage, OCRWord, BoundingBox
from src.services.ocr_service import OCRService, OCRServiceError
from src.config.aws_settings import AWSSettings, aws_settings

logger = logging.getLogger(__name__)


class AWSTextractService(OCRService):
    """
    AWS Textract OCR implementation.
    
    Uses DetectDocumentText API which provides:
    - Word-level text extraction
    - Bounding box coordinates
    - Confidence scores
    - Single or multi-page support
    """
    
    def __init__(
        self,
        settings: Optional[AWSSettings] = None,
        session: Optional[aioboto3.Session] = None,
    ):
        """
        Initialize AWS Textract service.
        
        Args:
            settings: AWS configuration (uses global settings if None)
            session: Pre-configured aioboto3 session for testing
        """
        self.settings = settings or aws_settings
        
        if session:
            self.session = session
        else:
            # Validate configuration
            self.settings.validate_ocr_config()
            
            # Create session
            if self.settings.aws_access_key_id:
                # Using explicit credentials
                self.session = aioboto3.Session(
                    aws_access_key_id=self.settings.aws_access_key_id,
                    aws_secret_access_key=self.settings.aws_secret_access_key,
                    region_name=self.settings.get_textract_region(),
                )
            else:
                # Using IAM role
                self.session = aioboto3.Session(
                    region_name=self.settings.get_textract_region(),
                )
    
    async def analyze_document(
        self,
        document_bytes: bytes,
        file_format: str = "tiff",
        language: Optional[str] = None,
    ) -> OCRResult:
        """
        Extract text and bounding boxes using AWS Textract.
        
        Args:
            document_bytes: Raw document bytes
            file_format: Document format (ignored - Textract auto-detects)
            language: Optional language code (not supported by Textract)
            
        Returns:
            OCRResult with normalized structure
            
        Raises:
            OCRServiceError: If AWS API call fails
        """
        try:
            logger.info(f"Starting Textract OCR for {len(document_bytes)} bytes")
            
            async with self.session.client('textract') as textract:
                # Call DetectDocumentText
                response = await textract.detect_document_text(
                    Document={'Bytes': document_bytes}
                )
            
            # Convert AWS format to our domain model
            ocr_result = self._convert_textract_response(response)
            
            logger.info(
                f"Textract OCR completed: {len(ocr_result.pages)} pages, "
                f"{len(ocr_result.full_text)} characters"
            )
            
            return ocr_result
            
        except (BotoCoreError, ClientError) as e:
            logger.error(f"AWS Textract API error: {e}")
            raise OCRServiceError(f"AWS Textract failed: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during Textract OCR: {e}")
            raise OCRServiceError(f"OCR failed: {e}") from e
    
    def _convert_textract_response(self, response: dict) -> OCRResult:
        """
        Convert Textract response to OCRResult.
        
        Textract returns:
        - Blocks with type: PAGE, LINE, WORD
        - Geometry with BoundingBox and Polygon
        - Confidence scores
        
        We extract:
        - Pages with dimensions
        - Words with bounding boxes
        - Full text content
        """
        blocks = response.get('Blocks', [])
        
        # Extract document metadata
        doc_metadata = response.get('DocumentMetadata', {})
        num_pages = doc_metadata.get('Pages', 1)
        
        # Group blocks by page and type
        pages_data = {}
        full_text_parts = []
        
        for block in blocks:
            block_type = block.get('BlockType')
            page_num = block.get('Page', 1)
            
            if page_num not in pages_data:
                pages_data[page_num] = {
                    'width': 1.0,  # Textract uses normalized coordinates (0-1)
                    'height': 1.0,
                    'words': []
                }
            
            if block_type == 'WORD':
                word = self._extract_word(block, page_num)
                pages_data[page_num]['words'].append(word)
            elif block_type == 'LINE':
                # Collect text for full_text
                text = block.get('Text', '')
                if text:
                    full_text_parts.append(text)
        
        # Create OCRPage objects
        pages = []
        for page_num in sorted(pages_data.keys()):
            page_data = pages_data[page_num]
            pages.append(OCRPage(
                page_number=page_num,
                width=page_data['width'],
                height=page_data['height'],
                words=page_data['words'],
            ))
        
        # Join lines with newlines
        full_text = '\n'.join(full_text_parts)
        
        return OCRResult(pages=pages, full_text=full_text)
    
    def _extract_word(self, block: dict, page_num: int) -> OCRWord:
        """
        Extract word from Textract block.
        
        Args:
            block: Textract WORD block
            page_num: Page number
            
        Returns:
            OCRWord with bounding box
        """
        text = block.get('Text', '')
        confidence = block.get('Confidence', 0.0) / 100.0  # Convert to 0-1
        
        # Extract bounding box from Geometry
        geometry = block.get('Geometry', {})
        bbox_data = geometry.get('BoundingBox', {})
        
        # Textract returns normalized coordinates (0-1)
        # We'll keep them normalized but convert to BoundingBox
        bbox = BoundingBox(
            page=page_num,
            x=bbox_data.get('Left', 0.0),
            y=bbox_data.get('Top', 0.0),
            width=bbox_data.get('Width', 0.0),
            height=bbox_data.get('Height', 0.0),
        )
        
        return OCRWord(
            text=text,
            confidence=confidence,
            bounding_box=bbox,
        )
    
    async def close(self):
        """Close AWS session (no-op for aioboto3)."""
        pass
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
