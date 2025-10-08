"""
Integration tests for the complete de-identification pipeline.

Tests the full flow from document input to masked output using
mock services.
"""

import pytest
import io
from PIL import Image

from src.services.deidentification_service import DeidentificationService
from src.services.mock_ocr_service import MockOCRService
from src.services.mock_phi_detection_service import MockPHIDetectionService
from src.utils.tiff_processor import TIFFProcessor
from src.models.domain import MaskingLevel
from src.utils.document_processor import DocumentFormat


@pytest.mark.asyncio
class TestDeidentificationService:
    """Integration tests for de-identification pipeline."""
    
    def create_test_tiff(self, num_pages: int = 1) -> bytes:
        """Helper to create a simple test TIFF."""
        images = []
        for i in range(num_pages):
            img = Image.new('RGB', (800, 600), color=(255, 255, 255))
            images.append(img)
        
        output = io.BytesIO()
        images[0].save(
            output,
            format='TIFF',
            save_all=True,
            append_images=images[1:] if len(images) > 1 else [],
            dpi=(300, 300),
        )
        
        return output.getvalue()
    
    async def test_end_to_end_pipeline(self):
        """Test complete de-identification pipeline."""
        # Create test document
        tiff_bytes = self.create_test_tiff(num_pages=2)
        
        # Initialize services
        ocr_service = MockOCRService(seed=42)
        phi_service = MockPHIDetectionService()
        doc_processor = TIFFProcessor()
        
        # Create orchestrator
        service = DeidentificationService(
            ocr_service=ocr_service,
            phi_detection_service=phi_service,
            document_processor=doc_processor,
        )
        
        # Run pipeline
        result = await service.deidentify_document(tiff_bytes)
        
        # Verify result
        assert result.status == "success"
        assert result.pages_processed > 0
        assert result.phi_entities_count > 0
        assert len(result.mask_regions) > 0
        assert len(result.masked_image_bytes) > 0
        assert result.processing_time_ms > 0
        
        # Verify masked document is valid TIFF
        masked_img = Image.open(io.BytesIO(result.masked_image_bytes))
        assert masked_img.format == 'TIFF'
    
    async def test_safe_harbor_mode(self):
        """Test SAFE_HARBOR masking level."""
        tiff_bytes = self.create_test_tiff(num_pages=1)
        
        ocr_service = MockOCRService(seed=42)
        phi_service = MockPHIDetectionService()
        doc_processor = TIFFProcessor()
        
        service = DeidentificationService(
            ocr_service=ocr_service,
            phi_detection_service=phi_service,
            document_processor=doc_processor,
        )
        
        result = await service.deidentify_document(
            tiff_bytes,
            masking_level=MaskingLevel.SAFE_HARBOR
        )
        
        assert result.status == "success"
        
        # Should detect multiple PHI categories
        categories = {e.category for e in result.phi_entities}
        assert len(categories) > 1  # Multiple types of PHI
    
    async def test_limited_dataset_mode(self):
        """Test LIMITED_DATASET masking level."""
        tiff_bytes = self.create_test_tiff(num_pages=1)
        
        ocr_service = MockOCRService(seed=42)
        phi_service = MockPHIDetectionService()
        doc_processor = TIFFProcessor()
        
        service = DeidentificationService(
            ocr_service=ocr_service,
            phi_detection_service=phi_service,
            document_processor=doc_processor,
        )
        
        # Run with SAFE_HARBOR
        safe_result = await service.deidentify_document(
            tiff_bytes,
            masking_level=MaskingLevel.SAFE_HARBOR
        )
        
        # Run with LIMITED_DATASET
        limited_result = await service.deidentify_document(
            tiff_bytes,
            masking_level=MaskingLevel.LIMITED_DATASET
        )
        
        # LIMITED_DATASET should have fewer or equal entities
        assert limited_result.phi_entities_count <= safe_result.phi_entities_count
    
    async def test_multi_page_document(self):
        """Test processing multi-page document."""
        tiff_bytes = self.create_test_tiff(num_pages=5)
        
        ocr_service = MockOCRService(seed=42)
        phi_service = MockPHIDetectionService()
        doc_processor = TIFFProcessor()
        
        service = DeidentificationService(
            ocr_service=ocr_service,
            phi_detection_service=phi_service,
            document_processor=doc_processor,
        )
        
        result = await service.deidentify_document(tiff_bytes)
        
        assert result.status == "success"
        assert result.pages_processed == 5
        
        # Verify output has same number of pages
        masked_img = Image.open(io.BytesIO(result.masked_image_bytes))
        page_count = 0
        while True:
            try:
                masked_img.seek(page_count)
                page_count += 1
            except EOFError:
                break
        
        assert page_count == 5
    
    async def test_pipeline_with_ocr_errors(self):
        """Test that pipeline handles OCR errors gracefully."""
        tiff_bytes = self.create_test_tiff(num_pages=1)
        
        # High error rate to ensure OCR mistakes
        ocr_service = MockOCRService(error_rate=0.2, seed=42)
        phi_service = MockPHIDetectionService()
        doc_processor = TIFFProcessor()
        
        service = DeidentificationService(
            ocr_service=ocr_service,
            phi_detection_service=phi_service,
            document_processor=doc_processor,
        )
        
        result = await service.deidentify_document(tiff_bytes)
        
        # Should still succeed despite OCR errors
        assert result.status == "success"
        assert len(result.mask_regions) > 0
    
    async def test_unmatched_entities_warning(self):
        """Test that unmatched entities generate warnings."""
        tiff_bytes = self.create_test_tiff(num_pages=1)
        
        # Use services that will produce mismatches
        ocr_service = MockOCRService(seed=42)
        phi_service = MockPHIDetectionService()
        doc_processor = TIFFProcessor()
        
        service = DeidentificationService(
            ocr_service=ocr_service,
            phi_detection_service=phi_service,
            document_processor=doc_processor,
        )
        
        result = await service.deidentify_document(tiff_bytes)
        
        # Check if there are warnings about unmatched entities
        # (This depends on mock data, may or may not have warnings)
        if result.errors:
            assert any("could not match" in err.lower() for err in result.errors)
    
    async def test_from_path_convenience_method(self, tmp_path):
        """Test convenience method for file path input."""
        # Create test file
        tiff_bytes = self.create_test_tiff(num_pages=1)
        input_path = tmp_path / "input.tiff"
        input_path.write_bytes(tiff_bytes)
        
        output_path = tmp_path / "output.tiff"
        
        ocr_service = MockOCRService(seed=42)
        phi_service = MockPHIDetectionService()
        doc_processor = TIFFProcessor()
        
        service = DeidentificationService(
            ocr_service=ocr_service,
            phi_detection_service=phi_service,
            document_processor=doc_processor,
        )
        
        result = await service.deidentify_from_path(
            str(input_path),
            output_path=str(output_path)
        )
        
        assert result.status == "success"
        assert output_path.exists()
        assert output_path.stat().st_size > 0
    
    async def test_context_manager(self):
        """Test async context manager protocol."""
        tiff_bytes = self.create_test_tiff(num_pages=1)
        
        ocr_service = MockOCRService(seed=42)
        phi_service = MockPHIDetectionService()
        doc_processor = TIFFProcessor()
        
        async with DeidentificationService(
            ocr_service=ocr_service,
            phi_detection_service=phi_service,
            document_processor=doc_processor,
        ) as service:
            result = await service.deidentify_document(tiff_bytes)
            assert result.status == "success"
        
        # Service should be closed after context exit
    
    async def test_performance_metrics(self):
        """Test that performance metrics are captured."""
        tiff_bytes = self.create_test_tiff(num_pages=3)
        
        ocr_service = MockOCRService(seed=42)
        phi_service = MockPHIDetectionService()
        doc_processor = TIFFProcessor()
        
        service = DeidentificationService(
            ocr_service=ocr_service,
            phi_detection_service=phi_service,
            document_processor=doc_processor,
        )
        
        result = await service.deidentify_document(tiff_bytes)
        
        assert result.processing_time_ms > 0
        assert result.pages_processed == 3
        
        # Log output for inspection
        print(f"\nPerformance metrics:")
        print(f"  Pages: {result.pages_processed}")
        print(f"  PHI entities: {result.phi_entities_count}")
        print(f"  Mask regions: {len(result.mask_regions)}")
        print(f"  Processing time: {result.processing_time_ms:.0f}ms")
        print(f"  Time per page: {result.processing_time_ms / result.pages_processed:.0f}ms")
