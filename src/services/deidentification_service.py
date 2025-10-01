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
from typing import Optional, Union

from src.models.domain import (
    DeidentificationResult,
    MaskingLevel,
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
        output_format: Optional[Union[str,DocumentFormat]] = None,
    ) -> DeidentificationResult:
        """
        De-identify a document by masking all PHI.
        
        Args:
            document_bytes: Raw document bytes
            masking_level: HIPAA compliance level
            output_format: Desired output format (uses input format if None)
            
        Returns:
            DeidentificationResult with masked document and metadata
            
        Raises:
            DeidentificationError: If pipeline fails
        """
        start_time = time.time()
        errors = []
        if type(output_format) == str:
            output_format = DocumentFormat.from_string(output_format)
        try:
            logger.info(
                f"Starting de-identification pipeline "
                f"(masking_level={masking_level.value})"
            )
            
            # Step 1: Load document and split into pages
            logger.info("Step 1: Loading document")
            images, metadata = await self.document_processor.load_document(
                document_bytes
            )
            logger.info(f"Loaded {len(images)} pages")
            
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
    
    async def deidentify_from_path(
        self,
        file_path: str,
        masking_level: MaskingLevel = MaskingLevel.SAFE_HARBOR,
        output_path: Optional[str] = None,
        output_format: Optional[DocumentFormat] = None,
    ) -> DeidentificationResult:
        """
        De-identify a document from file path.
        
        Args:
            file_path: Path to input document
            masking_level: HIPAA compliance level
            output_path: Optional path to save output (if None, only returns bytes)
            output_format: Desired output format
            
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
        )
        
        # Save output if path provided
        if output_path and result.status == "success":
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
