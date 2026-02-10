"""
Image masking service for redacting PHI from document images.

Draws solid black rectangles over bounding boxes to obscure sensitive information.
"""

import logging
from typing import List
from PIL import Image, ImageDraw

from src.models.domain import MaskRegion

logger = logging.getLogger(__name__)


class ImageMaskingService:
    """
    Service for applying mask regions to document images.
    
    Draws solid black rectangles over specified bounding boxes
    to redact PHI from scanned medical records.
    """
    
    def __init__(
        self,
        mask_color: tuple[int, int, int] = (0, 0, 0),
        debug_mode: bool = False,
    ):
        """
        Initialize image masking service.
        
        Args:
            mask_color: RGB color for masks (default: black)
            debug_mode: If True, use semi-transparent masks and colored borders
                       for debugging. DO NOT use in production.
        """
        self.mask_color = mask_color
        self.debug_mode = debug_mode
        
        if debug_mode:
            logger.warning(
                "ImageMaskingService initialized in DEBUG MODE. "
                "Masks will be semi-transparent. DO NOT use for production."
            )
    
    def apply_masks(
        self,
        images: List[Image.Image],
        mask_regions: List[MaskRegion],
    ) -> List[Image.Image]:
        """
        Apply mask regions to images.
        
        Processes sequentially for stability with large documents.
        
        Args:
            images: List of PIL Images (one per page)
            mask_regions: List of mask regions to apply
            
        Returns:
            List of masked images (new copies, originals unchanged)
        """
        if not images:
            raise ValueError("Cannot mask empty image list")
        
        if not mask_regions:
            logger.info("No mask regions to apply")
            return [img.copy() for img in images]
        
        logger.info(f"Applying {len(mask_regions)} masks to {len(images)} pages (sequential)")
        
        # Convert all images to RGB for consistent color handling
        images = [img.convert('RGB') if img.mode != 'RGB' else img for img in images]
        
        # Group mask regions by page
        regions_by_page = self._group_by_page(mask_regions)
        
        # Mask each page sequentially
        masked_images = []
        for page_num, img in enumerate(images, start=1):
            page_regions = regions_by_page.get(page_num, [])
            
            if page_regions:
                masked_img = self._mask_page(img, page_regions)
                
                # Log progress for large documents
                if len(images) > 50 and page_num % 50 == 0:
                    logger.info(f"  Masked {page_num}/{len(images)} pages")
            else:
                # No masks for this page, just copy
                masked_img = img.copy()
            
            masked_images.append(masked_img)
        
        total_masks = len(mask_regions)
        logger.info(f"Applied {total_masks} masks across {len(images)} pages")
        
        return masked_images
    
    def _mask_page(
        self,
        img: Image.Image,
        mask_regions: List[MaskRegion],
    ) -> Image.Image:
        """
        Apply masks to a single page.
        
        Args:
            img: Page image
            mask_regions: Mask regions for this page
            
        Returns:
            Masked image (new copy)
        """
        # Create copy to avoid modifying original
        masked_img = img.copy()
        
        # Create drawing context
        if self.debug_mode and masked_img.mode != 'RGBA':
            masked_img = masked_img.convert('RGBA')
        elif not self.debug_mode and masked_img.mode != 'RGB':
            masked_img = masked_img.convert('RGB')

        draw = ImageDraw.Draw(masked_img)
        
        for region in mask_regions:
            bbox = region.bounding_box
            
            # Calculate rectangle coordinates
            x1 = bbox.x
            y1 = bbox.y
            x2 = bbox.x + bbox.width
            y2 = bbox.y + bbox.height
            
            if self.debug_mode:
                # Debug mode: semi-transparent colored rectangles
                self._draw_debug_mask(draw, x1, y1, x2, y2, region)
            else:
                # Production: solid black rectangle
                draw.rectangle(
                    [(x1, y1), (x2, y2)],
                    fill=self.mask_color,
                    outline=None,
                )
        
        return masked_img
    
    def _draw_debug_mask(
        self,
        draw: ImageDraw.ImageDraw,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        region: MaskRegion,
    ):
        """
        Draw debug mask with colored border and label.
        
        Used for debugging/development only - shows what's being masked
        and the PHI category.
        """
        # Color by category for easier debugging
        category_colors = {
            'Person': (255, 0, 0, 128),      # Red
            'Date': (0, 255, 0, 128),        # Green
            'PhoneNumber': (0, 0, 255, 128), # Blue
            'Email': (255, 255, 0, 128),     # Yellow
            'SSN': (255, 0, 255, 128),       # Magenta
            'Address': (0, 255, 255, 128),   # Cyan
        }
        
        fill_color = category_colors.get(
            region.entity_category,
            (128, 128, 128, 128)  # Gray default
        )
        
        # Semi-transparent fill
        draw.rectangle(
            [(x1, y1), (x2, y2)],
            fill=fill_color,
            outline=(255, 0, 0),  # Red border
            width=2,
        )
        
        # Add text label (category)
        try:
            draw.text(
                (x1 + 5, y1 + 5),
                region.entity_category[:3].upper(),
                fill=(255, 255, 255),
            )
        except Exception:
            # Text drawing might fail if font not available
            pass
    
    def _group_by_page(
        self,
        mask_regions: List[MaskRegion],
    ) -> dict[int, List[MaskRegion]]:
        """
        Group mask regions by page number.
        
        Args:
            mask_regions: List of mask regions
            
        Returns:
            Dictionary mapping page number to list of regions on that page
        """
        by_page: dict[int, List[MaskRegion]] = {}
        
        for region in mask_regions:
            page = region.page
            if page not in by_page:
                by_page[page] = []
            by_page[page].append(region)
        
        return by_page