"""
Abstract base class for OCR service providers.

This interface allows swapping between different OCR providers
(Azure Document Intelligence, AWS Textract, Mock) without changing
the core de-identification logic.
"""

from abc import ABC, abstractmethod
from typing import Optional
from src.models.domain import OCRResult


class OCRServiceError(Exception):
    """Base exception for OCR service errors."""
    pass


class OCRService(ABC):
    """Abstract base class for OCR providers."""
    
    @abstractmethod
    async def analyze_document(
        self,
        document_bytes: bytes,
        file_format: str = "tiff",
        language: Optional[str] = None,
    ) -> OCRResult:
        """
        Extract text and bounding boxes from document.
        
        Args:
            document_bytes: Raw document bytes
            file_format: Document format (tiff, pdf, png, jpg, etc.)
            language: Optional language hint (e.g., "en", "es")
            
        Returns:
            OCRResult with normalized structure
            
        Raises:
            OCRServiceError: If OCR fails
        """
        pass
    
    async def analyze_document_from_path(
        self,
        file_path: str,
        file_format: Optional[str] = None,
    ) -> OCRResult:
        """
        Convenience method to analyze document from file path.
        
        Args:
            file_path: Path to document file
            file_format: Optional format override (auto-detected if None)
            
        Returns:
            OCRResult with normalized structure
            
        Raises:
            OCRServiceError: If OCR fails
        """
        import aiofiles
        from pathlib import Path
        
        # Auto-detect format from extension if not provided
        if file_format is None:
            file_format = Path(file_path).suffix.lstrip('.')
        
        # Read file
        async with aiofiles.open(file_path, 'rb') as f:
            document_bytes = await f.read()
        
        return await self.analyze_document(document_bytes, file_format)