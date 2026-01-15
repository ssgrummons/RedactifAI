"""
TIFF document processor implementation.

Handles multi-page TIFF loading, splitting, and reassembly with
metadata preservation.
"""

import io
import logging
import os
import tempfile
from typing import List, Optional
from PIL import Image
import numpy as np
import tifffile

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
    - Streaming save for large documents (via tifffile)
    """
    
    # Use tifffile for documents larger than this
    STREAMING_THRESHOLD = 50
    
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
        
        For large documents (>STREAMING_THRESHOLD pages), uses tifffile
        for streaming save to avoid memory issues.
        
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
        
        # For small documents, use simple Pillow save
        if len(images) <= self.STREAMING_THRESHOLD:
            return await self._save_with_pillow(images, metadata)
        
        # For large documents, use tifffile streaming save
        return await self._save_with_tifffile(images, metadata)
    
    async def _save_with_pillow(
        self,
        images: List[Image.Image],
        metadata: DocumentMetadata,
    ) -> bytes:
        """
        Simple save for small documents using Pillow (≤ 50 pages).
        
        Uses Pillow's built-in multi-page save.
        """
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
                f"Saved TIFF (Pillow): {len(images)} pages, "
                f"size={len(tiff_bytes) / 1024 / 1024:.2f}MB"
            )
            
            return tiff_bytes
            
        except Exception as e:
            logger.error(f"Failed to save TIFF with Pillow: {e}")
            raise DocumentProcessorError(f"TIFF saving failed: {e}") from e
    
    async def _save_with_tifffile(
        self,
        images: List[Image.Image],
        metadata: DocumentMetadata,
    ) -> bytes:
        """
        Streaming save for large documents using tifffile library.
        
        Writes pages one at a time without loading entire document into memory.
        This prevents CPU/memory exhaustion on large documents.
        """
        try:
            logger.info(
                f"Saving large TIFF ({len(images)} pages) with tifffile "
                f"(streaming mode)"
            )
            
            # Create temporary file for writing
            with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp:
                tmp_path = tmp.name
            
            try:
                # Determine resolution
                if metadata.dpi:
                    if isinstance(metadata.dpi, tuple):
                        resolution = metadata.dpi
                    else:
                        resolution = (metadata.dpi, metadata.dpi)
                else:
                    resolution = (300, 300)  # Default 300 DPI
                
                # Write pages one at a time
                with tifffile.TiffWriter(tmp_path, bigtiff=True) as tif:
                    for i, img in enumerate(images):
                        # Log progress for large documents
                        if i % 50 == 0 or i == len(images) - 1:
                            logger.info(f"  Writing page {i + 1}/{len(images)}")
                        
                        # Convert PIL Image to numpy array
                        img_array = np.array(img)
                        
                        # Write page with compression
                        tif.write(
                            img_array,
                            compression='lzw',
                            resolution=resolution,
                            resolutionunit='INCH',
                        )
                
                # Read final file into memory
                with open(tmp_path, 'rb') as f:
                    tiff_bytes = f.read()
                
                logger.info(
                    f"Saved TIFF (tifffile): {len(images)} pages, "
                    f"size={len(tiff_bytes) / 1024 / 1024:.2f}MB"
                )
                
                return tiff_bytes
                
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except Exception as e:
                        logger.warning(f"Failed to delete temp file {tmp_path}: {e}")
                        
        except Exception as e:
            logger.error(f"Failed to save TIFF with tifffile: {e}")
            raise DocumentProcessorError(f"TIFF streaming save failed: {e}") from e
    
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
        # Use the appropriate save method based on size
        if len(images) <= self.STREAMING_THRESHOLD:
            return await self._apply_compression_pillow(images, compression)
        else:
            # tifffile always uses LZW, so just use regular save
            return await self._save_with_tifffile(
                images,
                DocumentMetadata(format=DocumentFormat.TIFF)
            )
    
    async def _apply_compression_pillow(
        self,
        images: List[Image.Image],
        compression: CompressionLevel,
    ) -> bytes:
        """
        Apply compression using Pillow (for small documents).
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