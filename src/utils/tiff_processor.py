"""
TIFF document processor implementation.

Handles multi-page TIFF loading, splitting, and reassembly with
metadata preservation.
"""

import io
import logging
from typing import List, Optional
from PIL import Image

from src.utils.document_processor import (
    DocumentProcessor,
    DocumentProcessorError,
    DocumentMetadata,
    DocumentFormat,
    CompressionLevel,
)

logger = logging.getLogger(__name__)


class TIFFProcessor(DocumentProcessor):
    """
    TIFF document processor.
    
    Features:
    - Multi-page TIFF support
    - DPI preservation
    - Lossless compression (LZW)
    - Memory-efficient page iteration
    """
    
    async def load_document(
        self,
        document_bytes: bytes,
    ) -> tuple[List[Image.Image], DocumentMetadata]:
        """
        Load TIFF document and extract pages.
        
        Args:
            document_bytes: TIFF file bytes
            
        Returns:
            Tuple of (page_images, metadata)
        """
        try:
            # Load TIFF from bytes
            tiff_io = io.BytesIO(document_bytes)
            img = Image.open(tiff_io)
            
            # Extract metadata from first page
            metadata = self._extract_metadata(img)
            
            # Extract all pages
            pages = []
            page_num = 0
            
            while True:
                try:
                    # Seek to current page
                    img.seek(page_num)
                    
                    # Copy the page (to detach from file handle)
                    page_copy = img.copy()
                    pages.append(page_copy)
                    
                    page_num += 1
                    
                except EOFError:
                    # No more pages
                    break
            
            metadata.page_count = len(pages)
            
            logger.info(f"Loaded TIFF: {len(pages)} pages, DPI={metadata.dpi}")
            
            return pages, metadata
            
        except Exception as e:
            logger.error(f"Failed to load TIFF: {e}")
            raise DocumentProcessorError(f"TIFF loading failed: {e}") from e
    
    async def save_document(
        self,
        images: List[Image.Image],
        metadata: DocumentMetadata,
        output_format: Optional[DocumentFormat] = None,
    ) -> bytes:
        """
        Save images as TIFF document.
        
        Args:
            images: Page images
            metadata: Document metadata to preserve
            output_format: Output format (must be TIFF for this processor)
            
        Returns:
            TIFF bytes
        """
        if output_format and output_format != DocumentFormat.TIFF:
            raise DocumentProcessorError(
                f"TIFFProcessor can only save as TIFF, not {output_format}"
            )
        
        if not images:
            raise DocumentProcessorError("Cannot save empty document")
        
        try:
            output = io.BytesIO()
            
            # Prepare save parameters
            save_params = {
                'format': 'TIFF',
                'compression': 'tiff_lzw',  # Lossless compression
            }
            
            # Restore DPI if available
            if metadata.dpi:
                save_params['dpi'] = metadata.dpi
            
            # Save first page
            first_page = images[0]
            
            if len(images) == 1:
                # Single page
                first_page.save(output, **save_params)
            else:
                # Multi-page: save additional pages
                remaining_pages = images[1:]
                first_page.save(
                    output,
                    save_all=True,
                    append_images=remaining_pages,
                    **save_params
                )
            
            tiff_bytes = output.getvalue()
            
            logger.info(
                f"Saved TIFF: {len(images)} pages, "
                f"size={len(tiff_bytes) / 1024 / 1024:.2f}MB"
            )
            
            return tiff_bytes
            
        except Exception as e:
            logger.error(f"Failed to save TIFF: {e}")
            raise DocumentProcessorError(f"TIFF saving failed: {e}") from e
    
    async def _apply_compression(
        self,
        images: List[Image.Image],
        compression: CompressionLevel,
    ) -> bytes:
        """
        Apply TIFF-specific compression.
        
        Args:
            images: Page images
            compression: Compression level
            
        Returns:
            Compressed TIFF bytes
        """
        output = io.BytesIO()
        
        # Map compression level to TIFF compression
        compression_map = {
            CompressionLevel.LOSSLESS: 'tiff_lzw',
            CompressionLevel.BALANCED: 'tiff_lzw',  # Still lossless for TIFF
        }
        
        tiff_compression = compression_map.get(
            compression,
            'tiff_lzw'  # Default to lossless
        )
        
        try:
            first_page = images[0]
            
            if len(images) == 1:
                first_page.save(
                    output,
                    format='TIFF',
                    compression=tiff_compression
                )
            else:
                first_page.save(
                    output,
                    format='TIFF',
                    save_all=True,
                    append_images=images[1:],
                    compression=tiff_compression
                )
            
            compressed_bytes = output.getvalue()
            
            logger.info(
                f"Compressed TIFF with {tiff_compression}: "
                f"size={len(compressed_bytes) / 1024 / 1024:.2f}MB"
            )
            
            return compressed_bytes
            
        except Exception as e:
            logger.error(f"Failed to compress TIFF: {e}")
            raise DocumentProcessorError(f"TIFF compression failed: {e}") from e
    
    def _extract_metadata(self, img: Image.Image) -> DocumentMetadata:
        """
        Extract metadata from TIFF image.
        
        Args:
            img: PIL Image object
            
        Returns:
            DocumentMetadata
        """
        # Get DPI
        dpi = img.info.get('dpi')
        if dpi and isinstance(dpi, tuple):
            dpi = (int(dpi[0]), int(dpi[1]))
        
        # Get color mode
        color_mode = img.mode
        
        # Get compression info if available
        compression = img.info.get('compression')
        
        return DocumentMetadata(
            format=DocumentFormat.TIFF,
            dpi=dpi,
            color_mode=color_mode,
            compression=compression,
            extras={
                'original_size': img.size,
            }
        )