"""
Speaker Diarization Service using pyannote-audio.

Uses neural network-based voice embeddings to identify unique speakers
based on their voice characteristics (pitch, timbre, speaking patterns).

This replaces the naive pause-based speaker detection with proper
voice fingerprinting.
"""

import os
import tempfile
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple
import asyncio
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Thread pool for CPU-bound diarization (pyannote uses PyTorch)
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
    method: str  # "pyannote" or "fallback"


class SpeakerDiarizer:
    """
    Speaker diarization using pyannote-audio neural embeddings.

    Uses voice characteristics (pitch, timbre, speaking patterns) as
    fingerprints to identify unique speakers, rather than relying on
    pause duration which fails when speakers talk in rapid succession.

    Requirements:
    - pyannote.audio>=3.1.0
    - torchaudio>=2.0.0
    - Hugging Face token (HF_TOKEN env var) for model access

    Falls back to pause-based detection if pyannote unavailable.
    """

    _pipeline = None
    _initialized = False
    _init_error = None

    @classmethod
    def _init_pipeline(cls):
        """Initialize pyannote pipeline (lazy loading)."""
        if cls._initialized:
            return cls._pipeline is not None

        cls._initialized = True

        try:
            from pyannote.audio import Pipeline
            import torch

            # Get Hugging Face token for model access
            hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
            if not hf_token:
                logger.warning(
                    "⚠️ No HF_TOKEN found. Speaker diarization requires a Hugging Face token. "
                    "Get one at https://huggingface.co/settings/tokens and accept the model license at "
                    "https://huggingface.co/pyannote/speaker-diarization-3.1"
                )
                cls._init_error = "Missing HF_TOKEN"
                return False

            # Load the speaker diarization pipeline
            # Uses pyannote/speaker-diarization-3.1 (state-of-the-art)
            logger.info("🔊 Loading pyannote speaker diarization pipeline...")

            cls._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=hf_token,
            )

            # Move to GPU if available
            if torch.cuda.is_available():
                cls._pipeline.to(torch.device("cuda"))
                logger.info("✅ Pyannote pipeline loaded (GPU)")
            else:
                logger.info("✅ Pyannote pipeline loaded (CPU)")

            return True

        except ImportError as e:
            logger.warning(f"⚠️ pyannote.audio not installed: {e}")
            cls._init_error = f"Import error: {e}"
            return False
        except Exception as e:
            logger.warning(f"⚠️ Failed to load pyannote pipeline: {e}")
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

        # Try to initialize pipeline
        if not cls._init_pipeline():
            logger.warning(f"⚠️ Falling back to pause-based detection: {cls._init_error}")
            return cls._fallback_diarization(audio_data)

        # Write audio to temp file (pyannote requires file path)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name
            f.write(audio_data)

        try:
            import torchaudio

            # Load audio info for duration
            waveform, sample_rate = torchaudio.load(temp_path)
            duration = waveform.shape[1] / sample_rate

            # Run diarization
            logger.info(f"🔊 Running speaker diarization on {duration:.1f}s audio...")

            # Configure speaker count hints
            if num_speakers is not None:
                diarization = cls._pipeline(
                    temp_path,
                    num_speakers=num_speakers,
                )
            else:
                diarization = cls._pipeline(
                    temp_path,
                    min_speakers=min_speakers,
                    max_speakers=max_speakers,
                )

            # Convert pyannote output to our format
            segments = []
            speaker_mapping = {}  # Map pyannote speaker IDs to speaker_1, speaker_2, etc.

            for turn, _, speaker in diarization.itertracks(yield_label=True):
                # Map speaker ID to consistent format
                if speaker not in speaker_mapping:
                    speaker_mapping[speaker] = f"speaker_{len(speaker_mapping) + 1}"

                segment = DiarizedSegment(
                    speaker_id=speaker_mapping[speaker],
                    start_time=turn.start,
                    end_time=turn.end,
                    confidence=1.0,  # pyannote doesn't provide per-segment confidence
                )
                segments.append(segment)

            # Sort by start time
            segments.sort(key=lambda s: s.start_time)

            # Merge very short gaps (< 0.3s) between same speaker
            merged_segments = cls._merge_adjacent_segments(segments)

            num_detected = len(speaker_mapping)
            logger.info(f"✅ Diarization complete: {num_detected} speakers, {len(merged_segments)} segments")

            return DiarizationResult(
                segments=merged_segments,
                num_speakers=num_detected,
                duration=duration,
                method="pyannote",
            )

        except Exception as e:
            logger.error(f"❌ Diarization failed: {e}")
            return cls._fallback_diarization(audio_data)
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except:
                pass

    @classmethod
    def _merge_adjacent_segments(
        cls,
        segments: List[DiarizedSegment],
        max_gap: float = 0.3,
    ) -> List[DiarizedSegment]:
        """Merge adjacent segments from same speaker with small gaps."""
        if not segments:
            return segments

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
        Fallback to basic diarization when pyannote unavailable.

        This is a placeholder that returns a single speaker.
        The actual transcription endpoint should use Whisper's segments
        and apply basic heuristics.
        """
        logger.warning("⚠️ Using fallback diarization (single speaker assumed)")

        # Return a single segment covering the whole audio
        # The actual segmentation will be done by Whisper
        return DiarizationResult(
            segments=[
                DiarizedSegment(
                    speaker_id="speaker_1",
                    start_time=0.0,
                    end_time=0.0,  # Will be updated by caller
                    confidence=0.5,  # Low confidence for fallback
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
    if diarization.method == "fallback":
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
            best_speaker = "speaker_1"  # Default if no overlap found

        aligned.append((wseg, best_speaker))

    return aligned
