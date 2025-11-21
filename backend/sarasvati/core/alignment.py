"""
SARASVATI Alignment Engine
===========================
Dynamic Time Warping and Semantic Similarity for temporal alignment.

This module solves the "Alignment Problem": matching delayed interpreter speech
to the source provider speech using semantic similarity instead of timestamps.

Key Insight: We DO NOT compare Time(X) to Time(X). We use a sliding window
semantic search to find where the provider's concept appears in the interpreter stream.
"""

import numpy as np
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
import asyncio
import threading
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    SentenceTransformer = None

from .state import (
    TranscriptSegment,
    AlignmentMatch,
    BufferEntry,
    StreamRole,
    SarasvatiState,
)


@dataclass
class DTWConfig:
    """Configuration for Dynamic Time Warping alignment."""
    window_size_seconds: float = 30.0      # Search window for finding matches
    min_similarity_threshold: float = 0.35  # Lower threshold for cross-lingual matching
    max_time_delta: float = 45.0           # Maximum allowed delay (seconds)
    embedding_dim: int = 384               # Dimension of sentence embeddings
    use_semantic_vad: bool = True          # Use semantic boundaries, not silence
    penalty_gap: float = 0.1               # Penalty for gaps in DTW alignment


class AlignmentEngine:
    """
    Core alignment engine using DTW + Semantic Similarity.

    This class handles the critical task of matching Provider utterances to
    Interpreter utterances despite the 5-20 second delay.
    """

    def __init__(self, config: DTWConfig, use_real_embeddings: bool = True):
        self.config = config
        self._embedding_cache: dict = {}
        self.use_real_embeddings = use_real_embeddings
        self._model = None

        # Thread-safe cache lock
        self._cache_lock = threading.Lock()

        # ThreadPoolExecutor for CPU-bound work (embedding + DTW)
        self._executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="sarasvati_align"
        )

        # Load real embedding model if available and requested
        if use_real_embeddings and SENTENCE_TRANSFORMERS_AVAILABLE:
            print("🔄 Loading multilingual embedding model (paraphrase-multilingual-MiniLM-L12-v2)...")
            try:
                # MULTILINGUAL model - supports 50+ languages including Spanish, Gujarati
                # Same speed as English-only model but works cross-lingually
                self._model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
                print("✅ Multilingual embedding model loaded successfully")
                print("✅ ThreadPoolExecutor initialized (4 workers)")
            except Exception as e:
                print(f"⚠️  Failed to load embedding model: {e}")
                print("   Falling back to mock embeddings")
                self._model = None
        elif use_real_embeddings and not SENTENCE_TRANSFORMERS_AVAILABLE:
            print("⚠️  sentence-transformers not installed")
            print("   Install with: pip install sentence-transformers")
            print("   Falling back to mock embeddings (NOT suitable for production)")
            self._model = None
        else:
            print("ℹ️  Using mock embeddings (for testing/development only)")

    def __del__(self):
        """Cleanup: Shutdown executor on deletion."""
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=False)

    async def align_segments(
        self,
        provider_segment: TranscriptSegment,
        interpreter_buffer: List[BufferEntry],
        state: SarasvatiState,
    ) -> Optional[AlignmentMatch]:
        """
        Non-blocking async wrapper for alignment.

        CRITICAL: This method offloads CPU-bound work (embedding + DTW) to a
        ThreadPoolExecutor, preventing event loop blocking during matrix math.

        Per Sthiti's preservation: The Sudarshana Chakra (Event Loop) must keep
        spinning while heavy computation runs in worker threads.

        Args:
            provider_segment: The source segment from provider
            interpreter_buffer: FIFO buffer of interpreter segments
            state: Current graph state

        Returns:
            AlignmentMatch if found, None if no match in window
        """
        # Get the running event loop
        loop = asyncio.get_running_loop()

        # Offload the CPU-bound work to thread pool
        # This allows the event loop to continue processing ingestion
        # while the alignment math runs in a worker thread
        return await loop.run_in_executor(
            self._executor,
            self._align_segments_sync,
            provider_segment,
            interpreter_buffer,
        )

    def _align_segments_sync(
        self,
        provider_segment: TranscriptSegment,
        interpreter_buffer: List[BufferEntry],
    ) -> Optional[AlignmentMatch]:
        """
        Synchronous implementation of alignment logic.

        ALL CPU-bound work happens here (embeddings, DTW, scoring).
        This runs in a worker thread, NOT the main event loop.

        This is the core method that implements the Trisul alignment logic:
        1. Define a search window based on expected delay
        2. Compute semantic embeddings for provider segment
        3. Search interpreter buffer for semantic matches
        4. Use DTW to find optimal alignment
        5. Validate with negation-aware similarity check

        Args:
            provider_segment: The source segment from provider
            interpreter_buffer: FIFO buffer of interpreter segments

        Returns:
            AlignmentMatch if found, None if no match in window
        """
        # Step 1: Define temporal search window
        search_start = provider_segment["timestamp"]
        search_end = search_start + self.config.window_size_seconds

        # Step 2: Filter interpreter segments within the window
        candidate_segments = self._get_candidates_in_window(
            interpreter_buffer,
            search_start,
            search_end,
        )

        if not candidate_segments:
            return None

        # Step 3: Get embedding for provider segment (SYNC - no await!)
        provider_embedding = self._get_embedding(provider_segment["text"])

        # Step 4: Compute similarities for all candidates
        # Track: (candidate, raw_similarity, time_delta, combined_score, dtw_distance)
        best_match: Optional[Tuple[TranscriptSegment, float, float, float, float]] = None
        best_combined_score = -1.0

        for candidate in candidate_segments:
            interpreter_embedding = self._get_embedding(candidate["text"])

            # Cosine similarity
            similarity = self._cosine_similarity(
                provider_embedding,
                interpreter_embedding,
            )

            # DTW distance for temporal alignment
            dtw_dist = self._compute_dtw_distance(
                provider_segment,
                candidate,
            )

            # Combined score (weighted: 0.7 semantic, 0.3 temporal)
            # This is the TRUTH VECTOR per the architectural bible
            combined_score = (0.7 * similarity) + (0.3 * (1.0 - dtw_dist))

            if combined_score > best_combined_score:
                best_combined_score = combined_score
                time_delta = candidate["timestamp"] - provider_segment["timestamp"]
                best_match = (candidate, similarity, time_delta, combined_score, dtw_dist)

        # Step 5: Validate match against threshold
        # CRITICAL FIX: Threshold on combined_score, not raw similarity
        if best_match and best_match[3] >= self.config.min_similarity_threshold:
            interpreter_seg, raw_similarity, time_delta, combined_score, dtw_dist = best_match

            # Check for negation mismatches (critical!)
            has_negation_mismatch = self._check_negation_mismatch(
                provider_segment["text"],
                interpreter_seg["text"],
            )

            # If negation mismatch detected, apply severe penalty to COMBINED score
            if has_negation_mismatch:
                combined_score *= 0.3  # Severe penalty for negation errors
                raw_similarity *= 0.3  # Also penalize raw for consistency

            return AlignmentMatch(
                provider_segment=provider_segment,
                interpreter_segment=interpreter_seg,
                similarity_score=raw_similarity,      # Raw cosine similarity (for debugging)
                combined_score=combined_score,        # Truth vector (for decision-making)
                time_delta=time_delta,
                is_matched=True,
                dtw_distance=dtw_dist,
            )

        # No match found in window
        return AlignmentMatch(
            provider_segment=provider_segment,
            interpreter_segment=None,
            similarity_score=0.0,
            combined_score=0.0,
            time_delta=0.0,
            is_matched=False,
            dtw_distance=float("inf"),
        )

    def _get_candidates_in_window(
        self,
        buffer: List[BufferEntry],
        start_time: float,
        end_time: float,
    ) -> List[TranscriptSegment]:
        """Extract segments from buffer within the temporal search window."""
        candidates = []
        for entry in buffer:
            segment = entry["segment"]
            seg_time = segment["timestamp"]

            # Check if segment falls within search window
            if start_time <= seg_time <= end_time:
                # Only consider final transcripts, not interim
                if segment["is_final"]:
                    candidates.append(segment)

        return candidates

    def _get_embedding(self, text: str) -> np.ndarray:
        """
        Thread-safe embedding retrieval.

        - Lock only around cache access.
        - Run model encoding outside the lock for parallelism.
        """
        cache_key = hash(text)

        # Fast path: locked read
        with self._cache_lock:
            cached = self._embedding_cache.get(cache_key)
        if cached is not None:
            return cached

        # Compute embedding without holding the lock
        if self._model is not None:
            embedding = self._model.encode(text, convert_to_numpy=True)
        else:
            embedding = self._mock_embedding(text)

        # Store result under lock
        with self._cache_lock:
            self._embedding_cache[cache_key] = embedding

        return embedding

    def _mock_embedding(self, text: str) -> np.ndarray:
        """
        Mock embedding for development/testing.

        Creates a deterministic embedding based on text features:
        - Word frequency
        - Character n-grams
        - Medical keyword presence

        TODO: Replace with actual sentence-transformers model in production!
        """
        # Initialize random state with text hash for determinism
        rng = np.random.RandomState(seed=hash(text) % (2**32))

        # Base embedding from pseudo-random distribution
        embedding = rng.randn(self.config.embedding_dim).astype(np.float32)

        # Add features based on medical keywords
        medical_keywords = {
            "medication": 0, "dosage": 1, "fever": 2, "pain": 3,
            "prescription": 4, "treatment": 5, "diagnosis": 6,
            "symptom": 7, "allergy": 8, "no": 9, "not": 10,
        }

        text_lower = text.lower()
        for keyword, idx in medical_keywords.items():
            if keyword in text_lower:
                # Boost specific dimensions for keyword presence
                if idx < self.config.embedding_dim:
                    embedding[idx] += 2.0

        # Normalize to unit vector
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

        return embedding

    def _cosine_similarity(
        self,
        vec1: np.ndarray,
        vec2: np.ndarray,
    ) -> float:
        """
        Compute cosine similarity between two embedding vectors.

        Args:
            vec1: First embedding vector
            vec2: Second embedding vector

        Returns:
            Similarity score in range [-1, 1] (typically [0, 1] for normalized vectors)
        """
        # Ensure vectors are normalized
        vec1_norm = vec1 / (np.linalg.norm(vec1) + 1e-8)
        vec2_norm = vec2 / (np.linalg.norm(vec2) + 1e-8)

        # Compute dot product
        similarity = float(np.dot(vec1_norm, vec2_norm))

        # Clamp to [0, 1] range
        return max(0.0, min(1.0, similarity))

    def _compute_dtw_distance(
        self,
        seg1: TranscriptSegment,
        seg2: TranscriptSegment,
    ) -> float:
        """
        Compute Dynamic Time Warping distance for temporal alignment.

        This is a simplified DTW implementation for character-level alignment.
        In production, you might use word-level or phoneme-level DTW.

        Args:
            seg1: First transcript segment
            seg2: Second transcript segment

        Returns:
            Normalized DTW distance in range [0, 1]
        """
        s1 = seg1["text"].lower().split()
        s2 = seg2["text"].lower().split()

        n, m = len(s1), len(s2)

        # Handle edge cases
        if n == 0 or m == 0:
            return 1.0

        # Initialize DTW matrix
        dtw = np.zeros((n + 1, m + 1))
        dtw[0, :] = np.inf
        dtw[:, 0] = np.inf
        dtw[0, 0] = 0

        # Fill DTW matrix
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                # Cost: 0 if words match, 1 otherwise
                cost = 0.0 if s1[i - 1] == s2[j - 1] else 1.0

                # Take minimum of three paths
                dtw[i, j] = cost + min(
                    dtw[i - 1, j],      # Insertion
                    dtw[i, j - 1],      # Deletion
                    dtw[i - 1, j - 1],  # Match
                )

        # Normalize by path length
        distance = dtw[n, m] / max(n, m)

        return min(1.0, distance)

    def _check_negation_mismatch(
        self,
        provider_text: str,
        interpreter_text: str,
    ) -> bool:
        """
        Critical safety check: Detect negation mismatches.

        This is essential for medical safety. Examples:
        - Provider: "No fever" vs Interpreter: "Fever" → CRITICAL ERROR
        - Provider: "Not allergic" vs Interpreter: "Allergic" → CRITICAL ERROR

        Uses a rule-based approach with negation word detection.
        In production, consider using a cross-encoder model for better accuracy.

        Args:
            provider_text: Source text from provider
            interpreter_text: Translated text from interpreter

        Returns:
            True if negation mismatch detected, False otherwise
        """
        negation_words = {
            "no", "not", "never", "none", "nothing", "nowhere",
            "neither", "nobody", "cannot", "can't", "won't", "don't",
            "doesn't", "didn't", "isn't", "aren't", "wasn't", "weren't",
            "sin", "ningún", "ninguna", "nunca", "jamás",  # Spanish negations
        }

        provider_lower = provider_text.lower()
        interpreter_lower = interpreter_text.lower()

        # Count negation words in each text
        provider_negations = sum(
            1 for word in negation_words
            if f" {word} " in f" {provider_lower} "
        )
        interpreter_negations = sum(
            1 for word in negation_words
            if f" {word} " in f" {interpreter_lower} "
        )

        # Check for negation polarity mismatch
        # If one has negation and the other doesn't, flag it
        provider_is_negated = provider_negations > 0
        interpreter_is_negated = interpreter_negations > 0

        return provider_is_negated != interpreter_is_negated


class BatchAligner:
    """
    Batch processing for alignment when buffer exceeds threshold.

    This class handles bulk alignment of buffered segments to prevent
    memory buildup and ensure low latency.
    """

    def __init__(self, engine: AlignmentEngine):
        self.engine = engine

    async def process_buffer_batch(
        self,
        state: SarasvatiState,
    ) -> List[AlignmentMatch]:
        """
        Process a batch of provider segments against interpreter buffer.

        This is called when buffer size exceeds threshold or on a timer.

        Args:
            state: Current graph state with buffers

        Returns:
            List of alignment matches found
        """
        alignments: List[AlignmentMatch] = []

        # Get unprocessed provider entries
        unprocessed = [
            entry for entry in state["provider_buffer"]
            if not entry["is_processed"]
        ]

        # CRITICAL: snapshot interpreter buffer once per batch
        interpreter_snapshot = list(state["interpreter_buffer"])

        for entry in unprocessed:
            provider_segment = entry["segment"]

            # Try to align this segment against the snapshot
            alignment = await self.engine.align_segments(
                provider_segment,
                interpreter_snapshot,
                state,
            )

            if alignment:
                alignments.append(alignment)

                # Mark as processed if match found
                if alignment["is_matched"]:
                    entry["is_processed"] = True
                else:
                    # Increment attempt counter
                    entry["alignment_attempts"] += 1

                    # If too many attempts, mark as processed anyway (timeout)
                    if entry["alignment_attempts"] >= 5:
                        entry["is_processed"] = True

        return alignments


# Factory function for easy initialization
def create_alignment_engine(
    window_seconds: float = 30.0,
    similarity_threshold: float = 0.65,
) -> AlignmentEngine:
    """
    Factory to create configured alignment engine.

    Args:
        window_seconds: Search window size
        similarity_threshold: Minimum similarity for match

    Returns:
        Configured AlignmentEngine instance
    """
    config = DTWConfig(
        window_size_seconds=window_seconds,
        min_similarity_threshold=similarity_threshold,
    )
    return AlignmentEngine(config)
