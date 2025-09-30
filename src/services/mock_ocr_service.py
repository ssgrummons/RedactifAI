"""
Mock OCR service for testing without real Azure/AWS services.

Generates realistic OCR results with intentional errors for testing
the EntityMatcher's robustness.
"""

import random
from typing import Optional
from src.models.domain import OCRResult, OCRPage, OCRWord, BoundingBox
from src.services.ocr_service import OCRService


class MockOCRService(OCRService):
    """
    Mock OCR service that generates realistic test data.
    
    Features:
    - Generates word-level bounding boxes
    - Adds intentional OCR errors (character swaps)
    - Handles multi-page documents
    - Configurable error rate
    """
    
    def __init__(
        self,
        error_rate: float = 0.05,
        page_width: float = 2550.0,
        page_height: float = 3300.0,
        seed: Optional[int] = None,
    ):
        """
        Initialize mock OCR service.
        
        Args:
            error_rate: Probability of introducing OCR errors (0.0-1.0)
            page_width: Default page width in pixels
            page_height: Default page height in pixels
            seed: Random seed for reproducible errors
        """
        self.error_rate = error_rate
        self.page_width = page_width
        self.page_height = page_height
        
        if seed is not None:
            random.seed(seed)
    
    async def analyze_document(
        self,
        document_bytes: bytes,
        file_format: str = "tiff",
        language: Optional[str] = None,
    ) -> OCRResult:
        """
        Mock document analysis - returns predefined medical record text.
        
        In a real implementation, this would process document_bytes.
        For testing, we return a realistic medical record with PHI.
        """
        # Sample medical record text
        text = self._get_sample_medical_text()
        
        # Split into pages (simulate multi-page doc)
        pages_text = self._split_into_pages(text)
        
        # Generate OCR results for each page
        pages = []
        for page_num, page_text in enumerate(pages_text, start=1):
            page = self._generate_page_ocr(page_num, page_text)
            pages.append(page)
        
        # Full text is all pages concatenated
        full_text = "\n".join(pages_text)
        
        return OCRResult(pages=pages, full_text=full_text)
    
    def _get_sample_medical_text(self) -> str:
        """Get sample medical record text with PHI."""
        return """Patient: Samuel Grummons
DOB: 03/15/1985
MRN: 12345678

Chief Complaint: Follow-up for vasectomy consultation

History of Present Illness:
Mr. Grummons is a 38-year-old male who presents today for follow-up
regarding his vasectomy procedure performed on 06/22/2023. He reports
no complications and is doing well. He has two children and does not
wish to have more. His spouse, Jennifer Grummons, is supportive of
this decision.

Past Medical History:
- Hypertension, controlled on medication
- No prior surgeries

Medications:
- Lisinopril 10mg daily

Allergies: No known drug allergies

Social History:
Patient works as a software engineer at TechCorp Inc. He lives at
123 Main Street, Boston, MA 02101. Contact phone: (617) 555-1234.
Email: samuel.grummons@email.com

Insurance: Blue Cross Blue Shield Member ID: ABC123456789

Assessment and Plan:
Post-vasectomy follow-up is satisfactory. Patient advised to continue
routine health maintenance. Next appointment scheduled for annual
physical on 12/15/2023.

Attending Physician: Dr. Sarah Johnson, MD
Date of Service: 09/30/2023"""
    
    def _split_into_pages(self, text: str, max_lines_per_page: int = 15) -> list[str]:
        """Split text into pages (simulate multi-page document)."""
        lines = text.split('\n')
        pages = []
        
        current_page = []
        for line in lines:
            current_page.append(line)
            if len(current_page) >= max_lines_per_page:
                pages.append('\n'.join(current_page))
                current_page = []
        
        # Add remaining lines
        if current_page:
            pages.append('\n'.join(current_page))
        
        return pages
    
    def _generate_page_ocr(self, page_number: int, text: str) -> OCRPage:
        """Generate OCR result for a single page."""
        words = []
        
        # Start position for first line
        x = 100.0
        y = 200.0
        line_height = 30.0
        
        lines = text.split('\n')
        for line in lines:
            # Split line into words
            line_words = line.split()
            
            current_x = x
            for word_text in line_words:
                # Maybe introduce OCR error
                ocr_text = self._maybe_add_ocr_error(word_text)
                
                # Calculate word width (rough estimate: 12px per char)
                word_width = len(ocr_text) * 12.0
                
                # Create bounding box
                bbox = BoundingBox(
                    page=page_number,
                    x=current_x,
                    y=y,
                    width=word_width,
                    height=20.0,
                )
                
                # Create OCR word
                confidence = 0.99 if ocr_text == word_text else 0.85
                words.append(OCRWord(
                    text=ocr_text,
                    confidence=confidence,
                    bounding_box=bbox,
                ))
                
                # Move to next word position (word width + space)
                current_x += word_width + 10.0
            
            # Move to next line
            y += line_height
        
        return OCRPage(
            page_number=page_number,
            width=self.page_width,
            height=self.page_height,
            words=words,
        )
    
    def _maybe_add_ocr_error(self, word: str) -> str:
        """
        Randomly introduce OCR errors.
        
        Common OCR errors:
        - S → 5
        - O → 0
        - I → 1 or l
        - G → 6
        """
        if random.random() > self.error_rate or len(word) < 3:
            return word
        
        # Common OCR character substitutions
        substitutions = {
            'S': '5',
            's': '5',
            'O': '0',
            'o': '0',
            'I': '1',
            'i': 'l',
            'G': '6',
            'g': '6',
        }
        
        # Pick a random character to corrupt
        pos = random.randint(0, len(word) - 1)
        char = word[pos]
        
        if char in substitutions:
            # Make substitution
            word_list = list(word)
            word_list[pos] = substitutions[char]
            return ''.join(word_list)
        
        return word