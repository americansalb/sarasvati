"""
Translation and Transliteration Service

Uses OpenAI GPT models to:
1. Detect language (confirm ASR detection)
2. Transliterate non-Latin scripts to Latin (e.g., ગુજરાતી → gujarātī)
3. Translate to English for teaching/assessment

Example:
    Original: "નમસ્તે, તમે કેમ છો?"
    Transliteration: "namaste, tame kem cho?"
    Translation: "Hello, how are you?"
"""

from typing import Optional
import httpx
import json


class TranslationResult:
    """Result of translation/transliteration."""
    def __init__(
        self,
        original: str,
        detected_language: str,
        transliteration: Optional[str] = None,
        translation: Optional[str] = None,
        error: Optional[str] = None,
    ):
        self.original = original
        self.detected_language = detected_language
        self.transliteration = transliteration
        self.translation = translation
        self.error = error


class TranslationService:
    """OpenAI-based translation and transliteration service with medical vocabulary."""

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.api_key = api_key
        self.model = model

    async def process_non_english(
        self,
        text: str,
        suspected_language: str = "unknown",
    ) -> TranslationResult:
        """
        Process non-English text: detect language, transliterate, and translate.

        MEDICAL CONTEXT: This is used for medical interpreter monitoring.
        The LLM MUST know common medical vocabulary to avoid dangerous mistranslations.

        Args:
            text: Original text in any language/script
            suspected_language: Hint from ASR (e.g., "gu", "es", "hi")

        Returns:
            TranslationResult with transliteration and translation
        """
        if not text or len(text.strip()) == 0:
            return TranslationResult(
                original=text,
                detected_language="unknown",
                error="Empty text",
            )

        # Build prompt for GPT with MEDICAL VOCABULARY
        prompt = f"""You are a medical interpreter and language expert specializing in healthcare communication.

⚕️ CRITICAL: This is a MEDICAL conversation. The text contains medical terminology.

COMMON MEDICAL TERMS YOU MUST KNOW:

**Gujarati Medical Vocabulary:**
- ઝાડા (jāḍā) = DIARRHEA (NOT "heavy", NOT "loose")
- કબજિયાત (kabajiyāt) = CONSTIPATION (NOT "sweet", NOT "kabaddi")
- દુખાવો (dukhāvo) = pain, ache
- પેટ (peṭ) = stomach, abdomen
- માથું (māthuṁ) = head
- તાવ (tāv) = fever
- ઉલટી (ulaṭī) = vomiting
- દવા (davā) = medicine
- ડૉક્ટર (ḍôkṭar) = doctor

**Hindi Medical Vocabulary:**
- दस्त (dast) = diarrhea
- कब्ज (kabj) = constipation
- दर्द (dard) = pain
- पेट (pet) = stomach
- सिर (sir) = head
- बुखार (bukhār) = fever
- उल्टी (ultī) = vomiting

**Spanish Medical Vocabulary:**
- dolor = pain
- cabeza = head
- estómago = stomach
- diarrea = diarrhea
- estreñimiento = constipation
- náusea = nausea

Text to analyze: "{text}"
Suspected language: {suspected_language}

Respond ONLY with valid JSON:
{{
  "detected_language": "gu",
  "transliteration": "romanized version using Latin characters",
  "translation": "English translation (MUST be medically accurate)"
}}

CRITICAL RULES:
1. DO NOT hallucinate meanings - if unsure, preserve the original word
2. MEDICAL TERMS: Use the vocabulary above - these are common patient complaints
3. "ઝાડા" (jāḍā) is ALWAYS diarrhea in medical context
4. "કબજિયાત" is ALWAYS constipation, never a food item
5. If you see body parts (પેટ, માથું, सिर, cabeza), it's likely a symptom description
6. For transliteration: use standard IAST/ISO 15919 for Indic languages
7. If text is already Latin script (es, pt), set transliteration = null"""

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a MEDICAL interpreter and language expert. You specialize in healthcare communication and know medical vocabulary in Gujarati, Hindi, Spanish, Arabic, and Chinese. Always respond with valid JSON. NEVER hallucinate meanings for medical terms - if you see ઝાડા (jāḍā), it means DIARRHEA, not 'heavy' or 'loose'. If you see કબજિયાત (kabajiyāt), it means CONSTIPATION, not 'sweet' or 'kabaddi'. Medical accuracy is critical."
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 500,
                    },
                    timeout=30.0,
                )

                if response.status_code != 200:
                    return TranslationResult(
                        original=text,
                        detected_language=suspected_language,
                        error=f"OpenAI API error: {response.text}",
                    )

                result = response.json()
                content = result["choices"][0]["message"]["content"].strip()

                # Parse JSON response
                try:
                    parsed = json.loads(content)
                    return TranslationResult(
                        original=text,
                        detected_language=parsed.get("detected_language", suspected_language),
                        transliteration=parsed.get("transliteration"),
                        translation=parsed.get("translation"),
                    )
                except json.JSONDecodeError as e:
                    # Fallback: try to extract from text
                    return TranslationResult(
                        original=text,
                        detected_language=suspected_language,
                        error=f"Failed to parse GPT response: {content[:100]}",
                    )

            except Exception as e:
                return TranslationResult(
                    original=text,
                    detected_language=suspected_language,
                    error=f"Translation service exception: {str(e)}",
                )

    async def transliterate_only(self, text: str, language: str) -> Optional[str]:
        """
        Quick transliteration without translation (for UI display).

        Args:
            text: Text in non-Latin script
            language: Language code (e.g., "gu", "hi", "ar")

        Returns:
            Transliterated text in Latin script, or None if error
        """
        result = await self.process_non_english(text, language)
        return result.transliteration

    async def translate_only(self, text: str, language: str) -> Optional[str]:
        """
        Quick translation to English without transliteration.

        Args:
            text: Text in any language
            language: Language code

        Returns:
            English translation, or None if error
        """
        result = await self.process_non_english(text, language)
        return result.translation
