"""
Unit tests for EntityMatcher.

These tests verify the core matching logic with increasing complexity:
1. Simple single-word matches
2. Multi-word entity matches
3. OCR errors and fuzzy matching
4. Whitespace inconsistencies
5. Multi-line entities
6. Page boundaries
7. Edge cases
"""

import pytest
from src.models.domain import (
    BoundingBox,
    OCRWord,
    OCRPage,
    OCRResult,
    PHIEntity,
)
from src.services.entity_matcher import EntityMatcher, WordOffset


class TestWordOffset:
    """Tests for WordOffset helper class."""
    
    def test_contains_offset(self):
        """Test offset containment checking."""
        bbox = BoundingBox(page=1, x=100, y=100, width=50, height=20)
        word = OCRWord(text="Hello", confidence=0.99, bounding_box=bbox)
        word_offset = WordOffset(word=word, start_offset=0, end_offset=5)
        
        assert word_offset.contains_offset(0)
        assert word_offset.contains_offset(4)
        assert not word_offset.contains_offset(5)
        assert not word_offset.contains_offset(-1)
    
    def test_overlaps_range(self):
        """Test range overlap checking."""
        bbox = BoundingBox(page=1, x=100, y=100, width=50, height=20)
        word = OCRWord(text="Hello", confidence=0.99, bounding_box=bbox)
        word_offset = WordOffset(word=word, start_offset=5, end_offset=10)
        
        # Overlapping ranges
        assert word_offset.overlaps_range(0, 6)   # Starts before, ends inside
        assert word_offset.overlaps_range(7, 12)  # Starts inside, ends after
        assert word_offset.overlaps_range(5, 10)  # Exact match
        assert word_offset.overlaps_range(4, 11)  # Completely contains
        
        # Non-overlapping ranges
        assert not word_offset.overlaps_range(0, 5)   # Ends at start
        assert not word_offset.overlaps_range(10, 15) # Starts at end


class TestEntityMatcherBasics:
    """Tests for basic EntityMatcher functionality."""
    
    def test_simple_single_word_match(self):
        """Test matching a single-word entity to a single word."""
        # OCR result with one word
        bbox = BoundingBox(page=1, x=100, y=200, width=50, height=20)
        word = OCRWord(text="John", confidence=0.99, bounding_box=bbox)
        page = OCRPage(page_number=1, width=1000, height=1000, words=[word])
        ocr_result = OCRResult(pages=[page], full_text="John")
        
        # PHI entity for "John"
        entities = [
            PHIEntity(
                text="John",
                category="Person",
                offset=0,
                length=4,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        assert len(mask_regions) == 1
        region = mask_regions[0]
        assert region.page == 1
        assert region.entity_category == "Person"
        assert region.confidence == 0.95
        # Box should be word box plus padding
        assert region.bounding_box.x == bbox.x - 5  # Default padding
        assert region.bounding_box.width == bbox.width + 10
    
    def test_multi_word_entity_match(self):
        """Test matching a multi-word entity."""
        # OCR result with two words
        bbox1 = BoundingBox(page=1, x=100, y=200, width=50, height=20)
        bbox2 = BoundingBox(page=1, x=155, y=200, width=60, height=20)
        word1 = OCRWord(text="John", confidence=0.99, bounding_box=bbox1)
        word2 = OCRWord(text="Smith", confidence=0.99, bounding_box=bbox2)
        page = OCRPage(page_number=1, width=1000, height=1000, words=[word1, word2])
        ocr_result = OCRResult(pages=[page], full_text="John Smith")
        
        # PHI entity for "John Smith"
        entities = [
            PHIEntity(
                text="John Smith",
                category="Person",
                offset=0,
                length=10,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        assert len(mask_regions) == 1
        region = mask_regions[0]
        # Should merge both word boxes
        assert region.bounding_box.x == bbox1.x - 5  # Start of first word
        assert region.bounding_box.width >= (bbox2.x + bbox2.width) - bbox1.x + 10
    
    def test_multiple_entities_in_text(self):
        """Test matching multiple separate entities."""
        # OCR: "John Smith had a birthday on 03/15/2023"
        words = [
            OCRWord(text="John", confidence=0.99, 
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=50, height=20)),
            OCRWord(text="Smith", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=155, y=200, width=60, height=20)),
            OCRWord(text="had", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=220, y=200, width=40, height=20)),
            OCRWord(text="a", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=265, y=200, width=15, height=20)),
            OCRWord(text="birthday", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=285, y=200, width=80, height=20)),
            OCRWord(text="on", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=370, y=200, width=25, height=20)),
            OCRWord(text="03/15/2023", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=400, y=200, width=100, height=20)),
        ]
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(
            pages=[page],
            full_text="John Smith had a birthday on 03/15/2023"
        )
        
        # Two entities: name and date
        entities = [
            PHIEntity(text="John Smith", category="Person", 
                     offset=0, length=10, confidence=0.95),
            PHIEntity(text="03/15/2023", category="Date",
                     offset=30, length=10, confidence=0.98),
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        assert len(mask_regions) == 2
        # Verify we got one for each category
        categories = {r.entity_category for r in mask_regions}
        assert categories == {"Person", "Date"}


class TestOCRErrors:
    """Tests for handling OCR errors via fuzzy matching."""
    
    def test_single_character_ocr_error(self):
        """Test matching when OCR misreads one character (S→5)."""
        # OCR misread "Samuel" as "5amuel"
        bbox = BoundingBox(page=1, x=100, y=200, width=70, height=20)
        word = OCRWord(text="5amuel", confidence=0.85, bounding_box=bbox)
        page = OCRPage(page_number=1, width=1000, height=1000, words=[word])
        ocr_result = OCRResult(pages=[page], full_text="5amuel")
        
        # PHI entity has correct spelling
        entities = [
            PHIEntity(
                text="Samuel",
                category="Person",
                offset=0,
                length=6,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher(fuzzy_match_threshold=2)
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should still match despite OCR error
        assert len(mask_regions) == 1
        assert mask_regions[0].entity_category == "Person"
    
    def test_multiple_character_ocr_errors(self):
        """Test matching with multiple character errors within threshold."""
        # OCR misread "Grummons" as "6rumm0ns" (G→6, o→0)
        bbox = BoundingBox(page=1, x=100, y=200, width=90, height=20)
        word = OCRWord(text="6rumm0ns", confidence=0.80, bounding_box=bbox)
        page = OCRPage(page_number=1, width=1000, height=1000, words=[word])
        ocr_result = OCRResult(pages=[page], full_text="6rumm0ns")
        
        entities = [
            PHIEntity(
                text="Grummons",
                category="Person",
                offset=0,
                length=8,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher(fuzzy_match_threshold=2)
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # 2 character differences should match with threshold=2
        assert len(mask_regions) == 1
    
    def test_too_many_errors_no_match(self):
        """Test that too many OCR errors prevent matching."""
        # OCR completely garbled the word
        bbox = BoundingBox(page=1, x=100, y=200, width=70, height=20)
        word = OCRWord(text="xyz123", confidence=0.60, bounding_box=bbox)
        page = OCRPage(page_number=1, width=1000, height=1000, words=[word])
        ocr_result = OCRResult(pages=[page], full_text="xyz123")
        
        entities = [
            PHIEntity(
                text="Samuel",
                category="Person",
                offset=0,
                length=6,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher(fuzzy_match_threshold=2)
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should not match - too different
        assert len(mask_regions) == 0


class TestWhitespaceHandling:
    """Tests for handling inconsistent whitespace."""
    
    def test_extra_spaces_in_ocr(self):
        """Test when OCR has extra spaces between words."""
        # OCR: "John  Smith" (2 spaces)
        words = [
            OCRWord(text="John", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=50, height=20)),
            OCRWord(text="Smith", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=160, y=200, width=60, height=20)),
        ]
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(pages=[page], full_text="John  Smith")  # 2 spaces
        
        # PHI entity with normal spacing
        entities = [
            PHIEntity(
                text="John Smith",  # 1 space
                category="Person",
                offset=0,
                length=10,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should still match
        assert len(mask_regions) == 1
    
    def test_missing_spaces_in_ocr(self):
        """Test when OCR concatenates words."""
        # OCR: "JohnSmith" (no space)
        words = [
            OCRWord(text="JohnSmith", confidence=0.95,
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=110, height=20)),
        ]
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(pages=[page], full_text="JohnSmith")
        
        # PHI entity with space
        entities = [
            PHIEntity(
                text="John Smith",
                category="Person",
                offset=0,
                length=10,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should match the whole word
        assert len(mask_regions) == 1


class TestMultiLineEntities:
    """Tests for entities spanning multiple lines."""
    
    def test_address_spans_two_lines(self):
        """Test matching an address that spans two lines."""
        # Line 1: "123 Main St"
        # Line 2: "Boston, MA 02101"
        words = [
            # Line 1
            OCRWord(text="123", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=40, height=20)),
            OCRWord(text="Main", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=145, y=200, width=50, height=20)),
            OCRWord(text="St", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=200, y=200, width=30, height=20)),
            # Line 2 (y=230)
            OCRWord(text="Boston,", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=230, width=70, height=20)),
            OCRWord(text="MA", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=175, y=230, width=30, height=20)),
            OCRWord(text="02101", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=210, y=230, width=50, height=20)),
        ]
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(
            pages=[page],
            full_text="123 Main St\nBoston, MA 02101"
        )
        
        # Entity spans both lines
        entities = [
            PHIEntity(
                text="123 Main St\nBoston, MA 02101",
                category="Address",
                offset=0,
                length=28,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should merge all words into one box
        assert len(mask_regions) == 1
        region = mask_regions[0]
        # Box should span both lines (y from 200 to 230+20=250)
        assert region.bounding_box.y <= 200 - 5  # Top of first line + padding
        assert region.bounding_box.y + region.bounding_box.height >= 250 + 5


class TestPageBoundaries:
    """Tests for entities spanning page boundaries."""
    
    def test_entity_spans_two_pages(self):
        """Test entity that crosses page boundary."""
        # Page 1: "continued on"
        words_p1 = [
            OCRWord(text="continued", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=3200, width=100, height=20)),
            OCRWord(text="on", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=205, y=3200, width=30, height=20)),
        ]
        page1 = OCRPage(page_number=1, width=1000, height=3300, words=words_p1)
        
        # Page 2: "next page"
        words_p2 = [
            OCRWord(text="next", confidence=0.99,
                   bounding_box=BoundingBox(page=2, x=100, y=100, width=50, height=20)),
            OCRWord(text="page", confidence=0.99,
                   bounding_box=BoundingBox(page=2, x=155, y=100, width=50, height=20)),
        ]
        page2 = OCRPage(page_number=2, width=1000, height=3300, words=words_p2)
        
        ocr_result = OCRResult(
            pages=[page1, page2],
            full_text="continued on next page"
        )
        
        # Entity spans both pages
        entities = [
            PHIEntity(
                text="continued on next page",
                category="Custom",
                offset=0,
                length=22,
                confidence=0.90
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should create two separate mask regions, one per page
        assert len(mask_regions) == 2
        pages = {r.page for r in mask_regions}
        assert pages == {1, 2}


class TestConfidenceThreshold:
    """Tests for confidence-based filtering."""
    
    def test_low_confidence_entity_skipped(self):
        """Test that low-confidence entities are not masked."""
        bbox = BoundingBox(page=1, x=100, y=200, width=50, height=20)
        word = OCRWord(text="maybe", confidence=0.99, bounding_box=bbox)
        page = OCRPage(page_number=1, width=1000, height=1000, words=[word])
        ocr_result = OCRResult(pages=[page], full_text="maybe")
        
        # Low-confidence entity
        entities = [
            PHIEntity(
                text="maybe",
                category="Person",
                offset=0,
                length=5,
                confidence=0.40  # Low confidence
            )
        ]
        
        matcher = EntityMatcher(confidence_threshold=0.80)
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should be skipped due to low confidence
        assert len(mask_regions) == 0
    
    def test_high_confidence_entity_masked(self):
        """Test that high-confidence entities are masked."""
        bbox = BoundingBox(page=1, x=100, y=200, width=50, height=20)
        word = OCRWord(text="John", confidence=0.99, bounding_box=bbox)
        page = OCRPage(page_number=1, width=1000, height=1000, words=[word])
        ocr_result = OCRResult(pages=[page], full_text="John")
        
        entities = [
            PHIEntity(
                text="John",
                category="Person",
                offset=0,
                length=4,
                confidence=0.95  # High confidence
            )
        ]
        
        matcher = EntityMatcher(confidence_threshold=0.80)
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should be masked
        assert len(mask_regions) == 1


class TestEdgeCases:
    """Tests for edge cases and error conditions."""
    
    def test_empty_entities_list(self):
        """Test with no entities to mask."""
        bbox = BoundingBox(page=1, x=100, y=200, width=50, height=20)
        word = OCRWord(text="text", confidence=0.99, bounding_box=bbox)
        page = OCRPage(page_number=1, width=1000, height=1000, words=[word])
        ocr_result = OCRResult(pages=[page], full_text="text")
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, [])
        
        assert len(mask_regions) == 0
    
    def test_entity_not_in_text(self):
        """Test entity that doesn't appear in OCR text."""
        bbox = BoundingBox(page=1, x=100, y=200, width=50, height=20)
        word = OCRWord(text="text", confidence=0.99, bounding_box=bbox)
        page = OCRPage(page_number=1, width=1000, height=1000, words=[word])
        ocr_result = OCRResult(pages=[page], full_text="text")
        
        # Entity for word that isn't there
        entities = [
            PHIEntity(
                text="missing",
                category="Person",
                offset=0,
                length=7,
                confidence=0.95
            )
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should return empty list and log warning
        assert len(mask_regions) == 0
    
    def test_overlapping_entities(self):
        """Test handling of overlapping entities."""
        words = [
            OCRWord(text="Dr.", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=30, height=20)),
            OCRWord(text="Smith", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=135, y=200, width=60, height=20)),
        ]
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(pages=[page], full_text="Dr. Smith")
        
        # Two overlapping entities
        entities = [
            PHIEntity(text="Dr.", category="Title", 
                     offset=0, length=3, confidence=0.90),
            PHIEntity(text="Dr. Smith", category="Person",
                     offset=0, length=9, confidence=0.95),
        ]
        
        matcher = EntityMatcher()
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        # Should create separate regions for each entity
        # (overlapping is fine, image masking will handle it)
        assert len(mask_regions) == 2
    
    def test_box_padding_applied(self):
        """Test that padding is correctly applied to bounding boxes."""
        bbox = BoundingBox(page=1, x=100, y=200, width=50, height=20)
        word = OCRWord(text="test", confidence=0.99, bounding_box=bbox)
        page = OCRPage(page_number=1, width=1000, height=1000, words=[word])
        ocr_result = OCRResult(pages=[page], full_text="test")
        
        entities = [
            PHIEntity(text="test", category="Person",
                     offset=0, length=4, confidence=0.95)
        ]
        
        # Custom padding
        matcher = EntityMatcher(box_padding_px=10)
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        assert len(mask_regions) == 1
        region = mask_regions[0]
        
        # Check padding is applied
        assert region.bounding_box.x == bbox.x - 10
        assert region.bounding_box.y == bbox.y - 10
        assert region.bounding_box.width == bbox.width + 20
        assert region.bounding_box.height == bbox.height + 20
    
    def test_zero_padding(self):
        """Test with no padding."""
        bbox = BoundingBox(page=1, x=100, y=200, width=50, height=20)
        word = OCRWord(text="test", confidence=0.99, bounding_box=bbox)
        page = OCRPage(page_number=1, width=1000, height=1000, words=[word])
        ocr_result = OCRResult(pages=[page], full_text="test")
        
        entities = [
            PHIEntity(text="test", category="Person",
                     offset=0, length=4, confidence=0.95)
        ]
        
        matcher = EntityMatcher(box_padding_px=0)
        mask_regions = matcher.match_entities_to_boxes(ocr_result, entities)
        
        assert len(mask_regions) == 1
        region = mask_regions[0]
        
        # Should match original box exactly
        assert region.bounding_box.x == bbox.x
        assert region.bounding_box.y == bbox.y
        assert region.bounding_box.width == bbox.width
        assert region.bounding_box.height == bbox.height


class TestOffsetMapBuilding:
    """Tests specifically for the offset map building logic."""
    
    def test_offset_map_simple_text(self):
        """Test offset map with simple text."""
        words = [
            OCRWord(text="one", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=40, height=20)),
            OCRWord(text="two", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=145, y=200, width=40, height=20)),
            OCRWord(text="three", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=190, y=200, width=60, height=20)),
        ]
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(pages=[page], full_text="one two three")
        
        matcher = EntityMatcher()
        offset_map = matcher._build_offset_map(ocr_result)
        
        # Should have mapped all three words
        assert len(offset_map) == 3
        
        # Check offsets
        assert offset_map[0].word.text == "one"
        assert offset_map[0].start_offset == 0
        assert offset_map[0].end_offset == 3
        
        assert offset_map[1].word.text == "two"
        assert offset_map[1].start_offset == 4
        assert offset_map[1].end_offset == 7
        
        assert offset_map[2].word.text == "three"
        assert offset_map[2].start_offset == 8
        assert offset_map[2].end_offset == 13
    
    def test_offset_map_with_newlines(self):
        """Test offset map correctly handles newlines."""
        words = [
            OCRWord(text="line1", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=200, width=50, height=20)),
            OCRWord(text="line2", confidence=0.99,
                   bounding_box=BoundingBox(page=1, x=100, y=230, width=50, height=20)),
        ]
        page = OCRPage(page_number=1, width=1000, height=1000, words=words)
        ocr_result = OCRResult(pages=[page], full_text="line1\nline2")
        
        matcher = EntityMatcher()
        offset_map = matcher._build_offset_map(ocr_result)
        
        assert len(offset_map) == 2
        assert offset_map[0].end_offset == 5
        assert offset_map[1].start_offset == 6  # After newline