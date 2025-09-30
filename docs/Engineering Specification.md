# RedactifAI - Revised Engineering Specification

**Make it so. (Version 2.0 - Core Logic First)**

---

## Executive Summary

**What Changed:** Original spec assumed Azure Document Intelligence had built-in PII detection. **It doesn't.** OCR and PHI detection are separate services. This spec reflects that reality and focuses on the **critical 16-hour path**: building the entity-to-bounding-box matching logic that makes this project valuable.

**The Core Challenge:** Converting "Samuel Grummons had a vasectomy" → "█████████████████ had a vasectomy" requires:
1. OCR service: Extract "Samuel Grummons" with pixel coordinates
2. PHI detection service: Identify "Samuel Grummons" as a Person entity at character offset 0-15
3. **Entity matching (THE HARD PART)**: Map character offset 0-15 back to pixel coordinates
4. Image masking: Draw black rectangle over those pixels

**This spec prioritizes building #3 first**, with mocks for everything else. Once that works, adding real services is straightforward.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         API Layer (FastAPI)                     │
│  POST /jobs          - Submit document for processing           │
│  GET  /jobs/{id}     - Get job status                          │
│  GET  /jobs/{id}/result - Download masked document             │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Celery Worker Process                        │
│  1. Download document from storage                             │
│  2. Split into pages (ImageProcessor)                          │
│  3. OCR each page → text + bounding boxes                      │
│  4. Detect PHI entities → character offsets                    │
│  5. Match entities to bounding boxes (CORE LOGIC)              │
│  6. Mask bounding boxes                                        │
│  7. Reassemble and upload                                      │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ↓
┌─────────────────────────────────────────────────────────────────┐
│              DeidentificationService (Orchestrator)             │
└─────────┬──────────────┬──────────────┬──────────────┬─────────┘
          │              │              │              │
          ↓              ↓              ↓              ↓
    ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
    │   OCR    │   │   PHI    │   │  Entity  │   │  Image   │
    │ Service  │   │Detection │   │ Matcher  │   │ Masking  │
    │(Abstract)│   │ Service  │   │  (Core)  │   │ Service  │
    │          │   │(Abstract)│   │          │   │          │
    └──────────┘   └──────────┘   └──────────┘   └──────────┘
         │              │
         ↓              ↓
    Azure/AWS      Azure/AWS
    Textract       Language
```

**Key Design Principles:**
1. **Cloud-agnostic:** OCR and PHI services are abstracted
2. **Mock-first:** Build with mocks, add real services later
3. **Core logic first:** EntityMatcher is the critical path
4. **HIPAA-compliant:** Configurable masking levels

---

## Critical Path: Entity-to-Bounding-Box Matching

This is the **16-hour priority**. Everything else can be mocked.

### Problem Statement

**Input 1 - OCR Results:**
```python
OCRResult(
    pages=[
        OCRPage(
            page_number=1,
            width=2550.0,  # pixels
            height=3300.0,
            words=[
                OCRWord(text="Samuel", confidence=0.99, 
                       bounding_box=BoundingBox(page=1, x=145, y=220, width=85, height=24)),
                OCRWord(text="Grummons", confidence=0.98,
                       bounding_box=BoundingBox(page=1, x=235, y=220, width=110, height=24)),
                OCRWord(text="had", confidence=0.99,
                       bounding_box=BoundingBox(page=1, x=350, y=220, width=40, height=24)),
                # ... more words
            ]
        )
    ],
    full_text="Samuel Grummons had a vasectomy on 03/15/2023..."
)
```

**Input 2 - PHI Entities:**
```python
phi_entities = [
    PHIEntity(
        text="Samuel Grummons",
        category="Person",
        offset=0,        # Character offset in full_text
        length=15,
        confidence=0.95
    ),
    PHIEntity(
        text="03/15/2023",
        category="Date",
        offset=32,
        length=10,
        confidence=0.98
    )
]
```

**Output - Mask Regions:**
```python
mask_regions = [
    MaskRegion(
        page=1,
        bounding_box=BoundingBox(page=1, x=145, y=220, width=195, height=24),
        entity_category="Person",
        confidence=0.95
    ),
    MaskRegion(
        page=1,
        bounding_box=BoundingBox(page=1, x=420, y=220, width=120, height=24),
        entity_category="Date",
        confidence=0.98
    )
]
```

### Core Algorithm

```python
class EntityMatcher:
    """
    Maps PHI entities (character offsets) to OCR word bounding boxes.
    
    This is the core value proposition of RedactifAI.
    """
    
    def match_entities_to_boxes(
        self, 
        ocr_result: OCRResult, 
        phi_entities: List[PHIEntity]
    ) -> List[MaskRegion]:
        """
        Match PHI entities to bounding boxes for masking.
        
        Algorithm:
        1. Build character offset index from OCR words
        2. For each PHI entity, find overlapping OCR words
        3. Merge their bounding boxes into a single mask region
        4. Handle edge cases (OCR errors, multi-line text, page boundaries)
        """
        offset_map = self._build_offset_map(ocr_result)
        mask_regions = []
        
        for entity in phi_entities:
            overlapping_words = self._find_overlapping_words(
                entity, offset_map
            )
            
            if overlapping_words:
                merged_box = self._merge_bounding_boxes(overlapping_words)
                mask_regions.append(MaskRegion(
                    page=overlapping_words[0].page,
                    bounding_box=merged_box,
                    entity_category=entity.category,
                    confidence=entity.confidence
                ))
            else:
                # Entity not found in OCR - log warning
                logger.warning(
                    f"Could not match entity '{entity.text}' to OCR words"
                )
        
        return mask_regions
    
    def _build_offset_map(self, ocr_result: OCRResult) -> List[WordOffset]:
        """
        Build index mapping character offsets to OCR words.
        
        Handles:
        - Space normalization (OCR might have extra/missing spaces)
        - Line breaks
        - Page boundaries
        """
        # Implementation details below
    
    def _find_overlapping_words(
        self, 
        entity: PHIEntity, 
        offset_map: List[WordOffset]
    ) -> List[WordOffset]:
        """
        Find OCR words that overlap with entity character range.
        
        Uses fuzzy matching if exact match fails (handles OCR errors).
        """
        # Implementation details below
    
    def _merge_bounding_boxes(
        self, 
        words: List[WordOffset]
    ) -> BoundingBox:
        """
        Merge multiple word boxes into single bounding box.
        
        Takes min(x, y) and max(x+width, y+height) across all words.
        """
        # Implementation details below
```

### Edge Cases to Handle

| Edge Case | Example | Solution |
|-----------|---------|----------|
| **OCR errors** | Entity: "Samuel", OCR: "5amuel" | Fuzzy string matching (Levenshtein distance ≤ 2) |
| **Multi-line entities** | Address spanning 2 lines | Track line breaks in offset calculation |
| **Page boundaries** | Entity spans pages | Split into multiple mask regions |
| **Overlapping entities** | "Dr. Smith" (Person) + "Dr." (Title) | Merge overlapping regions or keep larger one |
| **Whitespace mismatch** | Entity: "John  Smith" (2 spaces), OCR: "John Smith" (1 space) | Normalize whitespace when building offset map |
| **Missing entities** | PHI service found it, but OCR missed the word | Log warning, skip masking (or expand search radius) |
| **Confidence threshold** | Low-confidence entity | Only mask if confidence > threshold (configurable) |

---

## Domain Models

### Core Data Structures

```python
# src/models/domain.py

from dataclasses import dataclass
from typing import List, Optional
from enum import Enum


@dataclass
class BoundingBox:
    """
    Bounding box in pixel coordinates.
    Normalized to page dimensions (0-1 relative coordinates optional).
    """
    page: int
    x: float      # Left edge (pixels)
    y: float      # Top edge (pixels)
    width: float  # Width (pixels)
    height: float # Height (pixels)


@dataclass
class OCRWord:
    """Single word extracted by OCR with location."""
    text: str
    confidence: float
    bounding_box: BoundingBox


@dataclass
class OCRLine:
    """Line of text with constituent words."""
    text: str
    words: List[OCRWord]
    bounding_box: BoundingBox


@dataclass
class OCRPage:
    """Single page OCR results."""
    page_number: int
    width: float   # Page width in pixels
    height: float  # Page height in pixels
    lines: List[OCRLine]
    words: List[OCRWord]


@dataclass
class OCRResult:
    """Complete OCR results for entire document."""
    pages: List[OCRPage]
    full_text: str  # All text concatenated with spaces/newlines


@dataclass
class PHIEntity:
    """PHI entity detected by ML service."""
    text: str
    category: str           # Person, Date, SSN, Address, etc.
    offset: int             # Character offset in full_text
    length: int             # Character length
    confidence: float       # 0.0-1.0
    subcategory: Optional[str] = None  # e.g., "FirstName", "LastName"


@dataclass
class MaskRegion:
    """Region to mask in the image."""
    page: int
    bounding_box: BoundingBox
    entity_category: str
    confidence: float


class MaskingLevel(str, Enum):
    """HIPAA compliance levels for masking."""
    SAFE_HARBOR = "safe_harbor"         # Mask ALL identifiers (18 HIPAA categories)
    LIMITED_DATASET = "limited_dataset" # Mask patient identifiers, keep provider names
    CUSTOM = "custom"                   # User-defined categories to mask


@dataclass
class DeidentificationResult:
    """Result of document de-identification."""
    status: str  # "success" or "failure"
    masked_image_bytes: bytes
    pages_processed: int
    phi_entities_count: int
    phi_entities: List[PHIEntity]
    mask_regions: List[MaskRegion]
    processing_time_ms: float
    errors: List[str]
```

---

## Service Abstractions

### OCR Service Interface

```python
# src/services/ocr_service.py

from abc import ABC, abstractmethod
from src.models.domain import OCRResult


class OCRService(ABC):
    """Abstract base class for OCR providers."""
    
    @abstractmethod
    async def analyze_document(
        self, 
        document_bytes: bytes,
        file_format: str = "tiff"
    ) -> OCRResult:
        """
        Extract text and bounding boxes from document.
        
        Args:
            document_bytes: Raw document bytes
            file_format: Document format (tiff, pdf, png, etc.)
            
        Returns:
            OCRResult with normalized structure
            
        Raises:
            OCRServiceError: If OCR fails
        """
        pass
```

**Implementations:**
- `MockOCRService` - Returns fake but realistic data for testing
- `AzureDocumentIntelligenceOCR` - Real Azure implementation
- `AWSTextractOCR` - Real AWS implementation (future)

### PHI Detection Service Interface

```python
# src/services/phi_detection_service.py

from abc import ABC, abstractmethod
from typing import List
from src.models.domain import PHIEntity


class PHIDetectionService(ABC):
    """Abstract base class for PHI/PII detection providers."""
    
    @abstractmethod
    async def detect_phi(
        self, 
        text: str,
        masking_level: MaskingLevel = MaskingLevel.SAFE_HARBOR
    ) -> List[PHIEntity]:
        """
        Detect PHI entities in text using ML.
        
        Args:
            text: Full text to analyze
            masking_level: Which entities to detect based on compliance level
            
        Returns:
            List of PHIEntity with character offsets
            
        Raises:
            PHIDetectionError: If detection fails
        """
        pass
```

**Implementations:**
- `MockPHIDetectionService` - Returns fake entities for testing
- `AzureLanguagePHIService` - Real Azure Language PII detection
- `AWSComprehendMedicalService` - Real AWS Comprehend Medical (future)
- `LocalNERService` - spaCy/Hugging Face models (future)

---

## HIPAA Safe Harbor Compliance

### 18 Identifiers to Remove

| # | Identifier | PHI Category | Example | Regex Supplement? |
|---|-----------|--------------|---------|-------------------|
| 1 | Names | Person, PersonName | "John Smith", "Dr. Jones" | No - use ML |
| 2 | Geographic subdivisions < state | Address, Location | "123 Main St, Boston" | No - use ML |
| 3 | Dates (except year) | Date, DateTime | "03/15/2023" | Yes - catch formatted dates |
| 4 | Phone/Fax | PhoneNumber | "(617) 555-1234" | Yes - regex for formats |
| 5 | Email | Email | "patient@example.com" | Yes - regex |
| 6 | SSN | SSN, NationalID | "123-45-6789" | Yes - regex |
| 7 | Medical record number | MedicalRecordNumber | "MRN: 12345678" | Yes - institution-specific |
| 8 | Health plan number | InsuranceID | "Member ID: ABC123456" | Yes - institution-specific |
| 9 | Account number | AccountNumber | "Acct: 987654" | Yes - institution-specific |
| 10 | Certificate/license number | LicenseNumber | "License: D12345" | Yes - regex |
| 11 | Vehicle identifiers | VehicleID | "License plate: 1ABC234" | Yes - regex |
| 12 | Device identifiers | DeviceID | "Serial: XYZ789" | Maybe - depends on format |
| 13 | URLs | URL | "http://example.com" | Yes - regex |
| 14 | IP addresses | IPAddress | "192.168.1.1" | Yes - regex |
| 15 | Biometric identifiers | Biometric | Fingerprints, voice prints | N/A for text |
| 16 | Full-face photos | Photo | N/A | N/A for text |
| 17 | Any other unique ID | CustomID | Institution-specific | Yes - configurable |
| 18 | Other identifying info | Various | Context-dependent | No - use ML |

**Implementation Strategy:**
1. **ML-based (Azure/AWS):** Names, addresses, dates, phone, email, SSN
2. **Regex supplement:** Institution-specific IDs (MRN, account, insurance)
3. **Configurable:** Load custom patterns from `phi_patterns.yaml`

### Masking Levels

```python
# Configuration via environment variable
MASKING_LEVEL=safe_harbor  # or limited_dataset or custom

# Behavior:
# safe_harbor: Mask ALL 18 identifiers including provider names
#   "Samuel Grummons saw Dr. Smith" → "█████████████████ saw █████████"
#
# limited_dataset: Mask patient identifiers, keep provider names
#   "Samuel Grummons saw Dr. Smith" → "█████████████████ saw Dr. Smith"
#   Requires data use agreement and IRB approval
#
# custom: Mask only specified categories (from config)
#   PHI_CATEGORIES=Person,SSN,Date
```

---

## Implementation Plan (16-Hour Critical Path)

### Phase 1: Data Models & EntityMatcher Core (4 hours)

**Deliverable:** Working entity-to-bbox matching with unit tests

**Files:**
- `src/models/domain.py` - All dataclasses
- `src/services/entity_matcher.py` - Core matching logic
- `tests/unit/test_entity_matcher.py` - Comprehensive tests

**Tasks:**
1. Define all domain models (30 min)
2. Implement `_build_offset_map()` (1 hour)
3. Implement `_find_overlapping_words()` with exact matching (1 hour)
4. Implement `_merge_bounding_boxes()` (30 min)
5. Write unit tests with clean data (1 hour)

**Success Criteria:**
- Can map "Samuel Grummons" (offset 0-15) to merged bounding box
- Handles multi-word entities
- Tests pass with 90%+ coverage

### Phase 2: Edge Case Handling (4 hours)

**Deliverable:** Robust matching that handles real-world messiness

**Tasks:**
1. Add fuzzy string matching for OCR errors (1.5 hours)
   - Use `python-Levenshtein` library
   - If exact match fails, try Levenshtein distance ≤ 2
2. Handle whitespace normalization (1 hour)
   - Normalize spaces when building offset map
   - Test with documents that have irregular spacing
3. Handle multi-line entities (1 hour)
   - Track line breaks in offset calculation
   - Test with addresses spanning multiple lines
4. Handle page boundaries (30 min)
   - Split entities that span pages
   - Create separate mask regions per page

**Success Criteria:**
- Handles OCR errors (S→5, O→0, etc.)
- Works with inconsistent whitespace
- Correctly masks multi-line addresses
- Tests cover all edge cases

### Phase 3: Mock Services (3 hours)

**Deliverable:** Fake OCR and PHI services that produce realistic test data

**Files:**
- `src/services/mock_ocr_service.py`
- `src/services/mock_phi_detection_service.py`
- `tests/integration/test_mocked_pipeline.py`

**Tasks:**
1. Implement `MockOCRService` (1.5 hours)
   - Load sample text
   - Generate realistic word bounding boxes
   - Add some OCR errors (character swaps)
2. Implement `MockPHIDetectionService` (1 hour)
   - Use simple regex to find names, dates, SSNs
   - Return as PHIEntity with offsets
3. Integration test: Full pipeline with mocks (30 min)
   - Mock OCR → Mock PHI → EntityMatcher → verify output

**Success Criteria:**
- Can run full de-identification pipeline without real services
- Mock data is realistic enough to catch bugs
- Integration tests pass

### Phase 4: Image Masking & Pipeline (3 hours)

**Deliverable:** End-to-end working system with mocks

**Files:**
- `src/services/image_masking_service.py`
- `src/utils/image_processor.py`
- `src/services/deidentification_service.py`

**Tasks:**
1. Implement `ImageProcessor` (1 hour)
   - Load TIFF with Pillow
   - Split into pages
   - Reassemble masked pages
2. Implement `ImageMaskingService` (1 hour)
   - Take PIL Image + MaskRegion list
   - Draw black rectangles
   - Optional: Add padding around boxes
3. Implement `DeidentificationService` orchestrator (1 hour)
   - Wire everything together
   - Error handling and logging

**Success Criteria:**
- Can load sample TIFF, mask PHI, save result
- Visual inspection shows correct masking
- End-to-end test passes

### Phase 5: Configuration & Testing (2 hours)

**Deliverable:** Configurable, production-ready core logic

**Tasks:**
1. Add configuration system (30 min)
   - MASKING_LEVEL setting
   - CONFIDENCE_THRESHOLD setting
   - PHI_CATEGORIES for custom mode
2. Add comprehensive integration tests (1 hour)
   - Test different masking levels
   - Test confidence thresholds
   - Test with complex multi-page documents
3. Performance testing (30 min)
   - Profile with 50-page document
   - Ensure acceptable speed (<2s per page)

**Success Criteria:**
- All tests pass
- Configuration works as expected
- Performance is acceptable

---

## Real Service Integration (Post-16 Hours)

Once core logic works, adding real services is straightforward:

### Azure Document Intelligence OCR

```python
# src/services/azure_ocr_service.py

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential


class AzureDocumentIntelligenceOCR(OCRService):
    def __init__(self):
        self.client = DocumentAnalysisClient(
            endpoint=settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT,
            credential=AzureKeyCredential(settings.AZURE_DOCUMENT_INTELLIGENCE_KEY)
        )
    
    async def analyze_document(
        self, 
        document_bytes: bytes,
        file_format: str = "tiff"
    ) -> OCRResult:
        # Use prebuilt-read model for OCR
        poller = self.client.begin_analyze_document(
            model_id="prebuilt-read",
            document=document_bytes
        )
        result = poller.result()
        
        # Convert Azure format to OCRResult
        return self._convert_azure_result(result)
    
    def _convert_azure_result(self, azure_result) -> OCRResult:
        """Convert Azure's response to normalized OCRResult."""
        pages = []
        for page in azure_result.pages:
            words = []
            for word in page.words:
                # Azure returns polygon, convert to bounding box
                bbox = self._polygon_to_bbox(word.polygon, page.page_number)
                words.append(OCRWord(
                    text=word.content,
                    confidence=word.confidence,
                    bounding_box=bbox
                ))
            
            pages.append(OCRPage(
                page_number=page.page_number,
                width=page.width,
                height=page.height,
                words=words,
                lines=[...]  # Similar conversion
            ))
        
        return OCRResult(
            pages=pages,
            full_text=azure_result.content
        )
    
    def _polygon_to_bbox(self, polygon, page) -> BoundingBox:
        """Convert Azure polygon (8 coordinates) to bounding box."""
        xs = [polygon[i] for i in range(0, len(polygon), 2)]
        ys = [polygon[i] for i in range(1, len(polygon), 2)]
        return BoundingBox(
            page=page,
            x=min(xs),
            y=min(ys),
            width=max(xs) - min(xs),
            height=max(ys) - min(ys)
        )
```

### Azure Language PII Detection

```python
# src/services/azure_phi_detection_service.py

from azure.ai.textanalytics import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential


class AzureLanguagePHIService(PHIDetectionService):
    def __init__(self):
        self.client = TextAnalyticsClient(
            endpoint=settings.AZURE_LANGUAGE_ENDPOINT,
            credential=AzureKeyCredential(settings.AZURE_LANGUAGE_KEY)
        )
    
    async def detect_phi(
        self, 
        text: str,
        masking_level: MaskingLevel = MaskingLevel.SAFE_HARBOR
    ) -> List[PHIEntity]:
        # Call Azure PII detection
        response = self.client.recognize_pii_entities(
            documents=[text],
            domain="phi"  # Healthcare-specific PII
        )
        
        entities = []
        for doc in response:
            for entity in doc.entities:
                # Filter based on masking level
                if self._should_mask_category(entity.category, masking_level):
                    entities.append(PHIEntity(
                        text=entity.text,
                        category=entity.category,
                        offset=entity.offset,
                        length=entity.length,
                        confidence=entity.confidence_score,
                        subcategory=entity.subcategory
                    ))
        
        return entities
    
    def _should_mask_category(self, category: str, level: MaskingLevel) -> bool:
        """Determine if category should be masked based on HIPAA level."""
        if level == MaskingLevel.SAFE_HARBOR:
            return True  # Mask everything
        elif level == MaskingLevel.LIMITED_DATASET:
            # Don't mask provider names
            return category not in ["HealthcareProfessional", "Organization"]
        else:
            # Custom level - check config
            return category in settings.PHI_CATEGORIES
```

---

## Testing Strategy

### Unit Tests (Mock Everything)

```python
# tests/unit/test_entity_matcher.py

def test_simple_entity_matching():
    """Test matching single-word entity to bounding box."""
    ocr_result = OCRResult(
        pages=[OCRPage(
            page_number=1,
            width=1000, height=1000,
            words=[
                OCRWord(text="John", confidence=0.99, 
                       bounding_box=BoundingBox(1, 100, 200, 50, 20)),
                OCRWord(text="Smith", confidence=0.99,
                       bounding_box=BoundingBox(1, 155, 200, 60, 20))
            ]
        )],
        full_text="John Smith"
    )
    
    entities = [
        PHIEntity(text="John Smith", category="Person", 
                 offset=0, length=10, confidence=0.95)
    ]
    
    matcher = EntityMatcher()
    mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
    
    assert len(mask_regions) == 1
    assert mask_regions[0].page == 1
    # Should merge both word boxes
    assert mask_regions[0].bounding_box.x == 100
    assert mask_regions[0].bounding_box.width == 115  # 155+60-100


def test_ocr_error_fuzzy_matching():
    """Test fuzzy matching when OCR misreads character."""
    ocr_result = OCRResult(
        pages=[OCRPage(
            page_number=1,
            words=[
                OCRWord(text="5amuel", confidence=0.85,  # S→5 error
                       bounding_box=BoundingBox(1, 100, 200, 70, 20))
            ]
        )],
        full_text="5amuel"
    )
    
    entities = [
        PHIEntity(text="Samuel", category="Person",
                 offset=0, length=6, confidence=0.95)
    ]
    
    matcher = EntityMatcher()
    mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
    
    # Should still match despite OCR error
    assert len(mask_regions) == 1
    assert mask_regions[0].entity_category == "Person"
```

### Integration Tests (With Mocks)

```python
# tests/integration/test_mocked_pipeline.py

async def test_full_deidentification_pipeline():
    """Test complete pipeline with mock services."""
    # Load sample TIFF
    with open("tests/fixtures/sample_medical_record.tiff", "rb") as f:
        tiff_bytes = f.read()
    
    # Use mock services
    ocr_service = MockOCRService()
    phi_service = MockPHIDetectionService()
    entity_matcher = EntityMatcher()
    masking_service = ImageMaskingService()
    
    # Run pipeline
    service = DeidentificationService(
        ocr_service=ocr_service,
        phi_detection_service=phi_service,
        entity_matcher=entity_matcher,
        image_masking_service=masking_service
    )
    
    result = await service.deidentify_document("job-123", tiff_bytes)
    
    assert result.status == "success"
    assert result.pages_processed > 0
    assert result.phi_entities_count > 0
    assert len(result.masked_image_bytes) > 0
    
    # Save for visual inspection
    with open("tests/output/masked_sample.tiff", "wb") as f:
        f.write(result.masked_image_bytes)
```

---

## Configuration

### Environment Variables

```bash
# Core Settings
MASKING_LEVEL=safe_harbor  # safe_harbor | limited_dataset | custom
CONFIDENCE_THRESHOLD=0.80  # Only mask entities above this confidence
PHI_CATEGORIES=Person,Date,SSN,PhoneNumber  # For custom mode

# Azure Document Intelligence (OCR)
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://xxx.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=xxx

# Azure Language (PII Detection)
AZURE_LANGUAGE_ENDPOINT=https://xxx.cognitiveservices.azure.com/
AZURE_LANGUAGE_KEY=xxx

# Processing
MAX_FILE_SIZE_MB=50
MASKING_PADDING_PX=5  # Extra padding around masked regions
```

### Custom PHI Patterns (Optional)

```yaml
# src/config/phi_patterns.yaml

# Supplement ML-based detection with regex for institution-specific IDs
patterns:
  - name: MRN
    regex: '\b(?:MRN|Medical Record)[:\s#]*([A-Z0-9]{6,12})\b'
    category: MedicalRecordNumber
    flags: IGNORECASE
  
  - name: AccountNumber
    regex: '\b(?:Account|Acct\.?)[:\s#]*(\d{6,12})\b'
    category: AccountNumber
    flags: IGNORECASE
  
  - name: InsuranceMemberID
    regex: '\b(?:Member|Insurance) ID[:\s]*([A-Z0-9]{8,15})\b'
    category: InsuranceID
    flags: IGNORECASE

# Users can add custom patterns for their institution
```

---

## Dependencies

```bash
# Core
poetry add pillow  # Image processing
poetry add python-Levenshtein  # Fuzzy string matching

# Azure Services
poetry add azure-ai-formrecognizer  # Document Intelligence OCR
poetry add azure-ai-textanalytics  # Language PII detection

# AWS Services (Future)
poetry add boto3  # AWS SDK
poetry add aioboto3  # Async AWS SDK

# Testing
poetry add --group dev pytest pytest-asyncio pytest-cov
poetry add --group dev python-Levenshtein  # For testing fuzzy matching
poetry add --group dev faker  # Generate fake PHI for tests

# Existing (from Phase 1-2)
poetry add fastapi uvicorn sqlalchemy asyncpg celery redis aiofiles
```

---

## Project Structure

```
redactifai/
├── .env.example
├── .gitignore
├── LICENSE (MIT)
├── README.md
├── pyproject.toml
├── pytest.ini
├── docker-compose.yml
├── Dockerfile
├── Dockerfile.worker
│
├── src/
│   ├── __init__.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── domain.py              # All dataclasses (OCRResult, PHIEntity, etc.)
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ocr_service.py         # Abstract OCR interface
│   │   ├── mock_ocr_service.py    # Mock for testing
│   │   ├── azure_ocr_service.py   # Azure Document Intelligence
│   │   ├── phi_detection_service.py      # Abstract PHI interface
│   │   ├── mock_phi_detection_service.py # Mock for testing
│   │   ├── azure_phi_detection_service.py # Azure Language PII
│   │   ├── entity_matcher.py      # **CORE LOGIC** - Map entities to boxes
│   │   ├── image_masking_service.py      # Draw black rectangles
│   │   └── deidentification_service.py   # Orchestrates pipeline
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── image_processor.py     # TIFF load/split/reassemble
│   │   ├── geometry.py            # Bounding box operations
│   │   └── logging.py             # Structured logging
│   │
│   ├── config/
│   │   └── phi_patterns.yaml      # Custom regex patterns
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── s3.py
│   │   ├── local.py
│   │   └── settings.py
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py              # Job ORM
│   │   └── session.py             # DatabaseSessionManager
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py              # FastAPI endpoints
│   │
│   └── tasks.py                   # Celery worker tasks
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   │
│   ├── unit/
│   │   ├── test_entity_matcher.py    # **PRIORITY** - Core logic tests
│   │   ├── test_image_masking.py
│   │   ├── test_geometry.py
│   │   └── test_storage.py
│   │
│   ├── integration/
│   │   ├── test_mocked_pipeline.py   # Full flow with mocks
│   │   └── test_api.py
│   │
│   └── fixtures/
│       ├── sample_medical_record.tiff
│       └── expected_ocr_output.json
│
└── scripts/
    ├── init_db.py
    └── run_tests.sh
```

---

## Success Metrics

### After 16 Hours (Critical Path Complete)

**Must Have:**
- ✅ `EntityMatcher` working with 90%+ accuracy on test data
- ✅ Handles all major edge cases (OCR errors, multi-line, whitespace)
- ✅ End-to-end pipeline works with mock services
- ✅ Can load TIFF, mask PHI, save result
- ✅ Unit test coverage >80%
- ✅ Integration tests pass

**Nice to Have:**
- ✅ Performance profiling done
- ✅ Configuration system working
- ✅ Documentation for core algorithm

### Post-16 Hours (Real Services)

**Phase 6: Azure Integration (4-6 hours)**
- Implement `AzureDocumentIntelligenceOCR`
- Implement `AzureLanguagePHIService`
- Test with real Azure credentials
- Handle API errors and rate limits

**Phase 7: API & Workers (from original spec)**
- FastAPI endpoints
- Celery tasks
- Job queue management
- (Already designed in original spec)

---

## Open Questions to Resolve

### 1. HIPAA Compliance Level

**Question:** What masking level should be the default?

**Options:**
- `safe_harbor` (strictest) - Mask ALL identifiers including providers
- `limited_dataset` - Keep provider names, mask patient info
- `custom` - User-defined

**Recommendation:** Default to `safe_harbor` for liability reasons. Let users opt into less restrictive modes.

### 2. Confidence Threshold

**Question:** What confidence threshold for masking entities?

**Context:** ML services return confidence scores (0.0-1.0). Low-confidence entities might be false positives.

**Options:**
- Mask everything (threshold=0.0) - May over-mask
- Threshold=0.8 - Conservative, may miss some PHI
- Threshold=0.5 - Aggressive, more false positives

**Recommendation:** Default to 0.8, make it configurable. Log low-confidence entities for review.

### 3. Fuzzy Matching Tolerance

**Question:** How tolerant should fuzzy matching be for OCR errors?

**Context:** Levenshtein distance allows character substitutions. Distance=1 means one character different.

**Options:**
- Distance ≤ 1 - Very strict, may miss OCR errors
- Distance ≤ 2 - Moderate, good balance
- Distance ≤ 3 - Lenient, may match wrong words

**Recommendation:** Distance ≤ 2 for words >5 characters, exact match for shorter words.

### 4. Multi-Page Entity Handling

**Question:** How to handle entities that span page boundaries?

**Example:** Address starts at bottom of page 1, continues on page 2.

**Options:**
- Split entity, create mask region per page
- Only mask portion on first page
- Skip masking (log warning)

**Recommendation:** Split and mask on both pages. Track page boundaries in offset calculation.

### 5. Provider Name Masking

**Question:** Should provider names always be maskable separately?

**Context:** For research use, might want "Patient saw Dr. Smith for X" where patient is masked but doctor isn't.

**Options:**
- Always mask providers (safe_harbor)
- Make provider masking optional (limited_dataset)
- Detect provider context (complex)

**Recommendation:** Support both modes via `MASKING_LEVEL` config.

### 6. Padding Around Masked Regions

**Question:** Should masked rectangles extend beyond exact bounding box?

**Context:** Small text might be partially visible at edges.

**Options:**
- No padding (exact bbox)
- Small padding (5px)
- Percentage-based padding (10% of box size)

**Recommendation:** Default to 5px padding, make configurable via `MASKING_PADDING_PX`.

---

## Risk Assessment

### High Risk (Core Logic Issues)

| Risk | Impact | Mitigation |
|------|--------|------------|
| **EntityMatcher fails to match entities** | PHI not masked, HIPAA violation | Extensive testing with real medical records, log unmatched entities |
| **Fuzzy matching too aggressive** | Masks non-PHI words | Tune Levenshtein distance, add confidence threshold |
| **Multi-line entities not handled** | Partial masking | Track line breaks in offset calculation, test thoroughly |
| **OCR quality too poor** | Can't find entities | Document OCR quality requirements, reject low-quality scans |

### Medium Risk (Service Integration)

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Azure API rate limits** | Processing delays | Implement retry logic, queue management |
| **Azure service outages** | Service unavailable | Graceful degradation, clear error messages |
| **Cost overruns** | Expensive to run | Monitor API usage, set budget alerts |
| **Coordinate system mismatches** | Masks in wrong place | Normalize all coordinates, extensive testing |

### Low Risk (Nice-to-Have Features)

| Risk | Impact | Mitigation |
|------|--------|------------|
| **AWS integration delayed** | Single-vendor lock-in | Already abstracted, can add later |
| **Custom patterns complex** | Users struggle to configure | Good documentation, examples |
| **Performance issues** | Slow processing | Profile and optimize, consider batch processing |

---

## Deployment Considerations (Post-Development)

### Azure Resources Needed

```bash
# Document Intelligence
az cognitiveservices account create \
  --name redactifai-ocr \
  --resource-group redactifai-rg \
  --kind FormRecognizer \
  --sku S0 \
  --location eastus

# Language Service (PII Detection)
az cognitiveservices account create \
  --name redactifai-phi \
  --resource-group redactifai-rg \
  --kind TextAnalytics \
  --sku S \
  --location eastus
```

### Cost Estimates (Azure)

**Document Intelligence (OCR):**
- Read API: $1.50 per 1,000 pages
- For 10,000 pages/month: ~$15/month

**Language Service (PII Detection):**
- Text Analytics: $2 per 1,000 text records
- Assuming 1 record = 1 page: ~$20/month for 10,000 pages

**Total: ~$35/month for 10,000 pages**

Plus infrastructure (compute, storage, database) ~$50-100/month.

---

## Timeline Summary

### Critical Path (16 hours)
- **Hours 1-4:** Data models + EntityMatcher core
- **Hours 5-8:** Edge case handling
- **Hours 9-11:** Mock services
- **Hours 12-14:** Image masking + pipeline
- **Hours 15-16:** Configuration + final testing

### Post-Critical Path
- **Hours 17-22:** Azure service integration (~6 hours)
- **Hours 23-28:** API + Celery workers (~6 hours)
- **Hours 29-32:** Docker + deployment (~4 hours)
- **Hours 33-36:** Documentation + polish (~4 hours)

**Total: ~36 hours for production-ready v1.0**

---

## Next Steps

1. **Review this spec** - Confirm approach makes sense
2. **Start new thread** - Copy this spec, begin implementation
3. **Build in order:**
   - Phase 1: Data models + EntityMatcher core
   - Phase 2: Edge cases
   - Phase 3: Mocks
   - Phase 4: Image masking
   - Phase 5: Configuration
   - Phase 6+: Real services

4. **Test continuously** - Write tests as you build each component

---

## Appendix: Azure API Examples

### Document Intelligence OCR Request

```python
from azure.ai.formrecognizer import DocumentAnalysisClient

client = DocumentAnalysisClient(endpoint, credential)

# Analyze document
poller = client.begin_analyze_document(
    model_id="prebuilt-read",
    document=tiff_bytes
)
result = poller.result()

# Response structure
{
  "apiVersion": "2024-11-30",
  "content": "Samuel Grummons had a vasectomy...",
  "pages": [
    {
      "pageNumber": 1,
      "width": 2550,
      "height": 3300,
      "words": [
        {
          "content": "Samuel",
          "polygon": [145, 220, 230, 220, 230, 244, 145, 244],
          "confidence": 0.994,
          "span": {"offset": 0, "length": 6}
        }
      ]
    }
  ]
}
```

### Language PII Detection Request

```python
from azure.ai.textanalytics import TextAnalyticsClient

client = TextAnalyticsClient(endpoint, credential)

# Detect PII
response = client.recognize_pii_entities(
    documents=["Samuel Grummons had a vasectomy on 03/15/2023"],
    domain="phi"
)

# Response structure
{
  "entities": [
    {
      "text": "Samuel Grummons",
      "category": "Person",
      "subcategory": "PersonName",
      "offset": 0,
      "length": 15,
      "confidenceScore": 0.95
    },
    {
      "text": "03/15/2023",
      "category": "DateTime",
      "subcategory": "Date",
      "offset": 32,
      "length": 10,
      "confidenceScore": 0.98
    }
  ],
  "redactedText": "********* ******** had a vasectomy on **********"
}
```

---

**END OF SPECIFICATION**
