"""
Mock PHI detection service for testing.

Uses regex patterns to detect common PHI categories without requiring
Azure or AWS services.
"""

import re
from typing import List
from src.models.domain import PHIEntity, MaskingLevel
from src.services.phi_detection_service import PHIDetectionService


class MockPHIDetectionService(PHIDetectionService):
    """
    Mock PHI detection using regex patterns.
    
    Detects common PHI categories:
    - Names (simple pattern: capitalized words)
    - Dates (various formats)
    - Phone numbers
    - Email addresses
    - SSNs
    - Medical record numbers
    - Addresses
    """
    
    # Regex patterns for PHI detection
    PATTERNS = {
        "Date": [
            r'\b\d{1,2}/\d{1,2}/\d{4}\b',  # MM/DD/YYYY
            r'\b\d{1,2}-\d{1,2}-\d{4}\b',  # MM-DD-YYYY
        ],
        "PhoneNumber": [
            r'\(\d{3}\)\s*\d{3}-\d{4}',  # (617) 555-1234
            r'\d{3}-\d{3}-\d{4}',         # 617-555-1234
        ],
        "Email": [
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        ],
        "SSN": [
            r'\b\d{3}-\d{2}-\d{4}\b',
        ],
        "MedicalRecordNumber": [
            r'\bMRN:\s*\d+\b',
            r'\bMedical Record\s*#?:?\s*\d+\b',
        ],
        "InsuranceID": [
            r'\bMember ID:\s*[A-Z0-9]+\b',
        ],
        "Address": [
            # Simple: number + street + city, state zip
            r'\b\d+\s+[A-Z][a-z]+\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd)[,\s]+[A-Z][a-z]+[,\s]+[A-Z]{2}\s+\d{5}\b',
        ],
    }
    
    async def detect_phi(
        self,
        text: str,
        masking_level: MaskingLevel = MaskingLevel.SAFE_HARBOR,
    ) -> List[PHIEntity]:
        """Detect PHI entities using regex patterns."""
        entities = []
        
        # Detect using regex patterns
        for category, patterns in self.PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    entity = PHIEntity(
                        text=match.group(),
                        category=category,
                        offset=match.start(),
                        length=len(match.group()),
                        confidence=0.95,
                    )
                    
                    if self._should_include_entity(category, masking_level):
                        entities.append(entity)
        
        # Detect person names (simple heuristic: capitalized words)
        entities.extend(self._detect_names(text, masking_level))
        
        # Sort by offset
        entities.sort(key=lambda e: e.offset)
        
        return entities
    
    def _detect_names(
        self,
        text: str,
        masking_level: MaskingLevel,
    ) -> List[PHIEntity]:
        """
        Detect person names using simple heuristic.
        
        Looks for patterns like "FirstName LastName" where both are capitalized.
        """
        names = []
        
        # Pattern: Two or more consecutive capitalized words
        # This is overly simplistic but works for testing
        pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b'
        
        for match in re.finditer(pattern, text):
            matched_text = match.group()
            
            # Skip common non-name phrases
            skip_phrases = {
                'Chief Complaint',
                'History Of',
                'Present Illness',
                'Past Medical',
                'Social History',
                'Blue Cross',
                'Blue Shield',
                'New England',
            }
            
            if any(skip in matched_text for skip in skip_phrases):
                continue
            
            # Check if this looks like a medical professional
            # (for limited dataset mode)
            is_provider = any(
                title in text[max(0, match.start()-10):match.start()]
                for title in ['Dr.', 'Dr ', 'Doctor', 'Physician']
            )
            
            category = "HealthcareProfessional" if is_provider else "Person"
            
            if self._should_include_entity(category, masking_level):
                names.append(PHIEntity(
                    text=matched_text,
                    category=category,
                    offset=match.start(),
                    length=len(matched_text),
                    confidence=0.90,
                    subcategory="PersonName",
                ))
        
        return names