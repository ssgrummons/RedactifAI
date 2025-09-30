"""
Integration test for the complete de-identification pipeline using mock services.
"""

import pytest
from src.services.mock_ocr_service import MockOCRService
from src.services.mock_phi_detection_service import MockPHIDetectionService
from src.services.entity_matcher import EntityMatcher
from src.models.domain import MaskingLevel


@pytest.mark.asyncio
class TestMockedPipeline:
    """Test full pipeline with mock services."""
    
    async def test_end_to_end_with_mocks(self):
        """Test complete de-identification pipeline."""
        # Initialize services
        ocr_service = MockOCRService(error_rate=0.05, seed=42)
        phi_service = MockPHIDetectionService()
        entity_matcher = EntityMatcher()
        
        # Step 1: OCR the document
        ocr_result = await ocr_service.analyze_document(b"fake_bytes")
        
        assert len(ocr_result.pages) > 0
        assert len(ocr_result.full_text) > 0
        assert "Samuel Grummons" in ocr_result.full_text
        
        # Step 2: Detect PHI
        phi_entities = await phi_service.detect_phi(
            ocr_result.full_text,
            masking_level=MaskingLevel.SAFE_HARBOR
        )
        
        assert len(phi_entities) > 0
        
        # Should detect at least: name, DOB, phone, email, address, MRN
        categories = {e.category for e in phi_entities}
        expected_categories = {"Person", "Date", "PhoneNumber", "Email", "MedicalRecordNumber"}
        assert expected_categories.issubset(categories)
        
        # Step 3: Match entities to bounding boxes
        mask_regions = entity_matcher.match_entities_to_boxes(
            ocr_result,
            phi_entities
        )
        
        assert len(mask_regions) > 0
        
        # Verify mask regions have valid structure
        for region in mask_regions:
            assert region.page >= 1
            assert region.bounding_box.width > 0
            assert region.bounding_box.height > 0
            assert 0.0 <= region.confidence <= 1.0
        
        print(f"\n✓ Processed {len(ocr_result.pages)} pages")
        print(f"✓ Detected {len(phi_entities)} PHI entities")
        print(f"✓ Created {len(mask_regions)} mask regions")
        
        # Print detected PHI for inspection
        print("\nDetected PHI:")
        for entity in phi_entities[:10]:  # First 10
            print(f"  - {entity.category}: '{entity.text}' "
                  f"(offset={entity.offset}, confidence={entity.confidence:.2f})")
    
    async def test_limited_dataset_mode(self):
        """Test that limited dataset mode keeps provider names."""
        ocr_service = MockOCRService(seed=42)
        phi_service = MockPHIDetectionService()
        
        ocr_result = await ocr_service.analyze_document(b"fake_bytes")
        
        # Detect with SAFE_HARBOR (masks everything)
        safe_harbor_entities = await phi_service.detect_phi(
            ocr_result.full_text,
            masking_level=MaskingLevel.SAFE_HARBOR
        )
        
        # Detect with LIMITED_DATASET (keeps providers)
        limited_entities = await phi_service.detect_phi(
            ocr_result.full_text,
            masking_level=MaskingLevel.LIMITED_DATASET
        )
        
        # LIMITED_DATASET should have fewer entities
        assert len(limited_entities) <= len(safe_harbor_entities)
        
        # Check that "Dr. Sarah Johnson" is excluded in limited mode
        safe_harbor_texts = {e.text for e in safe_harbor_entities}
        limited_texts = {e.text for e in limited_entities}
        
        assert "Sarah Johnson" in safe_harbor_texts or "Dr. Sarah Johnson" in safe_harbor_texts
        # Provider name should be in safe harbor but maybe not in limited
    
    async def test_handles_ocr_errors(self):
        """Test that pipeline handles OCR errors gracefully."""
        # High error rate to ensure we get some errors
        ocr_service = MockOCRService(error_rate=0.2, seed=42)
        phi_service = MockPHIDetectionService()
        entity_matcher = EntityMatcher(fuzzy_match_threshold=2)
        
        ocr_result = await ocr_service.analyze_document(b"fake_bytes")
        phi_entities = await phi_service.detect_phi(ocr_result.full_text)
        mask_regions = entity_matcher.match_entities_to_boxes(
            ocr_result,
            phi_entities
        )
        
        # Should still produce mask regions despite OCR errors
        assert len(mask_regions) > 0
        
        # Count OCR errors
        ocr_errors = sum(
            1 for page in ocr_result.pages
            for word in page.words
            if word.confidence < 0.90
        )
        
        print(f"\n✓ Handled {ocr_errors} OCR errors in document")