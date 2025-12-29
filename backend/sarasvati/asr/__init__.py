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

# Diarization imports are lazy - only import when needed
# This prevents server crash if resemblyzer isn't installed

__all__ = [
    "ASRProvider",
    "ASRResult",
    "ASRBackend",
    "ASRProviderFactory",
    "ASRConfig",
    "asr_config",
    "GroqProvider",
    "OpenAIProvider",
]
