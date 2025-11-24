"""
SARASVATI Independent Tribunal System
======================================
The "Trisul Protocol" - Three diverse agents with anti-telephone data flow.

Architecture:
- Node A (Extractor): llama-3.1-8b-instant (Meta) - Structured JSON extraction
- Node B (Monitor): llama3-8b-8192 (Meta) - Blind skeptic, independent analysis
- Node C (Arbiter): llama-3.3-70b-versatile (Meta) - Senior judge, overrides juniors

Anti-Telephone Pattern:
- Node A and B run in PARALLEL via asyncio.gather
- Node B is BLIND to Node A's output (prevents anchoring bias)
- Node C sees raw evidence + both A and B outputs
- Node C can OVERRIDE junior analysts if they conflict with raw text

This module uses Groq API for fast inference with model diversity.
"""

import os
import json
import re
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
import asyncio

try:
    from groq import AsyncGroq
except ImportError:
    AsyncGroq = None

from .state import (
    MedicalEntity,
    TranscriptSegment,
    AlignmentMatch,
    ClinicalError,
    ErrorSeverity,
    AgentDebateResult,
    TribunalCaseType,  # CRITICAL: Needed for case type handling
)


# ===== Default Models (can be overridden via env) =====
# NOTE: These are fallback defaults. Server.py overrides with better models.
# WARNING: Groq has decommissioned all Gemma models (gemma2-27b-it, gemma2-9b-it)

DEFAULT_MODEL_EXTRACTOR = "llama-3.3-70b-versatile"  # Node A: Meta - 70B (Prosecution)
DEFAULT_MODEL_MONITOR = "mixtral-8x7b-32768"         # Node B: Mistral - MoE (Defense)
DEFAULT_MODEL_ARBITER = "llama-3.1-8b-instant"       # Node C: Meta - 8B (Arbiter, fast)


class NodeAExtractor:
    """
    Node A: The Extractor (Prosecution)

    Model: llama-3.1-8b-instant (Meta)

    Inputs: Raw provider_segment, Raw interpreter_segment, Alignment metadata
    Output: Structured JSON comparing Provider Facts vs Interpreter Facts

    Role: "You are a clinical extraction engine. Produce STRICT JSON."
    """

    def __init__(self, groq_client: AsyncGroq, model: str = DEFAULT_MODEL_EXTRACTOR):
        self.client = groq_client
        self.model = model

    async def extract_comparison(
        self,
        source_segment: Optional[TranscriptSegment],
        interpreter_segment: Optional[TranscriptSegment],
        alignment: AlignmentMatch,
        patient_text: str = "",
        source_role: str = "provider",
        target_role: str = "patient",
        case_type: str = "aligned_outbound",
    ) -> Tuple[Dict[str, Any], str]:
        """
        Extract and compare medical facts - JUDGING ONLY THE INTERPRETER.

        The source (provider or patient) is GROUND TRUTH.
        The interpreter's job is to render it faithfully.

        Args:
            source_segment: The original utterance (provider or patient)
            interpreter_segment: The interpreter's rendition
            source_role: "provider" or "patient"
            target_role: "patient" or "provider"
            case_type: Type of tribunal case

        Returns:
            Tuple of (structured_json, extractor_notes)
        """
        source_text = source_segment["text"] if source_segment else "[NO SOURCE]"
        interpreter_text = interpreter_segment["text"] if interpreter_segment else "[NO INTERPRETATION]"

        # Build context string
        patient_context = f'\nPATIENT CONTEXT:\n"{patient_text}"\n' if patient_text else ""

        prompt = f"""You are a clinical extraction engine evaluating INTERPRETER PERFORMANCE.

CRITICAL: You are ONLY judging the interpreter's accuracy. The {source_role.upper()} is GROUND TRUTH.

{source_role.upper()} SAID (GROUND TRUTH):
"{source_text}"

INTERPRETER'S RENDITION (what interpreter said to {target_role}):
"{interpreter_text}"
{patient_context}
ALIGNMENT SCORE: {alignment.get("similarity_score", 0):.2f}
TIME DELTA: {alignment.get("time_delta", 0):.1f} seconds
CASE TYPE: {case_type}

Your task: Extract medical entities and compare INTERPRETER vs {source_role.upper()} (ground truth).
Identify where the interpreter:
- Omitted critical information
- Added information not in the original
- Distorted/mistranslated
- Changed tone/register inappropriately

Return ONLY valid JSON:
{{
  "source_facts": [
    {{"type": "drug|dosage|frequency|condition|instruction|symptom", "value": "exact text from {source_role}"}}
  ],
  "interpreter_facts": [
    {{"type": "drug|dosage|frequency|condition|instruction|symptom", "value": "exact text from interpreter"}}
  ],
  "interpreter_errors": [
    {{"type": "omission|addition|distortion|register", "severity": "critical|high|medium|low", "description": "what interpreter got wrong"}}
  ],
  "extractor_verdict": "ACCURATE|PARTIAL|INACCURATE|CRITICAL_ERROR"
}}

Patient safety depends on the interpreter's accuracy."""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a clinical extraction engine. Output ONLY valid JSON. No explanations."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=1500,
            )

            content = response.choices[0].message.content

            # Parse JSON from response
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                return (parsed, f"Extractor verdict: {parsed.get('extractor_verdict', 'UNKNOWN')}")
            else:
                return ({"error": "No JSON found", "raw": content[:500]}, "Extraction failed - no valid JSON")

        except Exception as e:
            return ({"error": str(e)}, f"Extraction error: {e}")


class NodeBMonitor:
    """
    Node B: The Monitor (Defense/Skeptic)

    Model: llama3-8b-8192 (Meta) - Different model for diversity

    Inputs: Raw provider_segment["text"], Raw interpreter_segment["text"]
    Constraint: Node B MUST NOT see Node A's JSON. It is BLIND to prevent anchoring bias.

    Role: "You are a skeptic. Read the utterances directly. Identify omissions/shifts yourself."
    Output: Plain-text critique (NOT JSON)
    """

    def __init__(self, groq_client: AsyncGroq, model: str = DEFAULT_MODEL_MONITOR):
        self.client = groq_client
        self.model = model

    async def analyze_independently(
        self,
        source_text: str,
        interpreter_text: str,
        patient_text: str = "",
        source_role: str = "provider",
        target_role: str = "patient",
        case_type: str = "aligned_outbound",
    ) -> str:
        """
        Independently analyze INTERPRETER PERFORMANCE without seeing Node A's output.

        CRITICAL: You are ONLY judging the interpreter. The source is GROUND TRUTH.

        Returns:
            Plain-text critique of interpreter behavior
        """
        # Build patient context for triadic validation
        patient_section = f'''
PATIENT CONTEXT (for verification):
"{patient_text}"
''' if patient_text else ""

        prompt = f"""You are a SKEPTICAL medical interpretation monitor evaluating INTERPRETER BEHAVIOR.

CRITICAL INSTRUCTIONS:
- You are ONLY judging the interpreter's accuracy and ethics
- The {source_role.upper()} statement is GROUND TRUTH - do not critique it
- Focus on what the INTERPRETER did right or wrong

{source_role.upper()}'S STATEMENT (GROUND TRUTH):
"{source_text}"

INTERPRETER'S RENDITION (what interpreter said to {target_role}):
"{interpreter_text}"
{patient_section}
CASE TYPE: {case_type}

Your job: Be a skeptic about the INTERPRETER'S performance.

Analyze the INTERPRETER for:
1. OMISSIONS: What critical info from the {source_role} did the interpreter fail to convey?
2. ADDITIONS/FABRICATIONS: What did the interpreter add that the {source_role} never said?
3. DISTORTIONS: What was mistranslated or changed (numbers, negations, medications, tone)?
4. REGISTER VIOLATIONS: Did the interpreter change tone inappropriately (informal ↔ formal)?
5. CLINICAL IMPACT: If errors exist, what's the patient safety risk?

Write a plain-text critique of the INTERPRETER'S behavior. Be specific. Quote exact discrepancies.

If the interpretation is accurate, say: "No significant issues detected."

Remember: You are the patient's advocate. Be thorough."""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a skeptical medical monitor. You see NO prior analysis. Read the text directly and identify issues yourself."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1000,
            )

            return response.choices[0].message.content

        except Exception as e:
            return f"Monitor error: {e}. Flagging for manual review."


class NodeCArbiter:
    """
    Node C: The Arbiter (Senior Judge)

    Model: llama-3.3-70b-versatile (Meta) - Heavy model for final decision

    Inputs:
        - Raw Evidence (Provider + Interpreter Text)
        - Node A's JSON (Prosecution)
        - Node B's Report (Defense)

    Role: "You are a Senior Medical Judge. Node A and B are junior analysts.
           If their claims conflict with the Raw Evidence, OVERRIDE them."

    Output: Final ClinicalError JSON
    """

    def __init__(self, groq_client: AsyncGroq, model: str = DEFAULT_MODEL_ARBITER):
        self.client = groq_client
        self.model = model

    async def arbitrate(
        self,
        source_text: str,
        interpreter_text: str,
        extractor_json: Dict[str, Any],
        monitor_report: str,
        alignment: AlignmentMatch,
        patient_text: str = "",
        source_role: str = "provider",
        target_role: str = "patient",
        case_type: str = "aligned_outbound",
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Make final judgment on INTERPRETER PERFORMANCE.

        CRITICAL: You are ONLY judging the interpreter.
        Source (provider or patient) is GROUND TRUTH.

        Returns:
            Tuple of (reasoning, list of error dicts with standardized types)
        """
        # Build context section
        patient_context = f'''
PATIENT CONTEXT (for verification):
"{patient_text}"
''' if patient_text else ""

        prompt = f"""You are a SENIOR MEDICAL JUDGE evaluating INTERPRETER PERFORMANCE in a {case_type} case.

═══════════════════════════════════════════════════════════
CRITICAL INSTRUCTIONS
═══════════════════════════════════════════════════════════
YOU ARE ONLY JUDGING THE INTERPRETER.
The {source_role.upper()} statement is GROUND TRUTH - DO NOT critique it.
Focus exclusively on what the INTERPRETER did right or wrong.

ZERO TOLERANCE for:
1. MEDICAL FABRICATIONS: Any invented diagnosis, symptom, treatment, or medical fact → ALWAYS CRITICAL
2. BODY-SHAMING/HARASSMENT: Insulting patient's appearance, weight, or person → ALWAYS HIGH or CRITICAL
3. FABRICATED CLINICAL CONTENT: Adding medical info not in source → ALWAYS CRITICAL

═══════════════════════════════════════════════════════════
PRIMARY EVIDENCE
═══════════════════════════════════════════════════════════

{source_role.upper()}'S STATEMENT (GROUND TRUTH):
"{source_text}"

INTERPRETER'S RENDITION (what interpreter said to {target_role}):
"{interpreter_text}"
{patient_context}
CASE TYPE: {case_type}

EXAMPLES OF CRITICAL ERRORS:
- Source: "Thank you" → Interpreter: "You have cancer" → CRITICAL (medical fabrication)
- Source: "Take one pill daily" → Interpreter: "Take three pills" → CRITICAL (dosage distortion)
- Source: "Pain in my head" → Interpreter: "Pain in my stomach" → CRITICAL (fabricated symptom location)

═══════════════════════════════════════════════════════════
JUNIOR ANALYST REPORTS (may contain errors - verify against raw text)
═══════════════════════════════════════════════════════════

NODE A (Extractor):
{json.dumps(extractor_json, indent=2)}

NODE B (Monitor):
{monitor_report}

═══════════════════════════════════════════════════════════
YOUR DUTY
═══════════════════════════════════════════════════════════

1. The PRIMARY EVIDENCE is ground truth
2. Node A and B may have errors - if they contradict raw text, OVERRIDE them
3. Judge ONLY the interpreter's behavior, never the {source_role} or patient
4. Patient safety is paramount

STANDARDIZED ERROR TYPES (use ONLY these - be SPECIFIC):
FABRICATIONS (interpreter added info not in source):
- fabrication_medical: Invented diagnosis, symptom, or medical fact (ALWAYS CRITICAL)
- fabrication_diagnosis: False statements about patient's condition (ALWAYS CRITICAL)
- fabrication_treatment: Made up medication, dosage, or treatment plan (ALWAYS CRITICAL)
- fabrication: Other fabricated information not in source (usually HIGH)

OMISSIONS (interpreter failed to convey info):
- omission_critical: Missed vital medical info affecting treatment (CRITICAL or HIGH)
- omission: Missed non-critical but meaningful information (MEDIUM)

OTHER ERRORS:
- distortion_medical: Wrong numbers, flipped negations on medical info (CRITICAL or HIGH)
- distortion: Mistranslation of non-medical content (MEDIUM or LOW)
- role_violation: Interpreter gave own opinion, advice, or overstepped role (HIGH)
- incoherent: Nonsensical, gibberish, or incomprehensible output (HIGH or CRITICAL)

═══════════════════════════════════════════════════════════
CULTURAL EQUIVALENTS & FUNCTIONAL TRANSLATION (CRITICAL)
═══════════════════════════════════════════════════════════

DO NOT flag "distortion" when the interpreter uses a CULTURALLY APPROPRIATE FUNCTIONAL EQUIVALENT
that preserves the MEDICAL MEANING and CLINICAL OUTCOME.

ACCEPTABLE FUNCTIONAL EQUIVALENTS (not distortion):
- "compliant with medication" → "taking medicine regularly / on time"
  Example: "Have you been compliant with it?" → "તમે દવા લો છો ટાઇમસર?" (Are you taking medicine on time?)
  → This is ACCEPTABLE, NOT distortion

- "diabetes medication" → "sugar medicine" (common cultural term)
- "high blood pressure" → "BP medicine" or "બી.પી." (widely understood)
- "twice daily" → "morning and evening" (functional equivalent)

ONLY flag distortion when there is a change in:
1. Drug/medicine name (e.g., "insulin" → "paracetamol")
2. Dose (e.g., "one pill" → "three pills")
3. Frequency (e.g., "twice" → "once", "morning" → "evening")
4. Body part (e.g., "head" → "stomach")
5. Negation (e.g., "no pain" → "has pain", "don't take" → "take")
6. Laterality (e.g., "left arm" → "right arm")

SEVERITY CALIBRATION (strictly enforce):
- CRITICAL: Medical fabrications, dangerous distortions, could cause physical harm
  MANDATORY CRITICAL: fabrication_medical, fabrication_diagnosis, fabrication_treatment,
                      wrong medication/dosage, flipped "do not" to "do", fabricated diagnosis,
                      wrong body part, wrong negation
- HIGH: Serious emotional harm, major misunderstanding, omitted key symptoms, incoherent gibberish
- MEDIUM: Meaningful distortion, partial omission of non-critical info
- LOW: Minor paraphrasing, acceptable simplification, preserved overall meaning, functional equivalents

═══════════════════════════════════════════════════════════
OUTPUT FORMAT & CONSTRAINTS
═══════════════════════════════════════════════════════════

Return ONLY valid JSON:
{{
  "verdict": "NO_ERRORS|MINOR_ISSUES|ERRORS_DETECTED|CRITICAL_ERRORS",
  "reasoning": "Your judicial analysis of INTERPRETER performance (2-3 sentences)",
  "override_notes": "If you overrode Node A or B, explain why",
  "errors": [
    {{
      "severity": "critical|high|medium|low",
      "type": "fabrication_medical|fabrication_diagnosis|fabrication_treatment|fabrication|omission_critical|omission|distortion_medical|distortion|role_violation|incoherent",
      "description": "Specific description of what the INTERPRETER got wrong (focus on clinical accuracy only)",
      "interpreter_said": "exact quote from interpreter or MISSING for omissions",
      "should_have_said": "what the correct interpretation would be (ONE SENTENCE ONLY, no repetition)"
    }}
  ]
}}

CRITICAL: "should_have_said" MUST be:
1. A SINGLE, complete sentence
2. In the target language (not source language)
3. Based on the GROUND TRUTH source text
4. NO REPETITION - if you find yourself repeating phrases, STOP and simplify
5. Focus on the KEY CLINICAL FACTS only (drug, dose, frequency, body part, negation)

If no errors: return {{"verdict": "NO_ERRORS", "reasoning": "...", "override_notes": null, "errors": []}}"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a Senior Medical Judge. Raw evidence is primary. Junior analysts (Node A/B) may be wrong. Override them if needed."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,  # Low temperature for consistent decisions
                max_tokens=2000,
                frequency_penalty=0.3,  # Penalize repetition
                presence_penalty=0.1,  # Encourage variety
            )

            content = response.choices[0].message.content

            # Parse JSON from response
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                reasoning = parsed.get("reasoning", "No reasoning provided")
                if parsed.get("override_notes"):
                    reasoning += f" [OVERRIDE: {parsed['override_notes']}]"

                # ENFORCE SEVERITY CALIBRATION: Medical fabrications MUST be CRITICAL
                errors = parsed.get("errors", [])
                for error in errors:
                    error_type = error.get("type", "").lower()

                    # Force CRITICAL for medical fabrications
                    if error_type in ["fabrication_medical", "fabrication_diagnosis", "fabrication_treatment"]:
                        if error.get("severity") != "critical":
                            print(f"⚠️ SEVERITY OVERRIDE: {error_type} changed from {error.get('severity')} to CRITICAL")
                            error["severity"] = "critical"

                return (reasoning, errors)
            else:
                return ("Failed to parse arbiter response", [])

        except Exception as e:
            return (f"Arbiter error: {e}", [{"severity": "high", "type": "system_error", "description": f"Arbiter failed: {e}"}])


class ClinicalDebateOrchestrator:
    """
    Independent Tribunal Orchestrator

    Implements the Anti-Telephone pattern:
    1. Node A and B run in PARALLEL (asyncio.gather)
    2. Node B is BLIND to Node A's output
    3. Node C sees everything and makes final judgment
    """

    def __init__(
        self,
        groq_api_key: str,
        model_extractor: str = DEFAULT_MODEL_EXTRACTOR,
        model_monitor: str = DEFAULT_MODEL_MONITOR,
        model_arbiter: str = DEFAULT_MODEL_ARBITER,
    ):
        if AsyncGroq is None:
            raise ImportError("groq package not installed. Install with: pip install groq")

        self.client = AsyncGroq(api_key=groq_api_key)

        # Initialize agents with DIFFERENT models
        self.extractor = NodeAExtractor(self.client, model_extractor)
        self.monitor = NodeBMonitor(self.client, model_monitor)
        self.arbiter = NodeCArbiter(self.client, model_arbiter)

        # Store model info for debugging
        self.models = {
            "extractor": model_extractor,
            "monitor": model_monitor,
            "arbiter": model_arbiter,
        }

    async def run_debate(
        self,
        alignment: AlignmentMatch,
        patient_text: str = "",
    ) -> AgentDebateResult:
        """
        Run the Independent Tribunal to judge INTERPRETER behavior.

        CRITICAL: The tribunal ONLY judges the interpreter's performance.
        Provider and patient are GROUND TRUTH references, not graded participants.

        The question is always: "Did the interpreter faithfully and ethically
        render this message between provider and patient?"

        Handles all 5 case types:
        - ALIGNED_OUTBOUND: Provider → Interpreter (matched)
        - ALIGNED_INBOUND: Patient → Interpreter (matched)
        - OMISSION_OUTBOUND: Provider spoke, interpreter didn't render it
        - OMISSION_INBOUND: Patient spoke, interpreter didn't relay it
        - FABRICATION: Interpreter spoke without provider or patient prompt
        """
        start_time = datetime.utcnow()

        # Extract case type and segments - with null safety and type normalization
        raw_case_type = alignment.get("case_type", TribunalCaseType.ALIGNED_OUTBOUND)
        # Normalize: case_type could be string or enum depending on source
        if isinstance(raw_case_type, str):
            try:
                case_type = TribunalCaseType(raw_case_type)
            except ValueError:
                # Invalid case type string, default to ALIGNED_OUTBOUND
                case_type = TribunalCaseType.ALIGNED_OUTBOUND
        else:
            case_type = raw_case_type

        provider_segment = alignment.get("provider_segment")
        patient_segment = alignment.get("patient_segment")
        interpreter_segment = alignment.get("interpreter_segment")

        # Determine source and direction based on case type
        if case_type in (TribunalCaseType.ALIGNED_OUTBOUND, TribunalCaseType.OMISSION_OUTBOUND):
            source_role = "provider"
            source_segment = provider_segment
            source_text = provider_segment["text"] if provider_segment else ""
            target_role = "patient"
            direction = "Provider → Interpreter → Patient"

        elif case_type in (TribunalCaseType.ALIGNED_INBOUND, TribunalCaseType.OMISSION_INBOUND):
            source_role = "patient"
            source_segment = patient_segment
            source_text = patient_segment["text"] if patient_segment else ""
            target_role = "provider"
            direction = "Patient → Interpreter → Provider"

        elif case_type == TribunalCaseType.FABRICATION:
            source_role = "none"
            source_segment = None
            source_text = ""
            target_role = "unknown"
            direction = "Interpreter spoke without prompt"

        else:
            # Fallback for unknown case types
            source_role = "provider"
            source_segment = provider_segment
            source_text = provider_segment["text"] if provider_segment else ""
            target_role = "patient"
            direction = "Unknown case type"

        interpreter_text = interpreter_segment["text"] if interpreter_segment else "[NO INTERPRETATION]"

        # ═══════════════════════════════════════════════════════════
        # ASR RELIABILITY CHECK: Don't judge interpreter on bad transcripts
        # ═══════════════════════════════════════════════════════════
        # Check if any segment is EXPLICITLY marked as unreliable
        # Only treat explicit False as unreliable; None/missing = assume reliable
        def is_asr_unreliable(seg):
            if not seg:
                return False
            val = seg.get("asr_reliable", True)
            return val is False  # Only explicit False triggers ASR gating

        source_unreliable = is_asr_unreliable(source_segment)
        interpreter_unreliable = is_asr_unreliable(interpreter_segment)

        # FIXED: Only check source and interpreter segments for this tribunal case
        # Don't redundantly check patient_segment (triadic context is separate)
        if source_unreliable or interpreter_unreliable:
            # ASR failed - emit system error, don't judge interpreter
            unreliable_segments = []
            if source_unreliable:
                source_lang = source_segment.get('detected_language', 'unknown') if source_segment else 'unknown'
                unreliable_segments.append(f"{source_role} segment (lang={source_lang})")
            if interpreter_unreliable:
                interp_lang = interpreter_segment.get('detected_language', 'unknown') if interpreter_segment else 'unknown'
                unreliable_segments.append(f"interpreter segment (lang={interp_lang})")

            asr_error = ClinicalError(
                error_id=f"err_{datetime.utcnow().timestamp()}_asr",
                severity=ErrorSeverity.MEDIUM,
                error_type="asr_unreliable",
                provider_entity=None,
                interpreter_entity=None,
                description=f"ASR transcription unreliable for {', '.join(unreliable_segments)}. Cannot judge interpreter on corrupted data.",
                arbiter_reasoning="ASR transcription failed or produced gibberish. Cannot judge interpreter performance on corrupted data.",
                confidence=0.3,
                detected_at=datetime.utcnow(),
                alignment_info=alignment,
                is_system_error=True,
                source_role=None,
                interpreter_quote=None,
                source_quote=None,
                ideal_interpretation=None,
            )

            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            print(f"⚠️ ASR UNRELIABLE: Skipping tribunal for {', '.join(unreliable_segments)}")

            return AgentDebateResult(
                extractor_entities=[],
                monitor_findings=[f"ASR unreliable for: {', '.join(unreliable_segments)}"],
                arbiter_decision="ASR transcription unreliable - interpreter not judged",
                detected_errors=[asr_error],
                processing_time_ms=processing_time,
            )

        # Handle omissions (no interpreter response)
        if not alignment["is_matched"] or not interpreter_segment:
            return self._handle_omission(alignment, start_time, source_role, source_text, case_type)

        # ═══════════════════════════════════════════════════════════
        # TRIBUNAL EXECUTION WITH ERROR HANDLING
        # Wrap in try/except so tribunal failures don't kill the whole cycle
        # ═══════════════════════════════════════════════════════════
        try:
            # ═══════════════════════════════════════════════════════════
            # PARALLEL EXECUTION: Node A and Node B run simultaneously
            # Node B is BLIND to Node A (anti-telephone pattern)
            # ═══════════════════════════════════════════════════════════

            extractor_task = asyncio.create_task(
                self.extractor.extract_comparison(
                    source_segment, interpreter_segment, alignment, patient_text,
                    source_role, target_role, case_type
                )
            )
            monitor_task = asyncio.create_task(
                self.monitor.analyze_independently(
                    source_text, interpreter_text, patient_text,
                    source_role, target_role, case_type
                )
            )

            # Wait for both to complete
            (extractor_json, extractor_notes), monitor_report = await asyncio.gather(
                extractor_task, monitor_task
            )

            # ═══════════════════════════════════════════════════════════
            # SEQUENTIAL: Node C (Arbiter) sees everything
            # ═══════════════════════════════════════════════════════════

            arbiter_reasoning, error_list = await self.arbiter.arbitrate(
                source_text=source_text,
                interpreter_text=interpreter_text,
                extractor_json=extractor_json,
                monitor_report=monitor_report,
                alignment=alignment,
                patient_text=patient_text,
                source_role=source_role,
                target_role=target_role,
                case_type=case_type,
            )

            # Convert error dicts to ClinicalError objects
            clinical_errors = []
            for err in error_list:
                severity_str = err.get("severity", "medium").lower()
                try:
                    severity = ErrorSeverity(severity_str)
                except ValueError:
                    severity = ErrorSeverity.MEDIUM

                # Determine if this is a system error or clinical error
                is_sys_error = err.get("type", "").lower() == "system_error"

                # ═══════════════════════════════════════════════════════════
                # SEMANTIC IMPORTANCE CALIBRATION
                # ═══════════════════════════════════════════════════════════
                # Adjust severity based on clinical impact, not just linguistic accuracy
                description_lower = err.get("description", "").lower()
                interpreter_quote_lower = (interpreter_text or "").lower()
                error_type = err.get("type", "unknown").lower()

                # DOWNGRADE: Likely pronunciation errors on names (Ramirez → Demirres)
                # These are LOW severity unless they cause clinical confusion
                if "name" in description_lower or "apellido" in description_lower or "last name" in description_lower:
                    if error_type in ["distortion", "distortion_medical"]:
                        # Check similarity score from alignment - if high, it's likely pronunciation
                        similarity = alignment.get("similarity_score", 0) if alignment else 0
                        if similarity > 0.5:  # Similar sounding names
                            severity = ErrorSeverity.LOW
                            print(f"      ⚙️  SEVERITY DOWNGRADE: Name pronunciation error ({similarity:.2f} similarity) → LOW")

                # CRITICAL: Body part substitutions (head → arm, cabeza → brazo)
                # These can cause serious clinical harm
                body_parts = ["head", "cabeza", "arm", "brazo", "leg", "pierna", "chest", "pecho",
                              "stomach", "estómago", "back", "espalda", "neck", "cuello",
                              "hand", "mano", "foot", "pie"]
                if any(part in interpreter_quote_lower or part in description_lower for part in body_parts):
                    if error_type in ["distortion", "distortion_medical", "fabrication"]:
                        severity = ErrorSeverity.CRITICAL
                        print(f"      ⚙️  SEVERITY UPGRADE: Body part error → CRITICAL")

                # CRITICAL: Medication/diagnosis/treatment errors
                # These directly impact patient safety
                medical_critical_terms = ["medication", "medicación", "medicine", "medicina",
                                         "diagnosis", "diagnóstico", "treatment", "tratamiento",
                                         "prescription", "receta", "dose", "dosis", "pill", "píldora",
                                         "surgery", "cirugía", "procedure", "procedimiento"]
                if any(term in interpreter_quote_lower or term in description_lower for term in medical_critical_terms):
                    if error_type in ["fabrication", "omission", "distortion", "fabrication_medical",
                                     "fabrication_diagnosis", "fabrication_treatment", "omission_critical"]:
                        severity = ErrorSeverity.CRITICAL
                        print(f"      ⚙️  SEVERITY UPGRADE: Medical information error → CRITICAL")

                clinical_error = ClinicalError(
                    error_id=f"err_{datetime.utcnow().timestamp()}_{len(clinical_errors)}",
                    severity=severity,
                    error_type=err.get("type", "unknown"),
                    provider_entity=None,  # Provider is ground truth, not graded
                    interpreter_entity=self._extract_entity_from_text(err.get("interpreter_said", ""), interpreter_segment) if interpreter_segment and not is_sys_error else None,
                    description=err.get("description", "Error detected"),
                    arbiter_reasoning=arbiter_reasoning,
                    confidence=0.85 if severity in [ErrorSeverity.CRITICAL, ErrorSeverity.HIGH] else 0.7,
                    detected_at=datetime.utcnow(),
                    alignment_info=alignment if not is_sys_error else None,
                    is_system_error=is_sys_error,
                    # Interpreter-centric tribunal context
                    source_role=source_role if not is_sys_error else None,  # type: ignore
                    interpreter_quote=interpreter_text if not is_sys_error else None,
                    source_quote=source_text if not is_sys_error else None,
                    # Sanitize ideal_interpretation: convert string "None" to actual None
                    ideal_interpretation=self._sanitize_ideal_interpretation(
                        err.get("should_have_said") or err.get("ideal_interpretation")
                    ) if not is_sys_error else None,
                )
                clinical_errors.append(clinical_error)

            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            # Build monitor findings from report
            monitor_findings = [line.strip() for line in monitor_report.split('\n') if line.strip() and not line.strip().lower().startswith('no significant')]

            return AgentDebateResult(
                extractor_entities=self._json_to_entities(extractor_json, source_segment),
                monitor_findings=monitor_findings[:5],  # Top 5 findings
                arbiter_decision=arbiter_reasoning,
                detected_errors=clinical_errors,
                processing_time_ms=processing_time,
            )

        except Exception as e:
            # Tribunal failed - emit system error but DON'T kill the cycle
            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            print(f"⚠️ Tribunal error for case_type={case_type}: {e}")

            system_error = ClinicalError(
                error_id=f"err_{datetime.utcnow().timestamp()}_system",
                severity=ErrorSeverity.HIGH,
                error_type="system_error",
                provider_entity=None,
                interpreter_entity=None,
                description=f"Tribunal processing failed: {str(e)[:200]}",
                arbiter_reasoning=f"System error during tribunal: {type(e).__name__}",
                confidence=0.5,
                detected_at=datetime.utcnow(),
                alignment_info=alignment,
                is_system_error=True,
                source_role=None,
                interpreter_quote=None,
                source_quote=None,
                ideal_interpretation=None,
            )

            return AgentDebateResult(
                extractor_entities=[],
                monitor_findings=[f"Tribunal error: {str(e)[:100]}"],
                arbiter_decision=f"System error: {type(e).__name__}",
                detected_errors=[system_error],
                processing_time_ms=processing_time,
            )

    def _handle_omission(
        self,
        alignment: AlignmentMatch,
        start_time: datetime,
        source_role: str,
        source_text: str,
        case_type: str,
    ) -> AgentDebateResult:
        """
        Handle omission cases (source spoke, interpreter didn't respond).

        This handles both OMISSION_OUTBOUND and OMISSION_INBOUND.
        """
        if case_type == TribunalCaseType.OMISSION_OUTBOUND:
            description = f"Provider said: '{source_text[:100]}...' but interpreter did not render it to patient"
            reasoning = "Provider statement was not interpreted within expected timeframe. Critical omission."
        elif case_type == TribunalCaseType.OMISSION_INBOUND:
            description = f"Patient said: '{source_text[:100]}...' but interpreter did not relay it to provider"
            reasoning = "Patient statement was not relayed to provider within expected timeframe. Critical omission."
        else:
            description = f"{source_role.capitalize()} spoke but interpreter did not respond"
            reasoning = "Omission detected - interpreter failed to render the message."

        error = ClinicalError(
            error_id=f"err_{datetime.utcnow().timestamp()}",
            severity=ErrorSeverity.CRITICAL,
            error_type="omission",  # Standardized error type
            provider_entity=None,  # Provider/patient are ground truth, not graded
            interpreter_entity=None,  # No interpreter utterance to extract from
            description=description,
            arbiter_reasoning=reasoning,
            confidence=0.95,
            detected_at=datetime.utcnow(),
            alignment_info=alignment,
            is_system_error=False,  # Clinical error, not infrastructure
        )

        processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000

        return AgentDebateResult(
            extractor_entities=[],
            monitor_findings=[f"CRITICAL: {source_role.capitalize()} spoke, interpreter silent - complete omission"],
            arbiter_decision=f"Critical: Interpreter omission in {case_type} case",
            detected_errors=[error],
            processing_time_ms=processing_time,
        )

    def _sanitize_ideal_interpretation(self, value: Any) -> Optional[str]:
        """
        Convert string 'None' to actual None for ideal_interpretation.
        LLMs sometimes return the string 'None' instead of null/empty.
        """
        if value is None:
            return None
        if isinstance(value, str):
            # Strip whitespace and check for string 'None'
            stripped = value.strip()
            if stripped == "None" or stripped == "" or stripped == "null":
                return None
            return value
        return None  # If it's not a string, return None

    def _extract_entity_from_text(
        self,
        text: str,
        segment: TranscriptSegment,
    ) -> MedicalEntity:
        """Create a basic MedicalEntity from text."""
        return MedicalEntity(
            entity_type="extracted",
            text=text[:200] if text else "",
            normalized=text[:200].lower() if text else "",
            confidence=0.5,
            timestamp=segment["timestamp"],
            context=segment["text"],
            embedding=None,
        )

    def _json_to_entities(
        self,
        extractor_json: Dict[str, Any],
        segment: TranscriptSegment,
    ) -> List[MedicalEntity]:
        """Convert extractor JSON to MedicalEntity list."""
        entities = []

        for fact in extractor_json.get("provider_facts", []):
            if isinstance(fact, dict):
                entities.append(MedicalEntity(
                    entity_type=fact.get("type", "unknown"),
                    text=fact.get("value", ""),
                    normalized=fact.get("normalized", fact.get("value", "")),
                    confidence=0.8,
                    timestamp=segment["timestamp"],
                    context=segment["text"],
                    embedding=None,
                ))

        return entities
