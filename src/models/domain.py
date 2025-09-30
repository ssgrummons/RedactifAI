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
    """Bounding box coordinates for PHI on a page."""
    page: int
    x: float
    y: float
    width: float
    height: float


@dataclass
class PHIEntity:
    """Detected PHI entity with location information."""
    category: str
    text: str
    confidence: float
    bounding_box: BoundingBox


@dataclass
class DeidentificationResult:
    """Result of document de-identification."""
    status: str  # "success" or "failure"
    masked_tiff_bytes: Optional[bytes]
    pages_processed: int
    phi_entities_count: int
    phi_entities: List[PHIEntity]
    processing_time_ms: float
    errors: List[str] = field(default_factory=list)