"""
test_tribunal_golden_cases.py

Golden test cases for the SARASVATI tribunal system.

These tests verify that the tribunal correctly identifies different error types
across medical interpretation scenarios. Each test represents a known edge case
that the system should handle correctly.

Test Categories:
1. CRITICAL errors - Dosage, negation, body part substitutions
2. Fabrication detection - Interpreter adding content not in source
3. Omission detection - Interpreter missing critical info
4. Cultural equivalents - Should NOT be flagged as errors
5. Distortion detection - Mistranslation that changes meaning
6. ASR reliability gating - Don't grade on bad transcripts

Usage:
    pytest backend/sarasvati/tests/test_tribunal_golden_cases.py -v
    python -m pytest backend/sarasvati/tests/test_tribunal_golden_cases.py -v
"""

import asyncio
import os
import pytest
from datetime import datetime
from typing import Dict, Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Import tribunal components
from backend.sarasvati.core.agent import (
    NodeAExtractor,
    NodeBMonitor,
    NodeCArbiter,
    ClinicalDebateOrchestrator,
    DEFAULT_MODEL_EXTRACTOR,
    DEFAULT_MODEL_MONITOR,
    DEFAULT_MODEL_ARBITER,
)
from backend.sarasvati.core.state import (
    TranscriptSegment,
    AlignmentMatch,
    StreamRole,
    TribunalCaseType,
    ErrorSeverity,
)


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_groq_client():
    """Create a mock Groq client for testing without API calls."""
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    return client


def make_segment(
    role: str,
    text: str,
    text_english: Optional[str] = None,
    text_english_smooth: Optional[str] = None,
    text_english_literal: Optional[str] = None,
    timestamp: float = 0.0,
    segment_id: Optional[str] = None,
    asr_reliable: bool = True,
) -> TranscriptSegment:
    """Helper to create a TranscriptSegment for testing."""
    return TranscriptSegment(
        role=StreamRole(role),
        text=text,
        text_english=text_english or text,
        text_english_smooth=text_english_smooth,
        text_english_literal=text_english_literal,
        timestamp=timestamp,
        duration=1.0,
        confidence=0.95,
        is_final=True,
        segment_id=segment_id or f"seg_{timestamp}",
        asr_reliable=asr_reliable,
    )


def make_alignment(
    provider_segment: Optional[TranscriptSegment] = None,
    interpreter_segment: Optional[TranscriptSegment] = None,
    patient_segment: Optional[TranscriptSegment] = None,
    case_type: TribunalCaseType = TribunalCaseType.ALIGNED_OUTBOUND,
    is_matched: bool = True,
    similarity_score: float = 0.85,
) -> AlignmentMatch:
    """Helper to create an AlignmentMatch for testing."""
    return AlignmentMatch(
        provider_segment=provider_segment,
        interpreter_segment=interpreter_segment,
        patient_segment=patient_segment,
        similarity_score=similarity_score,
        combined_score=similarity_score * 0.9,
        time_delta=2.0,
        is_matched=is_matched,
        dtw_distance=0.2,
        case_type=case_type,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# GOLDEN TEST CASES - Data
# ═══════════════════════════════════════════════════════════════════════════════

GOLDEN_CASES = {
    # ──────────────────────────────────────────────────────────────────────────
    # CRITICAL ERRORS - Must always be caught
    # ──────────────────────────────────────────────────────────────────────────

    "critical_dosage_error": {
        "description": "Interpreter changes medication dosage (500mg → 50mg)",
        "provider_text": "Take 500 milligrams of acetaminophen twice daily.",
        "interpreter_text": "Take 50 milligrams of acetaminophen twice daily.",
        "expected_severity": "critical",
        "expected_type": "distortion_medical",
        "should_detect_error": True,
    },

    "critical_negation_flip": {
        "description": "Interpreter removes negation (No fever → Fever)",
        "provider_text": "The patient reports no fever and no chills.",
        "interpreter_text": "The patient reports fever and chills.",
        "expected_severity": "critical",
        "expected_type": "distortion_medical",
        "should_detect_error": True,
    },

    "critical_body_part_substitution": {
        "description": "Interpreter changes body part (head → arm)",
        "provider_text": "Do you have pain in your head?",
        "interpreter_text": "Do you have pain in your arm?",
        "expected_severity": "critical",
        "expected_type": "distortion_medical",
        "should_detect_error": True,
    },

    "critical_medication_name_change": {
        "description": "Interpreter changes medication name",
        "provider_text": "We are prescribing metformin for your diabetes.",
        "interpreter_text": "We are prescribing aspirin for your diabetes.",
        "expected_severity": "critical",
        "expected_type": "distortion_medical",
        "should_detect_error": True,
    },

    "critical_frequency_change": {
        "description": "Interpreter changes medication frequency",
        "provider_text": "Take this medication three times a day.",
        "interpreter_text": "Take this medication once a day.",
        "expected_severity": "critical",
        "expected_type": "distortion_medical",
        "should_detect_error": True,
    },

    # ──────────────────────────────────────────────────────────────────────────
    # FABRICATION ERRORS - Interpreter adding content
    # ──────────────────────────────────────────────────────────────────────────

    "fabrication_diagnosis": {
        "description": "Interpreter invents a diagnosis",
        "provider_text": "We need to run more tests to determine the cause.",
        "interpreter_text": "You have cancer. We need to run more tests.",
        "expected_severity": "critical",
        "expected_type": "fabrication_diagnosis",
        "should_detect_error": True,
    },

    "fabrication_treatment": {
        "description": "Interpreter invents a treatment",
        "provider_text": "I'll see you next week for a follow-up.",
        "interpreter_text": "You need surgery. I'll see you next week.",
        "expected_severity": "critical",
        "expected_type": "fabrication_treatment",
        "should_detect_error": True,
    },

    "fabrication_symptom": {
        "description": "Interpreter adds symptom not mentioned",
        "provider_text": "You have a mild cold.",
        "interpreter_text": "You have a mild cold with heart palpitations.",
        "expected_severity": "critical",
        "expected_type": "fabrication_medical",
        "should_detect_error": True,
    },

    # ──────────────────────────────────────────────────────────────────────────
    # OMISSION ERRORS - Interpreter missing critical info
    # ──────────────────────────────────────────────────────────────────────────

    "omission_allergy_warning": {
        "description": "Interpreter omits critical allergy warning",
        "provider_text": "This medication contains penicillin. Do not take if you are allergic to penicillin.",
        "interpreter_text": "This medication will help you feel better.",
        "expected_severity": "critical",
        "expected_type": "omission_critical",
        "should_detect_error": True,
    },

    "omission_dosage_instruction": {
        "description": "Interpreter omits dosage instructions",
        "provider_text": "Take two pills every morning with food, and do not exceed four pills in 24 hours.",
        "interpreter_text": "Take the pills every morning.",
        "expected_severity": "high",
        "expected_type": "omission",
        "should_detect_error": True,
    },

    # ──────────────────────────────────────────────────────────────────────────
    # CULTURAL EQUIVALENTS - Should NOT be flagged as errors
    # ──────────────────────────────────────────────────────────────────────────

    "acceptable_functional_equivalent_compliance": {
        "description": "Functional equivalent: compliant → taking regularly",
        "provider_text": "Have you been compliant with your medication?",
        "interpreter_text": "Have you been taking your medicine regularly?",
        "expected_severity": None,
        "expected_type": None,
        "should_detect_error": False,
    },

    "acceptable_functional_equivalent_diabetes": {
        "description": "Functional equivalent: diabetes medication → sugar medicine",
        "provider_text": "This is your diabetes medication.",
        "interpreter_text": "This is your sugar medicine.",
        "expected_severity": None,
        "expected_type": None,
        "should_detect_error": False,
    },

    "acceptable_paraphrase_breathing": {
        "description": "Acceptable paraphrase: shortness of breath → difficulty breathing",
        "provider_text": "Are you experiencing shortness of breath?",
        "interpreter_text": "Are you having difficulty breathing?",
        "expected_severity": None,
        "expected_type": None,
        "should_detect_error": False,
    },

    "acceptable_paraphrase_chest": {
        "description": "Acceptable paraphrase: tightness in chest → chest pressure",
        "provider_text": "Do you feel tightness in your chest?",
        "interpreter_text": "Do you feel pressure in your chest?",
        "expected_severity": None,
        "expected_type": None,
        "should_detect_error": False,
    },

    "acceptable_paraphrase_twice_daily": {
        "description": "Acceptable paraphrase: twice daily → morning and evening",
        "provider_text": "Take this twice daily.",
        "interpreter_text": "Take this in the morning and evening.",
        "expected_severity": None,
        "expected_type": None,
        "should_detect_error": False,
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ACCURATE INTERPRETATIONS - No errors
    # ──────────────────────────────────────────────────────────────────────────

    "accurate_simple": {
        "description": "Simple accurate interpretation",
        "provider_text": "Please take a deep breath.",
        "interpreter_text": "Please take a deep breath.",
        "expected_severity": None,
        "expected_type": None,
        "should_detect_error": False,
    },

    "accurate_medical_history": {
        "description": "Accurate interpretation of medical history",
        "provider_text": "He has a history of COPD and recent pneumonia.",
        "interpreter_text": "He has a history of COPD and the pneumonia he had recently.",
        "expected_severity": None,
        "expected_type": None,
        "should_detect_error": False,
    },

    # ──────────────────────────────────────────────────────────────────────────
    # INCOHERENT OUTPUT - Gibberish or nonsensical
    # ──────────────────────────────────────────────────────────────────────────

    "incoherent_plural_bodies": {
        "description": "Impossible anatomy: plural bodies",
        "provider_text": "Do you have pain anywhere else?",
        "interpreter_text": "Do you have pain in other bodies?",
        "expected_severity": "critical",
        "expected_type": "incoherent",
        "should_detect_error": True,
    },

    "incoherent_broken_idiom": {
        "description": "Broken idiom: I'm sorry to hear → I'm sorry because I listen",
        "provider_text": "I'm sorry to hear that.",
        "interpreter_text": "I'm sorry because I listen.",
        "expected_severity": "high",
        "expected_type": "distortion",
        "should_detect_error": True,
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS - Model Configuration
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelConfiguration:
    """Verify that model assignments are correct (all flagship models)."""

    def test_extractor_uses_70b_model(self):
        """Extractor (Agent A) should use Llama 70B for capable medical extraction."""
        assert "70b" in DEFAULT_MODEL_EXTRACTOR.lower(), (
            f"Extractor should use 70B model for medical reasoning, got: {DEFAULT_MODEL_EXTRACTOR}"
        )

    def test_monitor_fallback_uses_70b(self):
        """Monitor fallback should use Llama 70B (not 8B)."""
        assert "70b" in DEFAULT_MODEL_MONITOR.lower(), (
            f"Monitor fallback should use 70B model, got: {DEFAULT_MODEL_MONITOR}"
        )

    def test_arbiter_uses_gpt4o(self):
        """Arbiter (Agent C) should use GPT-4o for structured judgment."""
        assert "gpt-4o" in DEFAULT_MODEL_ARBITER.lower() or "gpt4o" in DEFAULT_MODEL_ARBITER.lower(), (
            f"Arbiter should use GPT-4o, got: {DEFAULT_MODEL_ARBITER}"
        )

    def test_all_models_are_flagship(self):
        """All three models should be flagship-tier."""
        # Extractor (A): Llama 70B
        assert "70b" in DEFAULT_MODEL_EXTRACTOR.lower()
        # Monitor fallback: Llama 70B
        assert "70b" in DEFAULT_MODEL_MONITOR.lower()
        # Arbiter (C): GPT-4o (flagship)
        assert "gpt-4o" in DEFAULT_MODEL_ARBITER.lower() or "gpt4o" in DEFAULT_MODEL_ARBITER.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS - Anti-Telephone Pattern
# ═══════════════════════════════════════════════════════════════════════════════

class TestAntiTelephonePattern:
    """Verify the anti-telephone pattern is correctly implemented."""

    def test_monitor_does_not_receive_extractor_output(self):
        """
        Verify that NodeBMonitor.analyze_independently() does NOT receive
        the extractor's JSON output (anti-anchoring).
        """
        import inspect
        sig = inspect.signature(NodeBMonitor.analyze_independently)
        params = list(sig.parameters.keys())

        # Monitor should only receive: source_text, interpreter_text, patient_text,
        # source_role, target_role, case_type
        assert "extractor_json" not in params, (
            "Monitor should NOT receive extractor_json (anti-telephone pattern)"
        )
        assert "extractor_output" not in params, (
            "Monitor should NOT receive extractor output (anti-telephone pattern)"
        )

    def test_arbiter_receives_both_outputs(self):
        """
        Verify that NodeCArbiter.arbitrate() receives both extractor and monitor outputs.
        """
        import inspect
        sig = inspect.signature(NodeCArbiter.arbitrate)
        params = list(sig.parameters.keys())

        assert "extractor_json" in params, (
            "Arbiter should receive extractor_json"
        )
        assert "monitor_report" in params, (
            "Arbiter should receive monitor_report"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS - Golden Cases (requires API key)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set - skipping live API tests"
)
class TestTribunalGoldenCases:
    """
    Live integration tests using real Groq API.

    These tests verify the full tribunal pipeline against known edge cases.
    Run with: GROQ_API_KEY=xxx pytest -k TestTribunalGoldenCases -v
    """

    @pytest.fixture
    def orchestrator(self):
        """Create a real orchestrator with Groq API."""
        api_key = os.getenv("GROQ_API_KEY")
        return ClinicalDebateOrchestrator(api_key)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case_name", [
        "critical_dosage_error",
        "critical_negation_flip",
        "critical_body_part_substitution",
    ])
    async def test_critical_errors_detected(self, orchestrator, case_name):
        """Verify CRITICAL errors are always detected."""
        case = GOLDEN_CASES[case_name]

        provider_seg = make_segment(
            role="provider",
            text=case["provider_text"],
            text_english_smooth=case["provider_text"],
            timestamp=0.0,
        )
        interpreter_seg = make_segment(
            role="interpreter",
            text=case["interpreter_text"],
            text_english_literal=case["interpreter_text"],
            timestamp=2.0,
        )
        alignment = make_alignment(
            provider_segment=provider_seg,
            interpreter_segment=interpreter_seg,
        )

        result = await orchestrator.run_debate(alignment)

        # Should detect at least one error
        assert len(result["detected_errors"]) > 0, (
            f"Case '{case_name}' should detect an error: {case['description']}"
        )

        # Should be CRITICAL severity
        severities = [e["severity"].value if hasattr(e["severity"], "value") else e["severity"]
                     for e in result["detected_errors"]]
        assert "critical" in severities, (
            f"Case '{case_name}' should have CRITICAL severity, got: {severities}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case_name", [
        "acceptable_functional_equivalent_compliance",
        "acceptable_paraphrase_breathing",
        "accurate_simple",
    ])
    async def test_acceptable_interpretations_not_flagged(self, orchestrator, case_name):
        """Verify acceptable interpretations are NOT flagged as errors."""
        case = GOLDEN_CASES[case_name]

        provider_seg = make_segment(
            role="provider",
            text=case["provider_text"],
            text_english_smooth=case["provider_text"],
            timestamp=0.0,
        )
        interpreter_seg = make_segment(
            role="interpreter",
            text=case["interpreter_text"],
            text_english_literal=case["interpreter_text"],
            timestamp=2.0,
        )
        alignment = make_alignment(
            provider_segment=provider_seg,
            interpreter_segment=interpreter_seg,
        )

        result = await orchestrator.run_debate(alignment)

        # Should not detect clinical errors (system errors are OK)
        clinical_errors = [
            e for e in result["detected_errors"]
            if not e.get("is_system_error", False)
        ]
        assert len(clinical_errors) == 0, (
            f"Case '{case_name}' should NOT flag acceptable interpretation: "
            f"{case['description']}. Got errors: {clinical_errors}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS - Error Deduplication
# ═══════════════════════════════════════════════════════════════════════════════

class TestErrorDeduplication:
    """Test the error deduplication logic."""

    @pytest.fixture
    def orchestrator(self, mock_groq_client):
        """Create orchestrator with mock client."""
        with patch("backend.sarasvati.core.agent.AsyncGroq", return_value=mock_groq_client):
            return ClinicalDebateOrchestrator("fake-api-key")

    def test_fabrication_dominates_distortion(self, orchestrator):
        """Fabrication should remove distortion (can't distort what doesn't exist)."""
        errors = [
            {"type": "fabrication_medical", "severity": "critical", "description": "Made up diagnosis"},
            {"type": "distortion", "severity": "medium", "description": "Changed wording"},
        ]

        deduped = orchestrator._deduplicate_errors(errors)

        assert len(deduped) == 1, "Fabrication should remove distortion"
        assert "fabrication" in deduped[0]["type"], "Only fabrication should remain"

    def test_distortion_dominates_omission(self, orchestrator):
        """Distortion should remove omission (distortion is more specific)."""
        errors = [
            {"type": "distortion_medical", "severity": "high", "description": "Wrong dosage"},
            {"type": "omission", "severity": "medium", "description": "Missed info"},
        ]

        deduped = orchestrator._deduplicate_errors(errors)

        assert len(deduped) == 1, "Distortion should remove omission"
        assert "distortion" in deduped[0]["type"], "Only distortion should remain"

    def test_keeps_unrelated_errors(self, orchestrator):
        """Unrelated error types should both be kept."""
        errors = [
            {"type": "role_violation", "severity": "high", "description": "Gave advice"},
            {"type": "incoherent", "severity": "high", "description": "Gibberish"},
        ]

        deduped = orchestrator._deduplicate_errors(errors)

        assert len(deduped) == 2, "Unrelated errors should both be kept"


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS - ASR Reliability Gating
# ═══════════════════════════════════════════════════════════════════════════════

class TestASRReliabilityGating:
    """Test that unreliable ASR segments are not graded."""

    @pytest.mark.asyncio
    async def test_unreliable_source_not_graded(self, mock_groq_client):
        """When source ASR is unreliable, don't grade the interpreter."""
        with patch("backend.sarasvati.core.agent.AsyncGroq", return_value=mock_groq_client):
            orchestrator = ClinicalDebateOrchestrator("fake-api-key")

        # Source segment marked as unreliable
        provider_seg = make_segment(
            role="provider",
            text="Garbled ASR output",
            text_english_smooth="Garbled ASR output",
            asr_reliable=False,  # UNRELIABLE
        )
        interpreter_seg = make_segment(
            role="interpreter",
            text="Take two pills daily",
            text_english_literal="Take two pills daily",
            asr_reliable=True,
        )
        alignment = make_alignment(
            provider_segment=provider_seg,
            interpreter_segment=interpreter_seg,
        )

        result = await orchestrator.run_debate(alignment)

        # Should return system error, not clinical error
        assert len(result["detected_errors"]) == 1
        error = result["detected_errors"][0]
        assert error["error_type"] == "asr_unreliable"
        assert error["is_system_error"] == True


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
