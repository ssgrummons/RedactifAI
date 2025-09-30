"""
Unit tests for domain models.
"""

import pytest
from src.models.domain import (
    BoundingBox,
    OCRWord,
    OCRPage,
    OCRResult,
    PHIEntity,
    MaskRegion,
    MaskingLevel,
    DeidentificationResult,
)


class TestBoundingBox:
    """Tests for BoundingBox dataclass."""
    
    def test_valid_bounding_box(self):
        """Test creating a valid bounding box."""
        bbox = BoundingBox(page=1, x=100.0, y=200.0, width=50.0, height=30.0)
        assert bbox.page == 1
        assert bbox.x == 100.0
        assert bbox.y == 200.0
        assert bbox.width == 50.0
        assert bbox.height == 30.0
    
    def test_invalid_page_number(self):
        """Test that page number must be >= 1."""
        with pytest.raises(ValueError, match="Page must be >= 1"):
            BoundingBox(page=0, x=100.0, y=200.0, width=50.0, height=30.0)
    
    def test_negative_dimensions(self):
        """Test that width and height must be non-negative."""
        with pytest.raises(ValueError, match="Width and height must be >= 0"):
            BoundingBox(page=1, x=100.0, y=200.0, width=-50.0, height=30.0)
    
    def test_overlaps_same_page(self):
        """Test overlap detection on same page."""
        box1 = BoundingBox(page=1, x=100.0, y=100.0, width=50.0, height=50.0)
        box2 = BoundingBox(page=1, x=120.0, y=120.0, width=50.0, height=50.0)
        assert box1.overlaps(box2)
        assert box2.overlaps(box1)
    
    def test_no_overlap_same_page(self):
        """Test non-overlapping boxes on same page."""
        box1 = BoundingBox(page=1, x=100.0, y=100.0, width=50.0, height=50.0)
        box2 = BoundingBox(page=1, x=200.0, y=200.0, width=50.0, height=50.0)
        assert not box1.overlaps(box2)
    
    def test_no_overlap_different_pages(self):
        """Test that boxes on different pages never overlap."""
        box1 = BoundingBox(page=1, x=100.0, y=100.0, width=50.0, height=50.0)
        box2 = BoundingBox(page=2, x=100.0, y=100.0, width=50.0, height=50.0)
        assert not box1.overlaps(box2)
    
    def test_area_calculation(self):
        """Test bounding box area calculation."""
        bbox = BoundingBox(page=1, x=100.0, y=100.0, width=50.0, height=30.0)
        assert bbox.area() == 1500.0


class TestOCRWord:
    """Tests for OCRWord dataclass."""
    
    def test_valid_word(self):
        """Test creating a valid OCR word."""
        bbox = BoundingBox(page=1, x=100.0, y=200.0, width=50.0, height=20.0)
        word = OCRWord(text="Hello", confidence=0.95, bounding_box=bbox)
        assert word.text == "Hello"
        assert word.confidence == 0.95
        assert word.bounding_box == bbox
    
    def test_invalid_confidence_too_high(self):
        """Test that confidence must be <= 1.0."""
        bbox = BoundingBox(page=1, x=100.0, y=200.0, width=50.0, height=20.0)
        with pytest.raises(ValueError, match="Confidence must be 0.0-1.0"):
            OCRWord(text="Hello", confidence=1.5, bounding_box=bbox)
    
    def test_invalid_confidence_negative(self):
        """Test that confidence must be >= 0.0."""
        bbox = BoundingBox(page=1, x=100.0, y=200.0, width=50.0, height=20.0)
        with pytest.raises(ValueError, match="Confidence must be 0.0-1.0"):
            OCRWord(text="Hello", confidence=-0.1, bounding_box=bbox)


class TestOCRPage:
    """Tests for OCRPage dataclass."""
    
    def test_valid_page(self):
        """Test creating a valid OCR page."""
        bbox = BoundingBox(page=1, x=100.0, y=200.0, width=50.0, height=20.0)
        word = OCRWord(text="Hello", confidence=0.95, bounding_box=bbox)
        page = OCRPage(
            page_number=1,
            width=2550.0,
            height=3300.0,
            words=[word]
        )
        assert page.page_number == 1
        assert page.width == 2550.0
        assert page.height == 3300.0
        assert len(page.words) == 1
    
    def test_invalid_page_number(self):
        """Test that page number must be >= 1."""
        with pytest.raises(ValueError, match="Page number must be >= 1"):
            OCRPage(page_number=0, width=2550.0, height=3300.0, words=[])
    
    def test_invalid_dimensions(self):
        """Test that page dimensions must be > 0."""
        with pytest.raises(ValueError, match="Page dimensions must be > 0"):
            OCRPage(page_number=1, width=0.0, height=3300.0, words=[])


class TestOCRResult:
    """Tests for OCRResult dataclass."""
    
    def test_valid_result(self):
        """Test creating a valid OCR result."""
        bbox = BoundingBox(page=1, x=100.0, y=200.0, width=50.0, height=20.0)
        word = OCRWord(text="Hello", confidence=0.95, bounding_box=bbox)
        page = OCRPage(page_number=1, width=2550.0, height=3300.0, words=[word])
        result = OCRResult(pages=[page], full_text="Hello")
        assert len(result.pages) == 1
        assert result.full_text == "Hello"
    
    def test_empty_pages_invalid(self):
        """Test that OCRResult must have at least one page."""
        with pytest.raises(ValueError, match="must have at least one page"):
            OCRResult(pages=[], full_text="")
    
    def test_non_sequential_pages_invalid(self):
        """Test that pages must be sequential."""
        page1 = OCRPage(page_number=1, width=2550.0, height=3300.0, words=[])
        page3 = OCRPage(page_number=3, width=2550.0, height=3300.0, words=[])
        with pytest.raises(ValueError, match="Pages must be sequential"):
            OCRResult(pages=[page1, page3], full_text="test")


class TestPHIEntity:
    """Tests for PHIEntity dataclass."""
    
    def test_valid_entity(self):
        """Test creating a valid PHI entity."""
        entity = PHIEntity(
            text="John Smith",
            category="Person",
            offset=0,
            length=10,
            confidence=0.95
        )
        assert entity.text == "John Smith"
        assert entity.category == "Person"
        assert entity.offset == 0
        assert entity.length == 10
        assert entity.confidence == 0.95
        assert entity.end_offset == 10
    
    def test_negative_offset_invalid(self):
        """Test that offset must be >= 0."""
        with pytest.raises(ValueError, match="Offset must be >= 0"):
            PHIEntity(
                text="test",
                category="Person",
                offset=-1,
                length=4,
                confidence=0.95
            )
    
    def test_zero_length_invalid(self):
        """Test that length must be > 0."""
        with pytest.raises(ValueError, match="Length must be > 0"):
            PHIEntity(
                text="test",
                category="Person",
                offset=0,
                length=0,
                confidence=0.95
            )
    
    def test_overlaps_with(self):
        """Test entity overlap detection."""
        entity1 = PHIEntity(
            text="John Smith",
            category="Person",
            offset=0,
            length=10,
            confidence=0.95
        )
        entity2 = PHIEntity(
            text="Smith",
            category="LastName",
            offset=5,
            length=5,
            confidence=0.95
        )
        assert entity1.overlaps_with(entity2)
        assert entity2.overlaps_with(entity1)
    
    def test_no_overlap(self):
        """Test non-overlapping entities."""
        entity1 = PHIEntity(
            text="John",
            category="FirstName",
            offset=0,
            length=4,
            confidence=0.95
        )
        entity2 = PHIEntity(
            text="Smith",
            category="LastName",
            offset=5,
            length=5,
            confidence=0.95
        )
        assert not entity1.overlaps_with(entity2)


class TestMaskRegion:
    """Tests for MaskRegion dataclass."""
    
    def test_valid_mask_region(self):
        """Test creating a valid mask region."""
        bbox = BoundingBox(page=1, x=100.0, y=200.0, width=50.0, height=20.0)
        region = MaskRegion(
            page=1,
            bounding_box=bbox,
            entity_category="Person",
            confidence=0.95
        )
        assert region.page == 1
        assert region.bounding_box == bbox
        assert region.entity_category == "Person"
        assert region.confidence == 0.95
    
    def test_page_mismatch_invalid(self):
        """Test that mask region page must match bounding box page."""
        bbox = BoundingBox(page=1, x=100.0, y=200.0, width=50.0, height=20.0)
        with pytest.raises(ValueError, match="doesn't match"):
            MaskRegion(
                page=2,
                bounding_box=bbox,
                entity_category="Person",
                confidence=0.95
            )


class TestMaskingLevel:
    """Tests for MaskingLevel enum."""
    
    def test_enum_values(self):
        """Test that all masking levels are defined."""
        assert MaskingLevel.SAFE_HARBOR.value == "safe_harbor"
        assert MaskingLevel.LIMITED_DATASET.value == "limited_dataset"
        assert MaskingLevel.CUSTOM.value == "custom"


class TestDeidentificationResult:
    """Tests for DeidentificationResult dataclass."""
    
    def test_valid_success_result(self):
        """Test creating a valid success result."""
        entity = PHIEntity(
            text="John Smith",
            category="Person",
            offset=0,
            length=10,
            confidence=0.95
        )
        bbox = BoundingBox(page=1, x=100.0, y=200.0, width=50.0, height=20.0)
        region = MaskRegion(
            page=1,
            bounding_box=bbox,
            entity_category="Person",
            confidence=0.95
        )
        result = DeidentificationResult(
            status="success",
            masked_image_bytes=b"fake_tiff_data",
            pages_processed=1,
            phi_entities_count=1,
            phi_entities=[entity],
            mask_regions=[region],
            processing_time_ms=123.45,
            errors=[]
        )
        assert result.status == "success"
        assert result.pages_processed == 1
        assert result.phi_entities_count == 1
        assert len(result.errors) == 0
    
    def test_invalid_status(self):
        """Test that status must be 'success' or 'failure'."""
        with pytest.raises(ValueError, match="Status must be"):
            DeidentificationResult(
                status="pending",
                masked_image_bytes=b"",
                pages_processed=0,
                phi_entities_count=0,
                phi_entities=[],
                mask_regions=[],
                processing_time_ms=0.0,
                errors=[]
            )
    
    def test_entity_count_mismatch_invalid(self):
        """Test that phi_entities_count must match actual count."""
        with pytest.raises(ValueError, match="doesn't match actual count"):
            DeidentificationResult(
                status="success",
                masked_image_bytes=b"",
                pages_processed=0,
                phi_entities_count=5,  # Wrong count
                phi_entities=[],  # Empty list
                mask_regions=[],
                processing_time_ms=0.0,
                errors=[]
            )