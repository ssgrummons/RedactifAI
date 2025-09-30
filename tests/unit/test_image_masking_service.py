"""
Unit tests for ImageMaskingService.
"""

import pytest
from PIL import Image

from src.services.image_masking_service import ImageMaskingService
from src.models.domain import MaskRegion, BoundingBox


class TestImageMaskingService:
    """Tests for image masking functionality."""
    
    def create_test_image(self, width: int = 800, height: int = 600) -> Image.Image:
        """Helper to create a test image."""
        # Create white image with some colored regions
        img = Image.new('RGB', (width, height), color=(255, 255, 255))
        pixels = img.load()
        
        # Add colored rectangle (to test that it gets masked)
        for x in range(100, 200):
            for y in range(100, 150):
                pixels[x, y] = (255, 0, 0)  # Red
        
        return img
    
    def test_single_mask_application(self):
        """Test applying a single mask to an image."""
        img = self.create_test_image()
        
        # Create mask region over the red rectangle
        mask_region = MaskRegion(
            page=1,
            bounding_box=BoundingBox(page=1, x=100, y=100, width=100, height=50),
            entity_category="Person",
            confidence=0.95
        )
        
        service = ImageMaskingService()
        masked_images = service.apply_masks([img], [mask_region])
        
        assert len(masked_images) == 1
        
        # Verify original is unchanged
        original_pixel = img.getpixel((150, 125))
        assert original_pixel == (255, 0, 0)  # Still red
        
        # Verify masked image has black rectangle
        masked_pixel = masked_images[0].getpixel((150, 125))
        assert masked_pixel == (0, 0, 0)  # Now black
        
        # Verify area outside mask is unchanged
        outside_pixel = masked_images[0].getpixel((50, 50))
        assert outside_pixel == (255, 255, 255)  # Still white
    
    def test_multiple_masks_same_page(self):
        """Test applying multiple masks to the same page."""
        img = self.create_test_image()
        
        mask_regions = [
            MaskRegion(
                page=1,
                bounding_box=BoundingBox(page=1, x=100, y=100, width=50, height=30),
                entity_category="Person",
                confidence=0.95
            ),
            MaskRegion(
                page=1,
                bounding_box=BoundingBox(page=1, x=200, y=200, width=60, height=40),
                entity_category="Date",
                confidence=0.98
            ),
        ]
        
        service = ImageMaskingService()
        masked_images = service.apply_masks([img], mask_regions)
        
        assert len(masked_images) == 1
        
        # Both regions should be masked
        assert masked_images[0].getpixel((125, 115)) == (0, 0, 0)
        assert masked_images[0].getpixel((225, 220)) == (0, 0, 0)
    
    def test_multi_page_masking(self):
        """Test masking across multiple pages."""
        img1 = self.create_test_image()
        img2 = self.create_test_image()
        
        mask_regions = [
            MaskRegion(
                page=1,
                bounding_box=BoundingBox(page=1, x=100, y=100, width=50, height=30),
                entity_category="Person",
                confidence=0.95
            ),
            MaskRegion(
                page=2,
                bounding_box=BoundingBox(page=2, x=200, y=200, width=60, height=40),
                entity_category="Date",
                confidence=0.98
            ),
        ]
        
        service = ImageMaskingService()
        masked_images = service.apply_masks([img1, img2], mask_regions)
        
        assert len(masked_images) == 2
        
        # Page 1 should have mask at (100, 100)
        assert masked_images[0].getpixel((125, 115)) == (0, 0, 0)
        
        # Page 2 should have mask at (200, 200)
        assert masked_images[1].getpixel((225, 220)) == (0, 0, 0)
    
    def test_no_masks(self):
        """Test that images are copied when no masks applied."""
        img = self.create_test_image()
        
        service = ImageMaskingService()
        masked_images = service.apply_masks([img], [])
        
        assert len(masked_images) == 1
        
        # Image should be unchanged
        assert masked_images[0].getpixel((150, 125)) == (255, 0, 0)
        
        # But should be a copy, not the same object
        assert masked_images[0] is not img
    
    def test_page_with_no_masks(self):
        """Test pages without masks are copied unchanged."""
        img1 = self.create_test_image()
        img2 = self.create_test_image()
        
        # Only mask page 1
        mask_region = MaskRegion(
            page=1,
            bounding_box=BoundingBox(page=1, x=100, y=100, width=50, height=30),
            entity_category="Person",
            confidence=0.95
        )
        
        service = ImageMaskingService()
        masked_images = service.apply_masks([img1, img2], [mask_region])
        
        # Page 1 should be masked
        assert masked_images[0].getpixel((125, 115)) == (0, 0, 0)
        
        # Page 2 should be unchanged
        assert masked_images[1].getpixel((150, 125)) == (255, 0, 0)
    
    def test_custom_mask_color(self):
        """Test using a custom mask color."""
        img = self.create_test_image()
        
        mask_region = MaskRegion(
            page=1,
            bounding_box=BoundingBox(page=1, x=100, y=100, width=50, height=30),
            entity_category="Person",
            confidence=0.95
        )
        
        # Use blue masks instead of black
        service = ImageMaskingService(mask_color=(0, 0, 255))
        masked_images = service.apply_masks([img], [mask_region])
        
        # Masked area should be blue
        assert masked_images[0].getpixel((125, 115)) == (0, 0, 255)
    
    def test_overlapping_masks(self):
        """Test that overlapping masks work correctly."""
        img = self.create_test_image()
        
        mask_regions = [
            MaskRegion(
                page=1,
                bounding_box=BoundingBox(page=1, x=100, y=100, width=100, height=50),
                entity_category="Person",
                confidence=0.95
            ),
            MaskRegion(
                page=1,
                bounding_box=BoundingBox(page=1, x=150, y=120, width=80, height=40),
                entity_category="Date",
                confidence=0.98
            ),
        ]
        
        service = ImageMaskingService()
        masked_images = service.apply_masks([img], mask_regions)
        
        # Overlapping area should be black
        assert masked_images[0].getpixel((170, 130)) == (0, 0, 0)
    
    def test_empty_image_list_raises_error(self):
        """Test that empty image list raises an error."""
        service = ImageMaskingService()
        
        with pytest.raises(ValueError, match="Cannot mask empty image list"):
            service.apply_masks([], [])
    
    def test_debug_mode_warning(self, caplog):
        """Test that debug mode logs a warning."""
        import logging
        caplog.set_level(logging.WARNING)
        
        service = ImageMaskingService(debug_mode=True)
        
        assert "DEBUG MODE" in caplog.text
        assert "DO NOT use for production" in caplog.text
    
    def test_debug_mode_uses_colored_masks(self):
        """Test that debug mode creates colored semi-transparent masks."""
        img = self.create_test_image()
        
        mask_region = MaskRegion(
            page=1,
            bounding_box=BoundingBox(page=1, x=100, y=100, width=50, height=30),
            entity_category="Person",
            confidence=0.95
        )
        
        service = ImageMaskingService(debug_mode=True)
        masked_images = service.apply_masks([img], [mask_region])
        
        # In debug mode, masks should be colored (not pure black)
        masked_pixel = masked_images[0].getpixel((125, 115))
        # Should not be pure black or pure white
        assert masked_pixel != (0, 0, 0)
        assert masked_pixel != (255, 255, 255)
