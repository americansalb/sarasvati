"""
Speaker Diarization Service using Resemblyzer (FREE, no API key).

Uses neural network-based voice embeddings to identify unique speakers
based on their voice characteristics (pitch, timbre, speaking patterns).

This replaces the naive pause-based speaker detection with proper
voice fingerprinting using Resemblyzer's d-vector embeddings.

No API keys or paid services required.
"""

import os
import tempfile
import logging
import io
from dataclasses import dataclass
from typing import List, Optional, Tuple
import asyncio
from concurrent.futures import ThreadPoolExecutor

import numpy as np

logger = logging.getLogger(__name__)

# Thread pool for CPU-bound diarization
_executor = ThreadPoolExecutor(max_workers=2)


@dataclass
class DiarizedSegment:
    """A segment with speaker identification based on voice embedding."""
    speaker_id: str  # "speaker_1", "speaker_2", etc.
    start_time: float
    end_time: float
    confidence: float = 1.0


@dataclass
class DiarizationResult:
    """Result from speaker diarization."""
    segments: List[DiarizedSegment]
    num_speakers: int
    duration: float
    method: str  # "resemblyzer" or "fallback"


class SpeakerDiarizer:
    """
    Speaker diarization using Resemblyzer voice embeddings (FREE).

    Uses d-vector embeddings to create voice "fingerprints" for each speaker.
    No API keys, no paid services, runs entirely locally.

    Requirements:
    - resemblyzer (pip install resemblyzer)
    - librosa (for audio processing)
    - scikit-learn (for clustering)

    Falls back to pause-based detection if dependencies unavailable.
    """

    _encoder = None
    _initialized = False
    _init_error = None

    @classmethod
    def _init_encoder(cls):
        """Initialize Resemblyzer encoder (lazy loading)."""
        if cls._initialized:
            return cls._encoder is not None

        cls._initialized = True

        try:
            from resemblyzer import VoiceEncoder

            logger.info("🔊 Loading Resemblyzer voice encoder (FREE, no API key)...")
            cls._encoder = VoiceEncoder()
            logger.info("✅ Resemblyzer encoder loaded successfully")
            return True

        except ImportError as e:
            logger.warning(f"⚠️ Resemblyzer not installed: {e}")
            logger.warning("   Install with: pip install resemblyzer librosa")
            cls._init_error = f"Import error: {e}"
            return False
        except Exception as e:
            logger.warning(f"⚠️ Failed to load Resemblyzer: {e}")
            cls._init_error = str(e)
            return False

    @classmethod
    async def diarize(
        cls,
        audio_data: bytes,
        num_speakers: Optional[int] = None,
        min_speakers: int = 2,
        max_speakers: int = 4,
    ) -> DiarizationResult:
        """
        Perform speaker diarization on audio data.

        Args:
            audio_data: Raw audio bytes (wav, mp3, webm, etc.)
            num_speakers: Exact number of speakers (if known)
            min_speakers: Minimum expected speakers (default: 2)
            max_speakers: Maximum expected speakers (default: 4)

        Returns:
            DiarizationResult with speaker segments and metadata
        """
        # Run diarization in thread pool (CPU-bound)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _executor,
            cls._diarize_sync,
            audio_data,
            num_speakers,
            min_speakers,
            max_speakers,
        )

    @classmethod
    def _diarize_sync(
        cls,
        audio_data: bytes,
        num_speakers: Optional[int],
        min_speakers: int,
        max_speakers: int,
    ) -> DiarizationResult:
        """Synchronous diarization (runs in thread pool)."""

        # Try to initialize encoder
        if not cls._init_encoder():
            logger.warning(f"⚠️ Falling back to pause-based detection: {cls._init_error}")
            return cls._fallback_diarization(audio_data)

        try:
            import librosa
            from sklearn.cluster import SpectralClustering, AgglomerativeClustering
            from resemblyzer import preprocess_wav
        except ImportError as e:
            logger.warning(f"⚠️ Missing dependency: {e}")
            return cls._fallback_diarization(audio_data)

        # Write audio to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name
            f.write(audio_data)

        try:
            # Load and preprocess audio
            logger.info("🔊 Loading audio for diarization...")
            wav, sr = librosa.load(temp_path, sr=16000)
            duration = len(wav) / sr

            if duration < 1.0:
                logger.warning("⚠️ Audio too short for diarization")
                return DiarizationResult(
                    segments=[DiarizedSegment("speaker_1", 0, duration)],
                    num_speakers=1,
                    duration=duration,
                    method="resemblyzer",
                )

            # Preprocess for Resemblyzer
            wav_preprocessed = preprocess_wav(temp_path)

            # Segment audio into chunks for embedding
            # Use overlapping windows for better accuracy
            segment_duration = 1.5  # seconds per segment
            hop_duration = 0.75  # hop between segments
            segment_samples = int(segment_duration * sr)
            hop_samples = int(hop_duration * sr)

            segments_info = []  # (start_time, end_time, embedding)

            for start_sample in range(0, len(wav_preprocessed) - segment_samples // 2, hop_samples):
                end_sample = min(start_sample + segment_samples, len(wav_preprocessed))
                segment_wav = wav_preprocessed[start_sample:end_sample]

                # Skip silent segments
                if np.abs(segment_wav).mean() < 0.01:
                    continue

                # Get embedding for this segment
                try:
                    embedding = cls._encoder.embed_utterance(segment_wav)
                    start_time = start_sample / sr
                    end_time = end_sample / sr
                    segments_info.append((start_time, end_time, embedding))
                except Exception as e:
                    logger.debug(f"Skipping segment: {e}")
                    continue

            if len(segments_info) < 2:
                logger.warning("⚠️ Not enough voiced segments for clustering")
                return DiarizationResult(
                    segments=[DiarizedSegment("speaker_1", 0, duration)],
                    num_speakers=1,
                    duration=duration,
                    method="resemblyzer",
                )

            # Stack embeddings for clustering
            embeddings = np.array([s[2] for s in segments_info])

            # Determine number of clusters
            if num_speakers is not None:
                n_clusters = num_speakers
            else:
                # Estimate from embedding similarity
                n_clusters = cls._estimate_num_speakers(
                    embeddings, min_speakers, max_speakers
                )

            logger.info(f"🔊 Clustering {len(embeddings)} segments into {n_clusters} speakers...")

            # Cluster embeddings using Agglomerative Clustering
            # (more robust than spectral for small datasets)
            if len(embeddings) >= n_clusters:
                clustering = AgglomerativeClustering(
                    n_clusters=n_clusters,
                    metric="cosine",
                    linkage="average",
                )
                labels = clustering.fit_predict(embeddings)
            else:
                labels = [0] * len(embeddings)

            # Build diarized segments
            diarized_segments = []
            for i, (start_time, end_time, _) in enumerate(segments_info):
                speaker_id = f"speaker_{labels[i] + 1}"
                diarized_segments.append(DiarizedSegment(
                    speaker_id=speaker_id,
                    start_time=start_time,
                    end_time=end_time,
                    confidence=0.8,
                ))

            # Merge adjacent segments from same speaker
            merged = cls._merge_adjacent_segments(diarized_segments)

            unique_speakers = len(set(labels))
            logger.info(f"✅ Diarization complete: {unique_speakers} speakers, {len(merged)} segments")

            return DiarizationResult(
                segments=merged,
                num_speakers=unique_speakers,
                duration=duration,
                method="resemblyzer",
            )

        except Exception as e:
            logger.error(f"❌ Diarization failed: {e}")
            import traceback
            traceback.print_exc()
            return cls._fallback_diarization(audio_data)
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except:
                pass

    @classmethod
    def _estimate_num_speakers(
        cls,
        embeddings: np.ndarray,
        min_speakers: int,
        max_speakers: int,
    ) -> int:
        """
        Estimate number of speakers from embedding similarity.

        Uses the eigenvalue gap heuristic from spectral clustering.
        """
        from sklearn.metrics.pairwise import cosine_similarity

        # Compute similarity matrix
        sim_matrix = cosine_similarity(embeddings)

        # Convert to affinity (0-1 range)
        affinity = (sim_matrix + 1) / 2

        # Compute eigenvalues
        eigenvalues = np.linalg.eigvalsh(affinity)
        eigenvalues = np.sort(eigenvalues)[::-1]  # Descending

        # Find largest gap in top eigenvalues
        gaps = []
        for k in range(min_speakers, min(max_speakers + 1, len(eigenvalues))):
            if k < len(eigenvalues):
                gap = eigenvalues[k - 1] - eigenvalues[k]
                gaps.append((k, gap))

        if gaps:
            # Return k with largest gap
            best_k = max(gaps, key=lambda x: x[1])[0]
            return best_k

        return min_speakers

    @classmethod
    def _merge_adjacent_segments(
        cls,
        segments: List[DiarizedSegment],
        max_gap: float = 0.5,
    ) -> List[DiarizedSegment]:
        """Merge adjacent segments from same speaker with small gaps."""
        if not segments:
            return segments

        # Sort by start time
        segments = sorted(segments, key=lambda s: s.start_time)
        merged = [segments[0]]

        for seg in segments[1:]:
            last = merged[-1]

            # Same speaker and small gap -> merge
            if seg.speaker_id == last.speaker_id and (seg.start_time - last.end_time) < max_gap:
                merged[-1] = DiarizedSegment(
                    speaker_id=last.speaker_id,
                    start_time=last.start_time,
                    end_time=seg.end_time,
                    confidence=min(last.confidence, seg.confidence),
                )
            else:
                merged.append(seg)

        return merged

    @classmethod
    def _fallback_diarization(cls, audio_data: bytes) -> DiarizationResult:
        """
        Fallback to basic diarization when Resemblyzer unavailable.

        Returns a single speaker - actual segmentation done by Whisper.
        """
        logger.warning("⚠️ Using fallback diarization (single speaker assumed)")

        return DiarizationResult(
            segments=[
                DiarizedSegment(
                    speaker_id="speaker_1",
                    start_time=0.0,
                    end_time=0.0,
                    confidence=0.5,
                )
            ],
            num_speakers=1,
            duration=0.0,
            method="fallback",
        )


def align_transcription_with_diarization(
    whisper_segments: List[dict],
    diarization: DiarizationResult,
) -> List[Tuple[dict, str]]:
    """
    Align Whisper transcription segments with speaker diarization.

    Each Whisper segment gets assigned to the speaker who was talking
    during the majority of that segment.

    Args:
        whisper_segments: Segments from Whisper with start/end times
        diarization: Speaker diarization result

    Returns:
        List of (whisper_segment, speaker_id) tuples
    """
    if diarization.method == "fallback" or not diarization.segments:
        # Fallback: all segments get speaker_1
        return [(seg, "speaker_1") for seg in whisper_segments]

    aligned = []

    for wseg in whisper_segments:
        seg_start = wseg.get("start", 0.0)
        seg_end = wseg.get("end", 0.0)
        seg_duration = seg_end - seg_start

        if seg_duration <= 0:
            aligned.append((wseg, "speaker_1"))
            continue

        # Calculate overlap with each speaker
        speaker_overlaps = {}

        for dseg in diarization.segments:
            # Calculate overlap
            overlap_start = max(seg_start, dseg.start_time)
            overlap_end = min(seg_end, dseg.end_time)
            overlap = max(0, overlap_end - overlap_start)

            if overlap > 0:
                speaker_overlaps[dseg.speaker_id] = (
                    speaker_overlaps.get(dseg.speaker_id, 0) + overlap
                )

        # Assign to speaker with most overlap
        if speaker_overlaps:
            best_speaker = max(speaker_overlaps, key=speaker_overlaps.get)
        else:
            # No overlap - find nearest speaker segment
            best_speaker = "speaker_1"
            min_distance = float("inf")
            seg_mid = (seg_start + seg_end) / 2

            for dseg in diarization.segments:
                dseg_mid = (dseg.start_time + dseg.end_time) / 2
                distance = abs(seg_mid - dseg_mid)
                if distance < min_distance:
                    min_distance = distance
                    best_speaker = dseg.speaker_id

        aligned.append((wseg, best_speaker))

    return aligned
