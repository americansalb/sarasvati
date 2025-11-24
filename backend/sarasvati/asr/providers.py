"""
ASR Provider Abstraction Layer

Supports multiple ASR backends:
- Groq Whisper Large V3
- OpenAI gpt-4o-transcribe (Audio)
- OpenAI gpt-4o-mini-transcribe (Audio)
- OpenAI Whisper-1 (legacy)

Each provider implements the ASRProvider interface.
"""

from abc import ABC, abstractmethod
from typing import Optional, Literal
import httpx
import os


ASRBackend = Literal["groq", "openai-gpt4o-transcribe", "openai-gpt4o-mini-transcribe", "openai-whisper1"]


class ASRResult:
    """Standardized ASR result across all providers."""
    def __init__(
        self,
        text: str,
        duration: float,
        language: str = "unknown",
        error: Optional[str] = None,
        provider: str = "unknown",
    ):
        self.text = text
        self.duration = duration
        self.language = language
        self.error = error
        self.provider = provider


class ASRProvider(ABC):
    """Abstract base class for ASR providers."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    @abstractmethod
    async def transcribe(
        self,
        audio_data: bytes,
        filename: str,
        content_type: str,
        language: Optional[str] = None,
    ) -> ASRResult:
        """
        Transcribe audio data.

        Args:
            audio_data: Raw audio bytes
            filename: Original filename (e.g., "audio.webm")
            content_type: MIME type (e.g., "audio/webm")
            language: Optional language hint (ISO 639-1 code like "en", "es", "gu")
                     None or "auto" means auto-detect

        Returns:
            ASRResult with text, duration, language, and optional error
        """
        pass


class GroqProvider(ASRProvider):
    """Groq Whisper Large V3 provider."""

    async def transcribe(
        self,
        audio_data: bytes,
        filename: str,
        content_type: str,
        language: Optional[str] = None,
    ) -> ASRResult:
        """Transcribe using Groq Whisper Large V3."""
        whisper_data: dict = {"model": "whisper-large-v3", "response_format": "json"}
        if language and language != "auto":
            whisper_data["language"] = language

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"file": (filename, audio_data, content_type)},
                    data=whisper_data,
                    timeout=30.0,
                )

                if response.status_code != 200:
                    return ASRResult(
                        text="",
                        duration=0.0,
                        error=f"Groq API error: {response.text}",
                        provider="groq",
                    )

                result = response.json()
                return ASRResult(
                    text=result.get("text", "").strip(),
                    duration=result.get("duration", 0.0),
                    language=result.get("language", "unknown"),
                    provider="groq",
                )
            except Exception as e:
                return ASRResult(
                    text="",
                    duration=0.0,
                    error=f"Groq exception: {str(e)}",
                    provider="groq",
                )


class OpenAIProvider(ASRProvider):
    """OpenAI ASR provider (whisper-1 for /v1/audio/transcriptions)."""

    def __init__(self, api_key: str, model: str = "whisper-1"):
        super().__init__(api_key)
        self.model = model

    async def transcribe(
        self,
        audio_data: bytes,
        filename: str,
        content_type: str,
        language: Optional[str] = None,
    ) -> ASRResult:
        """Transcribe using OpenAI Audio API with medical context."""
        # OpenAI Audio API format
        data: dict = {
            "model": self.model,
            # Medical context prompt for better accuracy
            "prompt": (
                "This is a medical interview between a provider and a patient, "
                "with a professional interpreter. Transcribe accurately, "
                "preserving medical terminology and non-English words exactly."
            ),
        }
        if language and language != "auto":
            data["language"] = language

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"file": (filename, audio_data, content_type)},
                    data=data,
                    timeout=60.0,  # OpenAI can be slower
                )

                if response.status_code != 200:
                    return ASRResult(
                        text="",
                        duration=0.0,
                        error=f"OpenAI API error: {response.text}",
                        provider=f"openai-{self.model}",
                    )

                result = response.json()
                return ASRResult(
                    text=result.get("text", "").strip(),
                    duration=result.get("duration", 0.0),
                    language=result.get("language", "unknown"),
                    provider=f"openai-{self.model}",
                )
            except Exception as e:
                return ASRResult(
                    text="",
                    duration=0.0,
                    error=f"OpenAI exception: {str(e)}",
                    provider=f"openai-{self.model}",
                )


class ASRProviderFactory:
    """Factory to create ASR providers based on backend name."""

    @staticmethod
    def create(backend: ASRBackend, groq_key: str, openai_key: str) -> ASRProvider:
        """
        Create an ASR provider instance.

        Args:
            backend: ASR backend name
            groq_key: Groq API key
            openai_key: OpenAI API key

        Returns:
            ASRProvider instance
        """
        if backend == "groq":
            return GroqProvider(groq_key)
        elif backend in ["openai-gpt4o-transcribe", "openai-gpt4o-mini-transcribe", "openai-whisper1"]:
            # All OpenAI transcriptions use whisper-1 model for now
            # gpt-4o-audio models are for Realtime API, not transcriptions API
            return OpenAIProvider(openai_key, model="whisper-1")
        else:
            # Default to OpenAI
            return OpenAIProvider(openai_key, model="whisper-1")


class ASRConfig:
    """
    ASR configuration manager.

    Allows per-role, per-language ASR backend selection.
    """

    def __init__(self):
        # Default configuration - OpenAI gpt-4o-transcribe for all
        self.config = {
            "default": "openai-gpt4o-transcribe",
            "provider_en": "openai-gpt4o-transcribe",
            "patient_auto": "openai-gpt4o-transcribe",
            "interpreter_auto": "openai-gpt4o-transcribe",
        }

    def get_backend(self, role: str, language: str) -> ASRBackend:
        """
        Get ASR backend for a given role and language.

        Args:
            role: "provider", "patient", or "interpreter"
            language: Language code (e.g., "en", "es", "gu", "auto")

        Returns:
            ASR backend name
        """
        # Try specific role_language key first
        key = f"{role}_{language}"
        if key in self.config:
            return self.config[key]  # type: ignore

        # Try role-level default
        if role in self.config:
            return self.config[role]  # type: ignore

        # Fall back to global default
        return self.config.get("default", "groq")  # type: ignore

    def set_backend(self, role: str, language: str, backend: ASRBackend) -> None:
        """Set ASR backend for a role/language combination."""
        key = f"{role}_{language}"
        self.config[key] = backend

    def set_default(self, backend: ASRBackend) -> None:
        """Set global default ASR backend."""
        self.config["default"] = backend

    def get_all(self) -> dict:
        """Get all configuration."""
        return self.config.copy()

    def update(self, config: dict) -> None:
        """Update configuration from dictionary."""
        self.config.update(config)


# Global ASR configuration instance
asr_config = ASRConfig()
