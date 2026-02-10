from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List
from enum import Enum


class JobStatus(str, Enum):
    """Status of a de-identification job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class BoundingBox:
    """
    Bounding box in pixel coordinates.
    
    Represents a rectangular region on a specific page. Coordinates are
    absolute pixels from top-left origin (0,0).
    
    Attributes:
        page: 1-indexed page number
        x: Left edge in pixels
        y: Top edge in pixels
        width: Width in pixels
        height: Height in pixels
    """
    page: int
    x: float
    y: float
    width: float
    height: float
    
    def __post_init__(self):
        """Validate bounding box dimensions."""
        if self.page < 1:
            raise ValueError(f"Page must be >= 1, got {self.page}")
        if self.width < 0 or self.height < 0:
            raise ValueError(f"Width and height must be >= 0")
    
    def overlaps(self, other: 'BoundingBox') -> bool:
        """Check if this box overlaps with another box on the same page."""
        if self.page != other.page:
            return False
        
        # Check if rectangles don't overlap (easier to negate)
        if (self.x + self.width < other.x or
            other.x + other.width < self.x or
            self.y + self.height < other.y or
            other.y + other.height < self.y):
            return False
        
        return True
    
    def area(self) -> float:
        """Calculate area in square pixels."""
        return self.width * self.height


@dataclass
class OCRWord:
    """
    Single word extracted by OCR with location.
    
    Attributes:
        text: The word text
        confidence: OCR confidence score (0.0-1.0)
        bounding_box: Location of word on page
    """
    text: str
    confidence: float
    bounding_box: BoundingBox
    
    def __post_init__(self):
        """Validate confidence score."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0.0-1.0, got {self.confidence}")


@dataclass
class OCRPage:
    """
    Single page OCR results.
    
    Attributes:
        page_number: 1-indexed page number
        width: Page width in pixels
        height: Page height in pixels
        words: All words detected on this page
    """
    page_number: int
    width: float
    height: float
    words: List[OCRWord]
    
    def __post_init__(self):
        """Validate page dimensions."""
        if self.page_number < 1:
            raise ValueError(f"Page number must be >= 1, got {self.page_number}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"Page dimensions must be > 0")


@dataclass
class OCRResult:
    """
    Complete OCR results for entire document.
    
    Attributes:
        pages: List of pages in document order
        full_text: All text concatenated with spaces/newlines preserved
    """
    pages: List[OCRPage]
    full_text: str
    
    def __post_init__(self):
        """Validate OCR result."""
        if not self.pages:
            raise ValueError("OCRResult must have at least one page")
        
        # Verify page numbers are sequential
        for i, page in enumerate(self.pages, start=1):
            if page.page_number != i:
                raise ValueError(
                    f"Pages must be sequential. Expected page {i}, got {page.page_number}"
                )


@dataclass
class PHIEntity:
    """
    PHI entity detected by ML service.
    
    Attributes:
        text: The entity text as it appears in the document
        category: PHI category (Person, Date, SSN, Address, etc.)
        offset: Character offset in OCRResult.full_text
        length: Character length of entity
        confidence: Detection confidence score (0.0-1.0)
        subcategory: Optional subcategory (e.g., "FirstName", "LastName")
    """
    text: str
    category: str
    offset: int
    length: int
    confidence: float
    subcategory: Optional[str] = None
    
    def __post_init__(self):
        """Validate entity."""
        if self.offset < 0:
            raise ValueError(f"Offset must be >= 0, got {self.offset}")
        if self.length <= 0:
            raise ValueError(f"Length must be > 0, got {self.length}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0.0-1.0, got {self.confidence}")
    
    @property
    def end_offset(self) -> int:
        """Get the ending character offset (exclusive)."""
        return self.offset + self.length
    
    def overlaps_with(self, other: 'PHIEntity') -> bool:
        """Check if this entity overlaps with another entity."""
        return not (self.end_offset <= other.offset or other.end_offset <= self.offset)


@dataclass
class MaskRegion:
    """
    Region to mask in the image.
    
    Attributes:
        page: Page number to mask on
        bounding_box: Area to mask
        entity_category: PHI category being masked
        confidence: Confidence score from PHI detection
    """
    page: int
    bounding_box: BoundingBox
    entity_category: str
    confidence: float
    
    def __post_init__(self):
        """Validate mask region."""
        if self.page < 1:
            raise ValueError(f"Page must be >= 1, got {self.page}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0.0-1.0, got {self.confidence}")
        if self.bounding_box.page != self.page:
            raise ValueError(
                f"Bounding box page {self.bounding_box.page} doesn't match "
                f"mask region page {self.page}"
            )


class MaskingLevel(str, Enum):
    """
    HIPAA compliance levels for masking.
    
    SAFE_HARBOR: Mask ALL 18 HIPAA identifiers including provider names.
                 Most conservative, no data use agreement required.
    
    LIMITED_DATASET: Mask patient identifiers but keep provider names.
                     Requires data use agreement and IRB approval.
    
    CUSTOM: User-defined categories to mask via configuration.
    """
    SAFE_HARBOR = "safe_harbor"
    LIMITED_DATASET = "limited_dataset"
    CUSTOM = "custom"


@dataclass
class DeidentificationResult:
    """
    Result of document de-identification.
    
    Attributes:
        status: "success" or "failure"
        masked_image_bytes: Masked document as bytes (TIFF format)
        pages_processed: Number of pages processed
        phi_entities_count: Total PHI entities detected
        phi_entities: List of all detected PHI entities
        mask_regions: List of all mask regions applied
        processing_time_ms: Total processing time in milliseconds
        errors: List of error messages (empty if successful)
    """
    status: str
    masked_image_bytes: bytes
    pages_processed: int
    phi_entities_count: int
    phi_entities: List[PHIEntity]
    mask_regions: List[MaskRegion]
    processing_time_ms: float
    errors: List[str]
    original_format: Optional[str] = None
    output_format: Optional[str] = None
    entities_masked: Optional[int] = None
    
    def __post_init__(self):
        """Validate result."""
        if self.status not in ("success", "failure", "partial_success"):
            raise ValueError(f"Status must be 'success' or 'failure', got {self.status}")
        if self.pages_processed < 0:
            raise ValueError(f"Pages processed must be >= 0")
        if self.phi_entities_count != len(self.phi_entities):
            raise ValueError(
                f"phi_entities_count ({self.phi_entities_count}) doesn't match "
                f"actual count ({len(self.phi_entities)})"
            )