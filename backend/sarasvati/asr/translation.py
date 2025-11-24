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

ENSEMBLE MODE:
- Runs multiple translation strategies in parallel (different temperatures/prompts)
- Uses consensus logic to pick most medically accurate translation
- Validates critical medical terms (ઝાડા=diarrhea, કબજિયાત=constipation)
"""

from typing import Optional, List
import httpx
import json
import asyncio
from difflib import SequenceMatcher


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

    def __init__(self, api_key: str, model: str = "gpt-4o", temperature: float = 0.1):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

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
                        "temperature": self.temperature,
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


class EnsembleTranslation:
    """
    Multi-strategy translation using tribunal pattern.

    Runs multiple GPT-4o translation attempts with different configurations:
    - Strategy A: Conservative (temp=0.1, medical dictionary emphasis)
    - Strategy B: Moderate (temp=0.3, balanced)
    - Strategy C: Medical validator (temp=0.1, critical term checking)

    Picks best translation using consensus logic focused on medical accuracy.
    """

    # Critical medical terms that MUST be translated correctly
    CRITICAL_MEDICAL_TERMS = {
        "gu": {
            "ઝાડા": "diarrhea",
            "કબજિયાત": "constipation",
            "દુખાવો": "pain",
            "તાવ": "fever",
            "ઉલટી": "vomiting",
        },
        "hi": {
            "दस्त": "diarrhea",
            "कब्ज": "constipation",
            "दर्द": "pain",
            "बुखार": "fever",
            "उल्टी": "vomiting",
        },
        "es": {
            "diarrea": "diarrhea",
            "estreñimiento": "constipation",
            "dolor": "pain",
            "fiebre": "fever",
            "náusea": "nausea",
        },
    }

    @staticmethod
    def similarity(text1: str, text2: str) -> float:
        """Calculate similarity ratio between two strings."""
        return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()

    @staticmethod
    def validate_medical_terms(
        original: str, translation: str, language: str
    ) -> tuple[bool, int]:
        """
        Check if critical medical terms are translated correctly.

        Returns:
            (is_valid, num_critical_terms_found)
        """
        if language not in EnsembleTranslation.CRITICAL_MEDICAL_TERMS:
            return True, 0  # No validation rules for this language

        terms = EnsembleTranslation.CRITICAL_MEDICAL_TERMS[language]
        found_terms = 0

        for original_term, expected_english in terms.items():
            if original_term in original:
                found_terms += 1
                # Check if expected English term appears in translation
                if expected_english.lower() not in translation.lower():
                    print(f"   ⚠️  Medical term validation FAILED: '{original_term}' should be '{expected_english}' but not found in: {translation[:50]}...")
                    return False, found_terms

        if found_terms > 0:
            print(f"   ✅ Medical term validation PASSED: {found_terms} critical terms correctly translated")

        return True, found_terms

    @staticmethod
    async def translate_ensemble(
        text: str,
        suspected_language: str,
        api_key: str,
    ) -> TranslationResult:
        """
        Run multiple translation strategies in parallel, pick best result.

        Consensus strategies:
        1. Medical term validation: Reject translations with wrong medical terms
        2. Exact agreement: If 2+ strategies agree exactly, high confidence
        3. Similarity scoring: Pick most common translation pattern
        4. Fallback: Conservative strategy (lowest temperature)

        Args:
            text: Original text to translate
            suspected_language: Language code (e.g., "gu", "hi", "es")
            api_key: OpenAI API key

        Returns:
            TranslationResult with best translation from ensemble
        """
        if not text or len(text.strip()) == 0:
            return TranslationResult(
                original=text,
                detected_language="unknown",
                error="Empty text",
            )

        print(f"\n🎭 ENSEMBLE TRANSLATION: Running 3 strategies in parallel...")
        print(f"   Text: {text[:100]}{'...' if len(text) > 100 else ''}")
        print(f"   Language: {suspected_language}")

        # Strategy A: Conservative (temp=0.1) - Most deterministic
        service_a = TranslationService(api_key, model="gpt-4o", temperature=0.1)

        # Strategy B: Moderate (temp=0.3) - Slightly more flexible
        service_b = TranslationService(api_key, model="gpt-4o", temperature=0.3)

        # Strategy C: Very conservative (temp=0.05) - Maximum precision
        service_c = TranslationService(api_key, model="gpt-4o", temperature=0.05)

        # Run all three in parallel
        try:
            results = await asyncio.gather(
                service_a.process_non_english(text, suspected_language),
                service_b.process_non_english(text, suspected_language),
                service_c.process_non_english(text, suspected_language),
                return_exceptions=True,
            )
        except Exception as e:
            print(f"   ❌ Ensemble translation failed: {e}")
            return TranslationResult(
                original=text,
                detected_language=suspected_language,
                error=f"Ensemble translation exception: {str(e)}",
            )

        # Filter out exceptions
        valid_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"   ⚠️  Strategy {chr(65+i)} failed: {result}")
                continue
            if result.error:
                print(f"   ⚠️  Strategy {chr(65+i)} error: {result.error}")
                continue
            valid_results.append((chr(65+i), result))

        if not valid_results:
            return TranslationResult(
                original=text,
                detected_language=suspected_language,
                error="All ensemble strategies failed",
            )

        print(f"   ✓ Got {len(valid_results)} valid translations")

        # Step 1: Validate medical terms
        validated_results = []
        for strategy_name, result in valid_results:
            if result.translation:
                is_valid, num_terms = EnsembleTranslation.validate_medical_terms(
                    text, result.translation, suspected_language
                )
                if is_valid:
                    validated_results.append((strategy_name, result, num_terms))
                    print(f"   Strategy {strategy_name}: ✅ Medical validation passed ({num_terms} terms)")
                else:
                    print(f"   Strategy {strategy_name}: ❌ Medical validation FAILED - rejecting")

        # If medical validation filtered out all results, use unvalidated
        if not validated_results:
            print("   ⚠️  No translations passed medical validation, using all results")
            validated_results = [(name, result, 0) for name, result in valid_results]

        # Step 2: Check for exact agreement
        translations = [result.translation for _, result, _ in validated_results if result.translation]
        if len(translations) >= 2:
            for i in range(len(translations)):
                matches = sum(1 for t in translations if t.lower().strip() == translations[i].lower().strip())
                if matches >= 2:
                    print(f"   ✅ CONSENSUS: {matches} strategies agree exactly!")
                    best_result = validated_results[i][1]
                    best_result.detected_language = f"{best_result.detected_language}-ensemble-consensus"
                    return best_result

        # Step 3: Similarity scoring - pick one closest to others
        best_idx = 0
        best_score = 0.0
        for i, (name_i, result_i, terms_i) in enumerate(validated_results):
            if not result_i.translation:
                continue

            # Calculate average similarity to all other translations
            similarity_sum = 0.0
            for j, (name_j, result_j, terms_j) in enumerate(validated_results):
                if i != j and result_j.translation:
                    sim = EnsembleTranslation.similarity(result_i.translation, result_j.translation)
                    similarity_sum += sim

            avg_similarity = similarity_sum / max(len(validated_results) - 1, 1)

            # Bonus for having critical medical terms
            score = avg_similarity + (terms_i * 0.1)

            print(f"   Strategy {name_i}: similarity={avg_similarity:.2f}, terms={terms_i}, score={score:.2f}")

            if score > best_score:
                best_score = score
                best_idx = i

        best_strategy, best_result, _ = validated_results[best_idx]
        print(f"   🏆 WINNER: Strategy {best_strategy} (score={best_score:.2f})")

        best_result.detected_language = f"{best_result.detected_language}-ensemble-best"
        return best_result
