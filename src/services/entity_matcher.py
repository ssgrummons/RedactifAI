"""
EntityMatcher - Core logic for mapping PHI entities to OCR bounding boxes.

This is the critical component that makes Redactify valuable. It solves the
fundamental problem: PHI detection gives us character offsets in text, but we
need pixel coordinates to mask the document.
"""

import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass
import Levenshtein

from src.models.domain import (
    OCRResult,
    OCRWord,
    PHIEntity,
    MaskRegion,
    BoundingBox,
)

logger = logging.getLogger(__name__)


@dataclass
class WordOffset:
    """
    Maps an OCR word to its character position in full_text.
    
    Attributes:
        word: The OCR word
        start_offset: Starting character position in full_text
        end_offset: Ending character position in full_text (exclusive)
    """
    word: OCRWord
    start_offset: int
    end_offset: int
    
    def contains_offset(self, offset: int) -> bool:
        """Check if this word contains a character offset."""
        return self.start_offset <= offset < self.end_offset
    
    def overlaps_range(self, start: int, end: int) -> bool:
        """Check if this word overlaps with a character range."""
        return not (self.end_offset <= start or end <= self.start_offset)


class EntityMatcher:
    """
    Maps PHI entities (character offsets) to OCR word bounding boxes.
    
    This matcher is robust to:
    - OCR errors (character misreads)
    - Whitespace inconsistencies
    - Multi-line entities
    - Page boundaries
    """
    
    def __init__(
        self,
        fuzzy_match_threshold: int = 2,
        confidence_threshold: float = 0.0,
        box_padding_px: int = 5,
    ):
        """
        Initialize the entity matcher.
        
        Args:
            fuzzy_match_threshold: Max Levenshtein distance for fuzzy matching.
                                   2 means up to 2 character differences allowed.
            confidence_threshold: Minimum confidence to mask an entity.
                                 Set to 0.0 to mask everything.
            box_padding_px: Extra padding to add around masked regions.
        """
        self.fuzzy_match_threshold = fuzzy_match_threshold
        self.confidence_threshold = confidence_threshold
        self.box_padding_px = box_padding_px
    
    def match_entities_to_boxes(
        self,
        ocr_result: OCRResult,
        phi_entities: List[PHIEntity],
    ) -> List[MaskRegion]:
        """
        Match PHI entities to bounding boxes for masking.
        
        Args:
            ocr_result: OCR results with word bounding boxes
            phi_entities: Detected PHI entities with character offsets
            
        Returns:
            List of mask regions to apply to the document
        """
        # Build character offset index from OCR words
        offset_map = self._build_offset_map(ocr_result)
        
        mask_regions = []
        for entity in phi_entities:
            # Skip low-confidence entities
            if entity.confidence < self.confidence_threshold:
                logger.debug(
                    f"Skipping low-confidence entity '{entity.text}' "
                    f"(confidence={entity.confidence:.2f})"
                )
                continue
            
            # Find OCR words that overlap with this entity
            overlapping_words = self._find_overlapping_words(
                entity, offset_map, ocr_result.full_text
            )
            
            if overlapping_words:
                # Group by page (entity might span multiple pages)
                words_by_page = self._group_by_page(overlapping_words)
                
                # Create one mask region per page
                for page_num, page_words in words_by_page.items():
                    merged_box = self._merge_bounding_boxes(page_words)
                    mask_regions.append(MaskRegion(
                        page=page_num,
                        bounding_box=merged_box,
                        entity_category=entity.category,
                        confidence=entity.confidence,
                    ))
            else:
                # Entity not found in OCR - this is a problem
                logger.warning(
                    f"Could not match entity '{entity.text}' (offset={entity.offset}, "
                    f"length={entity.length}) to any OCR words. Entity may be in "
                    f"an image or OCR quality is too poor."
                )
        
        return mask_regions
    
    def _build_offset_map(self, ocr_result: OCRResult) -> List[WordOffset]:
        """
        Build index mapping character offsets to OCR words.
        
        This is the critical function. It walks through full_text character by
        character and matches substrings to OCR words, building a map that
        handles whitespace inconsistencies.
        
        Strategy:
        1. Flatten all OCR words across all pages
        2. Walk through full_text, trying to match each word
        3. Track current offset position as we go
        4. Handle spaces/newlines by skipping whitespace in full_text
        
        Args:
            ocr_result: Complete OCR results
            
        Returns:
            List of WordOffset objects mapping words to character positions
        """
        full_text = ocr_result.full_text
        offset_map: List[WordOffset] = []
        
        # Flatten all words from all pages
        all_words = []
        for page in ocr_result.pages:
            all_words.extend(page.words)
        
        current_offset = 0
        word_index = 0
        
        while word_index < len(all_words) and current_offset < len(full_text):
            word = all_words[word_index]
            
            # Skip whitespace in full_text
            while current_offset < len(full_text) and full_text[current_offset].isspace():
                current_offset += 1
            
            if current_offset >= len(full_text):
                break
            
            # Try to find this word starting at current_offset
            word_text_normalized = word.text.strip()
            match_offset, match_length = self._find_word_in_text(
                full_text, word_text_normalized, current_offset
            )
            
            if match_offset is not None:
                # Found it - record the mapping
                offset_map.append(WordOffset(
                    word=word,
                    start_offset=match_offset,
                    end_offset=match_offset + match_length,
                ))
                current_offset = match_offset + match_length
                word_index += 1
            else:
                # Couldn't find this word - OCR error or text mismatch
                # Log and skip this word
                logger.debug(
                    f"Could not locate OCR word '{word.text}' in full_text "
                    f"starting at offset {current_offset}"
                )
                word_index += 1
        
        return offset_map
    
    def _find_word_in_text(
        self,
        text: str,
        word: str,
        start_offset: int,
    ) -> Tuple[Optional[int], int]:
        """
        Find a word in text starting at offset, with fuzzy matching tolerance.
        
        Args:
            text: The full text to search in
            word: The word to find (already normalized/stripped)
            start_offset: Where to start searching
            
        Returns:
            Tuple of (match_offset, match_length) or (None, 0) if not found
        """
        if not word:
            return None, 0
        
        # First try exact match
        word_len = len(word)
        if start_offset + word_len <= len(text):
            substring = text[start_offset:start_offset + word_len]
            if substring == word:
                return start_offset, word_len
        
        # Try fuzzy match in a small window (handle OCR errors)
        # Look at substring slightly longer than the word
        search_window = min(word_len + 5, len(text) - start_offset)
        if search_window > 0:
            substring = text[start_offset:start_offset + search_window]
            
            # Try matching with varying lengths around expected word length
            for length in range(max(1, word_len - 2), min(len(substring), word_len + 3)):
                candidate = substring[:length]
                
                # Skip if candidate is just whitespace
                if not candidate.strip():
                    continue
                
                # Calculate edit distance
                distance = Levenshtein.distance(word, candidate)
                
                # Accept if within threshold
                if distance <= self.fuzzy_match_threshold:
                    return start_offset, length
        
        return None, 0
    
    def _find_overlapping_words(
        self,
        entity: PHIEntity,
        offset_map: List[WordOffset],
        full_text: str,
    ) -> List[WordOffset]:
        """
        Find OCR words that overlap with entity character range.
        
        Args:
            entity: PHI entity with character offsets
            offset_map: Word offset mappings
            full_text: Original full text (for validation)
            
        Returns:
            List of WordOffset objects that overlap with the entity
        """
        overlapping = []
        
        for word_offset in offset_map:
            if word_offset.overlaps_range(entity.offset, entity.end_offset):
                overlapping.append(word_offset)
        
        # Validate that the overlapping words' text is similar to entity text
        # This prevents masking completely unrelated text when offsets coincidentally align
        if overlapping:
            # Concatenate the text from overlapping words
            combined_text = " ".join(wo.word.text for wo in overlapping)
            entity_text = entity.text.strip()
            
            # If texts are very different, reject this match
            # Use a more lenient threshold since we're comparing multi-word phrases
            max_distance = max(len(entity_text) // 3, self.fuzzy_match_threshold)
            distance = Levenshtein.distance(
                combined_text.lower(), 
                entity_text.lower()
            )
            
            if distance > max_distance:
                logger.debug(
                    f"Rejected offset match for entity '{entity_text}' - found "
                    f"'{combined_text}' at same offset but texts too different "
                    f"(distance={distance}, max={max_distance})"
                )
                overlapping = []
        
        # If we found nothing, try fuzzy search as a fallback
        # BUT only if the entity text appears somewhere in full_text
        # (this prevents matching completely unrelated text)
        if not overlapping and entity.text.lower() in full_text.lower():
            overlapping = self._fuzzy_search_for_entity(
                entity, offset_map, full_text
            )
        
        return overlapping
    
    def _fuzzy_search_for_entity(
        self,
        entity: PHIEntity,
        offset_map: List[WordOffset],
        full_text: str,
    ) -> List[WordOffset]:
        """
        Fallback: Try to find entity text in offset map using fuzzy matching.
        
        This is a last-resort when exact offset matching fails. We search for
        the entity text itself in the OCR words.
        
        Args:
            entity: PHI entity we're trying to locate
            offset_map: Word offset mappings
            full_text: Original full text
            
        Returns:
            List of WordOffset objects that might contain the entity
        """
        entity_text = entity.text.strip().lower()
        candidates = []
        
        # Look for words whose text is similar to the entity text
        for word_offset in offset_map:
            word_text = word_offset.word.text.strip().lower()
            
            # Check if this word is part of the entity
            if word_text in entity_text or entity_text in word_text:
                candidates.append(word_offset)
            elif Levenshtein.distance(word_text, entity_text) <= self.fuzzy_match_threshold:
                candidates.append(word_offset)
        
        if candidates:
            logger.info(
                f"Used fuzzy search to find {len(candidates)} words for "
                f"entity '{entity.text}' after offset matching failed"
            )
        
        return candidates
    
    def _group_by_page(
        self,
        word_offsets: List[WordOffset],
    ) -> dict[int, List[WordOffset]]:
        """
        Group words by page number.
        
        Args:
            word_offsets: List of word offsets to group
            
        Returns:
            Dictionary mapping page number to list of words on that page
        """
        by_page: dict[int, List[WordOffset]] = {}
        
        for word_offset in word_offsets:
            page = word_offset.word.bounding_box.page
            if page not in by_page:
                by_page[page] = []
            by_page[page].append(word_offset)
        
        return by_page
    
    def _merge_bounding_boxes(
        self,
        word_offsets: List[WordOffset],
    ) -> BoundingBox:
        """
        Merge multiple word boxes into single bounding box with padding.
        
        Takes min(x, y) and max(x+width, y+height) across all words, then
        adds padding on all sides.
        
        Args:
            word_offsets: Words to merge (must all be on same page)
            
        Returns:
            Single merged bounding box
        """
        if not word_offsets:
            raise ValueError("Cannot merge empty list of word offsets")
        
        # Get page from first word (all should be same page)
        page = word_offsets[0].word.bounding_box.page
        
        # Find bounding rectangle
        boxes = [wo.word.bounding_box for wo in word_offsets]
        
        min_x = min(box.x for box in boxes)
        min_y = min(box.y for box in boxes)
        max_x = max(box.x + box.width for box in boxes)
        max_y = max(box.y + box.height for box in boxes)
        
        # Add padding to all sides
        min_x = max(0, min_x - self.box_padding_px)
        min_y = max(0, min_y - self.box_padding_px)
        max_x = max_x + self.box_padding_px
        max_y = max_y + self.box_padding_px
        
        width = max_x - min_x
        height = max_y - min_y
        
        return BoundingBox(
            page=page,
            x=min_x,
            y=min_y,
            width=width,
            height=height,
        )