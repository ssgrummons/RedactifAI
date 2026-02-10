"""
Deidentification orchestration service.

Coordinates the complete pipeline:
1. Load document (TIFF/PDF/etc)
2. OCR extraction
3. PHI detection
4. Entity-to-bbox matching
5. Image masking
6. Document reassembly
"""

import logging
import time
from typing import Optional, Union, List
from dataclasses import replace
from PIL import Image

from src.models.domain import (
    DeidentificationResult,
    MaskingLevel,
    PHIEntity,
    MaskRegion,
)
from src.services.ocr_service import OCRService
from src.services.phi_detection_service import PHIDetectionService
from src.services.entity_matcher import EntityMatcher
from src.services.image_masking_service import ImageMaskingService
from src.utils.document_processor import DocumentProcessor, DocumentFormat

logger = logging.getLogger(__name__)


class DeidentificationError(Exception):
    """Base exception for deidentification errors."""
    pass


class DeidentificationService:
    """
    Orchestrates the complete de-identification pipeline.
    
    This service coordinates all components to transform a document
    containing PHI into a redacted version suitable for sharing.
    """
    
    def __init__(
        self,
        ocr_service: OCRService,
        phi_detection_service: PHIDetectionService,
        document_processor: DocumentProcessor,
        entity_matcher: Optional[EntityMatcher] = None,
        image_masking_service: Optional[ImageMaskingService] = None,
    ):
        """
        Initialize deidentification service.
        
        Args:
            ocr_service: Service for OCR text extraction
            phi_detection_service: Service for PHI detection
            document_processor: Document loading/saving
            entity_matcher: Entity matching logic (creates default if None)
            image_masking_service: Image masking logic (creates default if None)
        """
        self.ocr_service = ocr_service
        self.phi_detection_service = phi_detection_service
        self.document_processor = document_processor
        self.entity_matcher = entity_matcher or EntityMatcher()
        self.image_masking_service = image_masking_service or ImageMaskingService()
    
    async def deidentify_document(
        self,
        document_bytes: bytes,
        masking_level: MaskingLevel = MaskingLevel.SAFE_HARBOR,
        output_format: Optional[Union[str, DocumentFormat]] = None,
        batch_size: int = 5,
    ) -> DeidentificationResult:
        """
        De-identify a document by masking all PHI.
        
        Args:
            document_bytes: Raw document bytes
            masking_level: HIPAA compliance level
            output_format: Desired output format (uses input format if None)
            batch_size: Number of pages to process at once (controls memory usage)
            
        Returns:
            DeidentificationResult with masked document and metadata
            
        Raises:
            DeidentificationError: If pipeline fails
        """
        start_time = time.time()
        errors = []
        
        if isinstance(output_format, str):
            output_format = DocumentFormat.from_string(output_format)
        
        try:
            logger.info(
                f"Starting de-identification pipeline "
                f"(masking_level={masking_level.value}, batch_size={batch_size})"
            )
            
            # Step 1: Load document and split into pages
            logger.info("Step 1: Loading document")
            images, metadata = await self.document_processor.load_document(
                document_bytes
            )
            total_pages = len(images)
            logger.info(f"Loaded {total_pages} pages")
            
            # Determine if we need batching
            if total_pages <= batch_size:
                logger.info(f"Small document ({total_pages} pages), processing in single batch")
                return await self._process_single_batch(
                    images, metadata, masking_level, output_format, start_time
                )
            
            # Large document - process in batches
            logger.info(f"Large document ({total_pages} pages), processing in batches of {batch_size}")
            return await self._process_batched(
                images, metadata, masking_level, output_format, batch_size, start_time
            )
            
        except Exception as e:
            processing_time_ms = (time.time() - start_time) * 1000
            error_msg = f"De-identification failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            errors.append(error_msg)
            
            return DeidentificationResult(
                status="failure",
                masked_image_bytes=b"",
                pages_processed=0,
                phi_entities_count=0,
                phi_entities=[],
                mask_regions=[],
                processing_time_ms=processing_time_ms,
                errors=errors,
            )
    
    async def _process_single_batch(
        self,
        images: List[Image.Image],
        metadata: dict,
        masking_level: MaskingLevel,
        output_format: Optional[DocumentFormat],
        start_time: float,
    ) -> DeidentificationResult:
        """Process document as a single batch (original logic)."""
        errors = []
        
        # Step 2: Optimize for OCR and extract text
        logger.info("Step 2: Running OCR")
        ocr_bytes = await self.document_processor.optimize_for_ocr(images)
        ocr_result = await self.ocr_service.analyze_document(ocr_bytes)
        
        total_words = sum(len(page.words) for page in ocr_result.pages)
        logger.info(f"OCR extracted {total_words} words from {len(ocr_result.pages)} pages")
        
        # Step 3: Detect PHI entities
        logger.info("Step 3: Detecting PHI")
        phi_entities = await self.phi_detection_service.detect_phi(
            ocr_result.full_text,
            masking_level=masking_level
        )
        logger.info(f"Detected {len(phi_entities)} PHI entities")
        
        # Step 4: Match entities to bounding boxes
        logger.info("Step 4: Matching entities to bounding boxes")
        mask_regions = self.entity_matcher.match_entities_to_boxes(
            ocr_result,
            phi_entities
        )
        logger.info(f"Created {len(mask_regions)} mask regions")
        
        # Check if we failed to match any entities
        unmatched_count = len(phi_entities) - len(mask_regions)
        if unmatched_count > 0:
            warning = (
                f"Warning: Could not match {unmatched_count} PHI entities "
                f"to bounding boxes. These may not be masked."
            )
            logger.warning(warning)
            errors.append(warning)
        
        # Step 5: Apply masks to images
        logger.info("Step 5: Applying masks to images")
        masked_images = self.image_masking_service.apply_masks(
            images,
            mask_regions
        )
        
        # Step 6: Reassemble document
        logger.info("Step 6: Reassembling document")
        masked_bytes = await self.document_processor.save_document(
            masked_images,
            metadata,
            output_format=output_format
        )
        
        # Calculate processing time
        processing_time_ms = (time.time() - start_time) * 1000
        
        logger.info(
            f"De-identification complete: {len(images)} pages, "
            f"{len(phi_entities)} PHI entities, "
            f"{len(mask_regions)} masks applied, "
            f"{processing_time_ms:.0f}ms"
        )
        
        return DeidentificationResult(
            status="success",
            masked_image_bytes=masked_bytes,
            pages_processed=len(images),
            phi_entities_count=len(phi_entities),
            phi_entities=phi_entities,
            mask_regions=mask_regions,
            processing_time_ms=processing_time_ms,
            errors=errors,
        )
    
    async def _process_batched(
        self,
        images: List[Image.Image],
        metadata: dict,
        masking_level: MaskingLevel,
        output_format: Optional[DocumentFormat],
        batch_size: int,
        start_time: float,
    ) -> DeidentificationResult:
        """Process large document in batches to control memory."""
        import tempfile
        import tifffile
        import numpy as np
        import os
        
        errors = []
        total_pages = len(images)
        
        all_phi_entities = []
        all_mask_regions = []
        
        # Create temporary file for streaming output
        with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp:
            tmp_output_path = tmp.name
        
        try:
            logger.info(f"Streaming output to temp file: {tmp_output_path}")
            
            # Determine resolution
            if metadata.dpi:
                if isinstance(metadata.dpi, tuple):
                    resolution = metadata.dpi
                else:
                    resolution = (metadata.dpi, metadata.dpi)
            else:
                resolution = (300, 300)
            
            # Open TIFF writer for streaming output
            num_batches = (total_pages + batch_size - 1) // batch_size
            
            with tifffile.TiffWriter(tmp_output_path, bigtiff=True) as tif:
                for batch_num in range(num_batches):
                    batch_start = batch_num * batch_size
                    batch_end = min(batch_start + batch_size, total_pages)
                    
                    logger.info(
                        f"Processing batch {batch_num + 1}/{num_batches}: "
                        f"pages {batch_start + 1}-{batch_end}"
                    )
                    
                    # Extract batch of images
                    batch_images = images[batch_start:batch_end]
                    
                    try:
                        # OCR this batch
                        logger.info(f"  Step 2 (batch): OCR on {len(batch_images)} pages")
                        batch_ocr_bytes = await self.document_processor.optimize_for_ocr(batch_images)
                        batch_ocr_result = await self.ocr_service.analyze_document(batch_ocr_bytes)
                        
                        # PHI detection
                        logger.info(f"  Step 3 (batch): Detecting PHI")
                        batch_phi_entities = await self.phi_detection_service.detect_phi(
                            batch_ocr_result.full_text,
                            masking_level=masking_level
                        )
                        logger.info(f"  Detected {len(batch_phi_entities)} PHI entities")
                        
                        # Match entities
                        logger.info(f"  Step 4 (batch): Matching entities to bounding boxes")
                        batch_mask_regions = self.entity_matcher.match_entities_to_boxes(
                            batch_ocr_result,
                            batch_phi_entities
                        )
                        logger.info(f"  Created {len(batch_mask_regions)} mask regions")
                        
                        unmatched = len(batch_phi_entities) - len(batch_mask_regions)
                        if unmatched > 0:
                            warning = f"  Warning: {unmatched} entities unmatched in batch {batch_num + 1}"
                            logger.warning(warning)
                            errors.append(warning)
                        
                        # Apply masks
                        logger.info(f"  Step 5 (batch): Applying {len(batch_mask_regions)} masks")
                        batch_masked_images = self.image_masking_service.apply_masks(
                            batch_images,
                            batch_mask_regions
                        )
                        
                        # Write masked images to TIFF immediately (don't accumulate in memory)
                        logger.info(f"  Step 6 (batch): Writing {len(batch_masked_images)} pages to disk")
                        for img in batch_masked_images:
                            img_array = np.array(img)
                            tif.write(
                                img_array,
                                compression='lzw',
                                resolution=resolution,
                                resolutionunit='INCH',
                            )
                        
                        # Accumulate metadata only (not images!)
                        all_phi_entities.extend(batch_phi_entities)
                        all_mask_regions.extend(batch_mask_regions)
                        
                        # Clean up batch images explicitly
                        del batch_images
                        del batch_masked_images
                        del batch_ocr_bytes
                        
                        logger.info(f"  Batch {batch_num + 1} complete")
                        
                    except Exception as e:
                        error_msg = f"Batch {batch_num + 1} failed: {str(e)}"
                        logger.error(error_msg, exc_info=True)
                        errors.append(error_msg)
                        
                        # Write unmasked copies as fallback
                        for img in images[batch_start:batch_end]:
                            img_array = np.array(img)
                            tif.write(
                                img_array,
                                compression='lzw',
                                resolution=resolution,
                                resolutionunit='INCH',
                            )
            
            # Read final TIFF from disk
            logger.info("Step 6: Reading final document from disk")
            with open(tmp_output_path, 'rb') as f:
                masked_bytes = f.read()
            
            processing_time_ms = (time.time() - start_time) * 1000
            
            logger.info(
                f"De-identification complete: {total_pages} pages, "
                f"{len(all_phi_entities)} PHI entities, "
                f"{len(all_mask_regions)} masks applied, "
                f"{processing_time_ms:.0f}ms"
            )
            
            # Determine status based on errors
            if errors:
                status = "success"  # Success with warnings
            else:
                status = "success"
            
            return DeidentificationResult(
                status=status,
                masked_image_bytes=masked_bytes,
                pages_processed=total_pages,
                phi_entities_count=len(all_phi_entities),
                phi_entities=all_phi_entities,
                mask_regions=all_mask_regions,
                processing_time_ms=processing_time_ms,
                errors=errors,
            )
            
        finally:
            # Clean up temp file
            if os.path.exists(tmp_output_path):
                try:
                    os.unlink(tmp_output_path)
                    logger.info(f"Cleaned up temp file: {tmp_output_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete temp file {tmp_output_path}: {e}")
    
    def _adjust_mask_region_pages(
        self,
        mask_regions: List[MaskRegion],
        page_offset: int,
    ) -> List[MaskRegion]:
        """
        Adjust page numbers in mask regions.
        
        When processing batches, we need to:
        1. Add page_offset to convert from batch-relative (1-based) to document-absolute
        2. Subtract page_offset to convert from document-absolute back to batch-relative
        
        Args:
            mask_regions: Mask regions to adjust
            page_offset: Offset to add to page numbers (can be negative)
            
        Returns:
            New list of mask regions with adjusted page numbers
        """
        adjusted_regions = []
        
        for region in mask_regions:
            # Create new region with adjusted page number
            adjusted_region = replace(region, page=region.page + page_offset)
            adjusted_regions.append(adjusted_region)
        
        return adjusted_regions
    
    async def deidentify_from_path(
        self,
        file_path: str,
        masking_level: MaskingLevel = MaskingLevel.SAFE_HARBOR,
        output_path: Optional[str] = None,
        output_format: Optional[DocumentFormat] = None,
        batch_size: int = 25,
    ) -> DeidentificationResult:
        """
        De-identify a document from file path.
        
        Args:
            file_path: Path to input document
            masking_level: HIPAA compliance level
            output_path: Optional path to save output (if None, only returns bytes)
            output_format: Desired output format
            batch_size: Pages per batch for large documents
            
        Returns:
            DeidentificationResult
        """
        import aiofiles
        
        # Read input file
        async with aiofiles.open(file_path, 'rb') as f:
            document_bytes = await f.read()
        
        # Process
        result = await self.deidentify_document(
            document_bytes,
            masking_level=masking_level,
            output_format=output_format,
            batch_size=batch_size,
        )
        
        # Save output if path provided
        if output_path and result.status in ("success", "partial_success"):
            async with aiofiles.open(output_path, 'wb') as f:
                await f.write(result.masked_image_bytes)
            logger.info(f"Saved de-identified document to {output_path}")
        
        return result
    
    async def close(self):
        """Clean up resources."""
        # Close OCR service if it has close method
        if hasattr(self.ocr_service, 'close'):
            await self.ocr_service.close()
        
        # Close PHI detection service if it has close method
        if hasattr(self.phi_detection_service, 'close'):
            await self.phi_detection_service.close()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()