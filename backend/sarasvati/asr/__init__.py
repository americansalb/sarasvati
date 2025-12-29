"""ASR (Automatic Speech Recognition) module."""

from .providers import (
    ASRProvider,
    ASRResult,
    ASRBackend,
    ASRProviderFactory,
    ASRConfig,
    asr_config,
    GroqProvider,
    OpenAIProvider,
)
from .diarization import (
    SpeakerDiarizer,
    DiarizedSegment,
    DiarizationResult,
    align_transcription_with_diarization,
)

__all__ = [
    "ASRProvider",
    "ASRResult",
    "ASRBackend",
    "ASRProviderFactory",
    "ASRConfig",
    "asr_config",
    "GroqProvider",
    "OpenAIProvider",
    "SpeakerDiarizer",
    "DiarizedSegment",
    "DiarizationResult",
    "align_transcription_with_diarization",
]
