"""
Additional real-world test scenarios for EntityMatcher.

These tests cover complex production scenarios that we've encountered:
1. PHI service returns different text than OCR
2. Fuzzy search over-matching
3. Short entities causing false positives
4. Offset misalignment between services
5. Gateway response format differences
"""

import pytest
from src.models.domain import (
    BoundingBox,
    OCRWord,
    OCRPage,
    OCRResult,
    PHIEntity,
)
from src.services.entity_matcher import EntityMatcher


class TestRealWorldScenarios:
    """Tests based on actual production issues."""
    
    def test_phi_service_normalized_text_ocr_has_formatting(self):
        """
        Test when PHI service returns normalized text but OCR preserves formatting.
        
        Real scenario: OCR has "John  Doe" (2 spaces), PHI returns "John Doe" (1 space).
        Offsets from PHI service don't match OCR full_text.
        """
        # OCR with extra spaces
        words = [
            OCRWord(text="John", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=50, height=20)),
            OCRWord(text="Doe", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=160, y=200, width=40, height=20)),
        ]
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(pages=[page], full_text="John  Doe")  # 2 spaces in OCR
        
        # PHI service detected normalized version with offset for normalized text
        entities = [
            PHIEntity(
                text="John Doe",  # 1 space
                category="Person",
                offset=0,
                length=8,  # Length in normalized text, not OCR text!
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should still match despite offset mismatch
        assert len(mask_regions) == 1
        assert mask_regions[0].entity_category == "Person"
    
    def test_short_entity_false_positives(self):
        """
        Test that short entities don't cause massive over-matching.
        
        Real scenario: Entity "J" matched 291 OCR words because every "J"
        in the document was considered a match.
        """
        # Document with many J's
        words = [
            OCRWord(text="J", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=10, height=20)),
            OCRWord(text="Smith", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=115, y=200, width=60, height=20)),
            OCRWord(text="John", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=250, width=50, height=20)),
            OCRWord(text="J", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=155, y=250, width=10, height=20)),
            OCRWord(text="Doe", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=170, y=250, width=40, height=20)),
        ]
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(pages=[page], full_text="J Smith\nJohn J Doe")
        
        # PHI entity for single letter (should rarely happen, but can)
        entities = [
            PHIEntity(
                text="J",
                category="Person",
                offset=0,
                length=1,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should match only the first J, not every J in document
        assert len(mask_regions) <= 1
    
    def test_common_word_as_phi_entity(self):
        """
        Test handling when PHI entity is a common word appearing multiple times.
        
        Real scenario: Name "John" appears in "John Doe" and also in 
        "St. John's Hospital". Fuzzy search might match both.
        """
        words = [
            # Patient name
            OCRWord(text="Patient:", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=80, height=20)),
            OCRWord(text="John", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=185, y=200, width=50, height=20)),
            OCRWord(text="Doe", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=240, y=200, width=40, height=20)),
            # Hospital name
            OCRWord(text="Hospital:", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=250, width=90, height=20)),
            OCRWord(text="St.", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=195, y=250, width=30, height=20)),
            OCRWord(text="John's", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=230, y=250, width=60, height=20)),
        ]
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(
            pages=[page],
            full_text="Patient: John Doe\nHospital: St. John's"
        )
        
        # PHI service detected "John Doe" (full name, not just "John")
        entities = [
            PHIEntity(
                text="John Doe",
                category="Person",
                offset=9,  # After "Patient: "
                length=8,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should mask only "John Doe", not "John's"
        assert len(mask_regions) == 1
        region = mask_regions[0]
        # Should be on first line (y=200), not second line (y=250)
        assert region.bounding_box.y < 230
    
    def test_offset_completely_wrong_fuzzy_search_saves_it(self):
        """
        Test when PHI service offsets are completely wrong but text is findable.
        
        Real scenario: Gateway wraps PHI service and modifies text somehow,
        causing all offsets to be shifted. Fuzzy search should find entities
        by text content.
        """
        words = [
            OCRWord(text="John", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=50, height=20)),
            OCRWord(text="Smith", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=155, y=200, width=60, height=20)),
        ]
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(pages=[page], full_text="John Smith")
        
        # PHI service has completely wrong offset (maybe gateway added a prefix)
        entities = [
            PHIEntity(
                text="John Smith",
                category="Person",
                offset=500,  # Way off!
                length=10,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Fuzzy search should save us
        assert len(mask_regions) >= 1
        assert mask_regions[0].entity_category == "Person"
    
    def test_entity_text_has_newlines_ocr_has_spaces(self):
        """
        Test when PHI service preserves newlines but OCR converts to spaces.
        
        Real scenario: Address entities from PHI service have \n, but OCR
        full_text has spaces instead.
        """
        words = [
            OCRWord(text="123", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=40, height=20)),
            OCRWord(text="Main", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=145, y=200, width=50, height=20)),
            OCRWord(text="St", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=200, y=200, width=30, height=20)),
            OCRWord(text="Boston", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=235, y=200, width=70, height=20)),
        ]
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(pages=[page], full_text="123 Main St Boston")  # Spaces
        
        # PHI service detected address with newline
        entities = [
            PHIEntity(
                text="123 Main St\nBoston",  # Newline
                category="Address",
                offset=0,
                length=18,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should still match despite newline vs space difference
        assert len(mask_regions) >= 1
    
    def test_multiple_pages_entity_only_on_one_page(self):
        """
        Test multi-page document where entity is only on one page.
        
        Real scenario: 28-page document, "John Doe" on page 5. Should not
        create masks on other pages.
        """
        # Create 3 pages, entity only on page 2
        words_p1 = [
            OCRWord(text="Page", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=50, height=20)),
            OCRWord(text="One", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=155, y=200, width=40, height=20)),
        ]
        words_p2 = [
            OCRWord(text="Patient:", confidence=0.99,
                   bounding_box=BoundingBox(page=2, x=100, y=200, width=80, height=20)),
            OCRWord(text="John", confidence=0.99,
                   bounding_box=BoundingBox(page=2, x=185, y=200, width=50, height=20)),
            OCRWord(text="Doe", confidence=0.99,
                   bounding_box=BoundingBox(page=2, x=240, y=200, width=40, height=20)),
        ]
        words_p3 = [
            OCRWord(text="Page", confidence=0.99,
                   bounding_box=BoundingBox(page=3, x=100, y=200, width=50, height=20)),
            OCRWord(text="Three", confidence=0.99,
                   bounding_box=BoundingBox(page=3, x=155, y=200, width=60, height=20)),
        ]
        
        page1 = OCRPage(page_number=1, width=1000, height=1000, words=words_p1)
        page2 = OCRPage(page_number=2, width=1000, height=1000, words=words_p2)
        page3 = OCRPage(page_number=3, width=1000, height=1000, words=words_p3)
        
        ocr_result = OCRResult(
            pages=[page1, page2, page3],
            full_text="Page One\nPatient: John Doe\nPage Three"
        )
        
        entities = [
            PHIEntity(
                text="John Doe",
                category="Person",
                offset=18,  # In the middle section
                length=8,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should have exactly 1 mask region on page 2
        assert len(mask_regions) == 1
        assert mask_regions[0].page == 2
    
    def test_very_long_document_performance(self):
        """
        Test that matching performs reasonably on long documents.
        
        Real scenario: 28-page medical record with 10,000+ words.
        This is more of a sanity check that we don't hang.
        """
        # Create a long document (100 words across 5 pages)
        all_pages = []
        full_text_parts = []
        
        for page_num in range(1, 6):
            words = []
            for i in range(20):  # 20 words per page
                word_text = f"word{page_num}_{i}"
                words.append(OCRWord(
                    text=word_text,
                    confidence=0.99,
                    bounding_box=BoundingBox(
                        page=page_num,
                        x=100 + (i % 5) * 100,
                        y=200 + (i // 5) * 30,
                        width=80,
                        height=20
                    )
                ))
                full_text_parts.append(word_text)
            
            all_pages.append(OCRPage(
                page_number=page_num,
                width=1000,
                height=1000,
                words=words
            ))
        
        ocr_result = OCRResult(
            pages=all_pages,
            full_text=" ".join(full_text_parts)
        )
        
        # Entity on page 3
        entities = [
            PHIEntity(
                text="word3_10",
                category="Person",
                offset=full_text_parts.index("word3_10") * 9,  # Approximate offset
                length=8,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        # This should not hang or take excessive time
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should find it
        assert len(mask_regions) >= 1


class TestFuzzySearchBehavior:
    """Tests specifically for fuzzy search edge cases."""
    
    def test_fuzzy_search_requires_minimum_length(self):
        """
        Test that fuzzy search skips very short entities.
        
        Prevents "J" from matching hundreds of single letters.
        """
        # Document with many single letters
        words = []
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for i, letter in enumerate(letters):
            words.append(OCRWord(
                text=letter,
                confidence=0.99,
                bounding_box=BoundingBox(page=1, x=100 + i*20, y=200, width=15, height=20)
            ))
        
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(pages=[page], full_text=" ".join(letters))
        
        # Entity for single letter with wrong offset (forces fuzzy search)
        entities = [
            PHIEntity(
                text="J",
                category="Person",
                offset=999,  # Wrong offset
                length=1,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Fuzzy search should refuse to search for single letters
        # So we should get 0 matches (not 26!)
        assert len(mask_regions) == 0
    
    def test_fuzzy_search_matches_sequences_not_fragments(self):
        """
        Test that fuzzy search matches word sequences, not fragments.
        
        "John Doe" should match consecutive words "John" "Doe",
        not match "John" on page 1 and "Doe" on page 15.
        """
        words = [
            # Page 1: "John Smith"
            OCRWord(text="John", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=50, height=20)),
            OCRWord(text="Smith", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=155, y=200, width=60, height=20)),
            # Some other words
            OCRWord(text="Random", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=250, width=70, height=20)),
            OCRWord(text="Text", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=175, y=250, width=50, height=20)),
            # Much later: "Jane Doe"
            OCRWord(text="Jane", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=500, width=50, height=20)),
            OCRWord(text="Doe", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=155, y=500, width=40, height=20)),
        ]
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(
            pages=[page],
            full_text="John Smith\nRandom Text\nJane Doe"
        )
        
        # Looking for "John Doe" (which doesn't exist as a sequence)
        entities = [
            PHIEntity(
                text="John Doe",
                category="Person",
                offset=999,  # Force fuzzy search
                length=8,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should NOT match - "John" and "Doe" aren't consecutive
        assert len(mask_regions) == 0
    
    def test_fuzzy_search_stops_after_first_match(self):
        """
        Test that fuzzy search doesn't continue after finding a match.
        
        If "John Smith" appears twice, should only match the first occurrence.
        """
        words = [
            # First occurrence
            OCRWord(text="John", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=50, height=20)),
            OCRWord(text="Smith", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=155, y=200, width=60, height=20)),
            # Some space
            OCRWord(text="...", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=250, width=30, height=20)),
            # Second occurrence
            OCRWord(text="John", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=300, width=50, height=20)),
            OCRWord(text="Smith", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=155, y=300, width=60, height=20)),
        ]
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(
            pages=[page],
            full_text="John Smith\n...\nJohn Smith"
        )
        
        entities = [
            PHIEntity(
                text="John Smith",
                category="Person",
                offset=999,  # Force fuzzy search
                length=10,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should find exactly 1 match (the first occurrence)
        assert len(mask_regions) == 1
        # Should be at y=200, not y=300
        assert mask_regions[0].bounding_box.y < 250