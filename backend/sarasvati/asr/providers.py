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


class EnsembleASR:
    """
    Multi-model ASR using tribunal pattern.

    Runs both Groq Whisper Large V3 and OpenAI Whisper-1 in parallel,
    then uses consensus logic to pick the best transcription.

    Philosophy: Greater than the sum of their parts - just like the tribunal!
    """

    @staticmethod
    async def transcribe_ensemble(
        audio_data: bytes,
        filename: str,
        content_type: str,
        language: Optional[str],
        groq_key: str,
        openai_key: str,
        expected_scripts: Optional[list[str]] = None,
    ) -> ASRResult:
        """
        Run both Groq and OpenAI in parallel, pick the best result.

        Consensus strategies:
        1. Exact agreement → high confidence
        2. High similarity (>80%) → use Groq (larger model)
        3. Script validation → pick one with correct script
        4. Length check → avoid empty results
        5. Default → Groq (Whisper Large V3 > V1)
        """
        import asyncio

        groq_provider = GroqProvider(groq_key)
        openai_provider = OpenAIProvider(openai_key, model="whisper-1")

        # Run both in parallel
        groq_result, openai_result = await asyncio.gather(
            groq_provider.transcribe(audio_data, filename, content_type, language),
            openai_provider.transcribe(audio_data, filename, content_type, language),
            return_exceptions=True,
        )

        # Handle exceptions
        if isinstance(groq_result, Exception):
            print(f"   ⚠️ Groq failed: {str(groq_result)}")
            groq_result = ASRResult("", 0.0, error=str(groq_result), provider="groq")
        if isinstance(openai_result, Exception):
            print(f"   ⚠️ OpenAI failed: {str(openai_result)}")
            openai_result = ASRResult("", 0.0, error=str(openai_result), provider="openai")

        # Both failed?
        if groq_result.error and openai_result.error:
            return ASRResult(
                text="",
                duration=0.0,
                error=f"Both failed: Groq={groq_result.error}, OpenAI={openai_result.error}",
                provider="ensemble-failed",
            )

        # One failed? Use the other
        if groq_result.error:
            print(f"   ✅ Using OpenAI (Groq failed)")
            openai_result.provider = "ensemble-openai-fallback"
            return openai_result
        if openai_result.error:
            print(f"   ✅ Using Groq (OpenAI failed)")
            groq_result.provider = "ensemble-groq-fallback"
            return groq_result

        # Both succeeded - apply consensus logic
        print(f"   🤝 Ensemble debate:")
        print(f"      Groq:   '{groq_result.text[:50]}...' (len={len(groq_result.text)}, lang={groq_result.language})")
        print(f"      OpenAI: '{openai_result.text[:50]}...' (len={len(openai_result.text)}, lang={openai_result.language})")

        # Strategy 1: Exact agreement (consensus!)
        if groq_result.text.lower().strip() == openai_result.text.lower().strip():
            print(f"   ✅ CONSENSUS: Both providers agree!")
            groq_result.provider = "ensemble-consensus"
            return groq_result

        # Strategy 2: High similarity
        groq_words = set(groq_result.text.lower().split())
        openai_words = set(openai_result.text.lower().split())
        if groq_words and openai_words:
            similarity = len(groq_words & openai_words) / max(len(groq_words), len(openai_words))
            if similarity > 0.8:
                print(f"   ✅ HIGH AGREEMENT ({similarity:.0%}) - using Groq (larger model)")
                groq_result.provider = "ensemble-high-agreement"
                return groq_result
            print(f"   ⚠️ DISAGREEMENT (similarity={similarity:.0%})")

        # Strategy 3: Script validation (for Gujarati, Hindi, Arabic, etc.)
        if expected_scripts:
            groq_script = EnsembleASR._detect_script(groq_result.text)
            openai_script = EnsembleASR._detect_script(openai_result.text)

            groq_valid = groq_script in expected_scripts
            openai_valid = openai_script in expected_scripts

            print(f"      Scripts: Groq={groq_script} {'✓' if groq_valid else '✗'}, OpenAI={openai_script} {'✓' if openai_valid else '✗'}")

            if groq_valid and not openai_valid:
                print(f"   ✅ Groq has valid script")
                groq_result.provider = "ensemble-script-validation"
                return groq_result
            elif openai_valid and not groq_valid:
                print(f"   ✅ OpenAI has valid script")
                openai_result.provider = "ensemble-script-validation"
                return openai_result

        # Strategy 4: Length check (avoid empty/short results)
        if len(groq_result.text.strip()) < 3 and len(openai_result.text.strip()) >= 5:
            print(f"   ✅ OpenAI has content, Groq too short")
            openai_result.provider = "ensemble-length-check"
            return openai_result
        elif len(openai_result.text.strip()) < 3 and len(groq_result.text.strip()) >= 5:
            print(f"   ✅ Groq has content, OpenAI too short")
            groq_result.provider = "ensemble-length-check"
            return groq_result

        # Default: Prefer Groq (Whisper Large V3 > V1)
        print(f"   ➡️ Defaulting to Groq (larger model)")
        groq_result.provider = "ensemble-groq-default"
        return groq_result

    @staticmethod
    def _detect_script(text: str) -> str:
        """Quick script detection for ensemble validation."""
        if not text:
            return "unknown"

        # Check first 50 chars
        sample = text[:50]

        # Gujarati: U+0A80 to U+0AFF
        if any('\u0A80' <= c <= '\u0AFF' for c in sample):
            return "gujarati"

        # Devanagari (Hindi): U+0900 to U+097F
        if any('\u0900' <= c <= '\u097F' for c in sample):
            return "devanagari"

        # Arabic: U+0600 to U+06FF
        if any('\u0600' <= c <= '\u06FF' for c in sample):
            return "arabic"

        # Chinese: U+4E00 to U+9FFF
        if any('\u4E00' <= c <= '\u9FFF' for c in sample):
            return "chinese"

        # Sinhala (Whisper hallucination): U+0D80 to U+0DFF
        if any('\u0D80' <= c <= '\u0DFF' for c in sample):
            return "sinhala"

        # Thai (Whisper hallucination): U+0E00 to U+0E7F
        if any('\u0E00' <= c <= '\u0E7F' for c in sample):
            return "thai"

        return "latin"


class ASRConfig:
    """
    ASR configuration manager.

    Now supports ENSEMBLE mode (default): runs both Groq + OpenAI in parallel.
    """

    def __init__(self):
        # Default: ENSEMBLE mode (run both, pick best)
        self.config = {
            "mode": "ensemble",  # "ensemble" | "groq" | "openai"
            "default": "ensemble",
            "provider_en": "ensemble",
            "patient_auto": "ensemble",
            "interpreter_auto": "ensemble",
        }

    def get_backend(self, role: str, language: str) -> str:
        """Get ASR backend. Can return 'ensemble'."""
        key = f"{role}_{language}"
        if key in self.config:
            return self.config[key]
        if role in self.config:
            return self.config[role]
        return self.config.get("default", "ensemble")

    def set_backend(self, role: str, language: str, backend: str) -> None:
        key = f"{role}_{language}"
        self.config[key] = backend

    def set_default(self, backend: str) -> None:
        self.config["default"] = backend
        self.config["mode"] = backend

    def get_mode(self) -> str:
        """Get current mode: 'ensemble', 'groq', or 'openai'"""
        return self.config.get("mode", "ensemble")

    def get_all(self) -> dict:
        return self.config.copy()

    def update(self, config: dict) -> None:
        self.config.update(config)


# Global ASR configuration instance
asr_config = ASRConfig()
