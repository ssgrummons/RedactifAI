"""
Abstract interface for document processing.

Handles loading, splitting, optimization, and reassembly of documents
across multiple formats (TIFF, PDF, PNG series).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from PIL import Image
from enum import Enum


class DocumentFormat(str, Enum):
    """Supported document formats."""
    TIFF = "tiff"
    PDF = "pdf"
    PNG = "png"
    JPEG = "jpeg"


class CompressionLevel(str, Enum):
    """Compression strategies for OCR optimization."""
    NONE = "none"          # No compression
    LOSSLESS = "lossless"  # PNG or TIFF LZW
    BALANCED = "balanced"  # Slight quality reduction for size


@dataclass
class DocumentMetadata:
    """
    Metadata to preserve during document processing.
    
    Captures format-specific information that should be maintained
    when reassembling the document.
    """
    format: DocumentFormat
    dpi: Optional[tuple[int, int]] = None  # (x_dpi, y_dpi)
    color_mode: Optional[str] = None  # "RGB", "L" (grayscale), etc.
    compression: Optional[str] = None  # Original compression type
    page_count: int = 0
    
    # Format-specific extras
    extras: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.extras is None:
            self.extras = {}


class DocumentProcessorError(Exception):
    """Base exception for document processing errors."""
    pass


class DocumentProcessor(ABC):
    """
    Abstract base class for document processors.
    
    Subclasses implement format-specific loading and saving logic,
    but all work with PIL Images as the common in-memory format.
    """
    
    @abstractmethod
    async def load_document(
        self,
        document_bytes: bytes,
    ) -> tuple[List[Image.Image], DocumentMetadata]:
        """
        Load document and split into pages.
        
        Args:
            document_bytes: Raw document bytes
            
        Returns:
            Tuple of (page_images, metadata)
            Each image is a PIL.Image object
            
        Raises:
            DocumentProcessorError: If loading fails
        """
        pass
    
    @abstractmethod
    async def save_document(
        self,
        images: List[Image.Image],
        metadata: DocumentMetadata,
        output_format: Optional[DocumentFormat] = None,
    ) -> bytes:
        """
        Reassemble images into document.
        
        Args:
            images: List of PIL Images (one per page)
            metadata: Original document metadata
            output_format: Desired output format (uses metadata.format if None)
            
        Returns:
            Document as bytes
            
        Raises:
            DocumentProcessorError: If saving fails
        """
        pass
    
    async def optimize_for_ocr(
        self,
        images: List[Image.Image],
        max_size_mb: float = 10.0,
        compression: CompressionLevel = CompressionLevel.LOSSLESS,
    ) -> bytes:
        """
        Optimize document for OCR service upload.
        
        Applies compression if total size exceeds threshold to reduce
        upload time and API costs without significantly impacting OCR quality.
        
        Args:
            images: Page images
            max_size_mb: Maximum size before compression kicks in
            compression: Compression strategy to use
            
        Returns:
            Optimized document bytes
        """
        # Estimate current size (rough approximation)
        estimated_size_mb = sum(
            img.width * img.height * len(img.getbands()) / (1024 * 1024)
            for img in images
        )
        
        if compression == CompressionLevel.NONE or estimated_size_mb <= max_size_mb:
            # No optimization needed
            metadata = DocumentMetadata(
                format=DocumentFormat.TIFF,
                page_count=len(images)
            )
            return await self.save_document(images, metadata)
        
        # Apply compression
        return await self._apply_compression(images, compression)
    
    @abstractmethod
    async def _apply_compression(
        self,
        images: List[Image.Image],
        compression: CompressionLevel,
    ) -> bytes:
        """
        Apply format-specific compression.
        
        Args:
            images: Page images
            compression: Compression level
            
        Returns:
            Compressed document bytes
        """
        pass
    
    async def load_from_path(self, file_path: str) -> tuple[List[Image.Image], DocumentMetadata]:
        """
        Convenience method to load document from file path.
        
        Args:
            file_path: Path to document file
            
        Returns:
            Tuple of (page_images, metadata)
        """
        import aiofiles
        
        async with aiofiles.open(file_path, 'rb') as f:
            document_bytes = await f.read()
        
        return await self.load_document(document_bytes)
    
    async def save_to_path(
        self,
        images: List[Image.Image],
        metadata: DocumentMetadata,
        file_path: str,
        output_format: Optional[DocumentFormat] = None,
    ) -> None:
        """
        Convenience method to save document to file path.
        
        Args:
            images: Page images
            metadata: Document metadata
            file_path: Output file path
            output_format: Desired format
        """
        import aiofiles
        
        document_bytes = await self.save_document(images, metadata, output_format)
        
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(document_bytes)