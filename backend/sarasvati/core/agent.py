"""
SARASVATI Independent Tribunal System
======================================
The "Trisul Protocol" - Three diverse agents with anti-telephone data flow.

Architecture:
- Node A (Extractor): llama-3.1-8b-instant (Meta) - Structured JSON extraction
- Node B (Monitor): gemma2-9b-it (Google) - Blind skeptic, independent analysis
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
)


# ===== Default Models (can be overridden via env) =====

DEFAULT_MODEL_EXTRACTOR = "llama-3.1-8b-instant"    # Node A: Meta - Fast/Structured
DEFAULT_MODEL_MONITOR = "gemma2-9b-it"              # Node B: Google - Diversity
DEFAULT_MODEL_ARBITER = "llama-3.3-70b-versatile"   # Node C: Meta - Heavy Judge


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
        provider_segment: TranscriptSegment,
        interpreter_segment: Optional[TranscriptSegment],
        alignment: AlignmentMatch,
        patient_text: str = "",
    ) -> Tuple[Dict[str, Any], str]:
        """
        Extract and compare medical facts from all three streams (Trisul Protocol).

        Returns:
            Tuple of (structured_json, extractor_notes)
        """
        provider_text = provider_segment["text"]
        interpreter_text = interpreter_segment["text"] if interpreter_segment else "[NO INTERPRETATION]"

        # Build patient context for triadic validation
        patient_context = f'\nPATIENT SAID (in their language):\n"{patient_text}"\n' if patient_text else ""

        prompt = f"""You are a clinical extraction engine. Your task is to extract medical facts from ALL utterances and produce a structured comparison.

PROVIDER SAID:
"{provider_text}"

INTERPRETER SAID:
"{interpreter_text}"
{patient_context}
ALIGNMENT SCORE: {alignment["similarity_score"]:.2f}
TIME DELTA: {alignment["time_delta"]:.1f} seconds

Extract ALL medical entities from ALL utterances. Compare them side-by-side.
IMPORTANT: If interpreter claims to translate what the patient said, verify it matches the patient's actual words.

Return ONLY valid JSON in this exact format:
{{
  "provider_facts": [
    {{"type": "drug|dosage|frequency|condition|instruction", "value": "exact text", "normalized": "standardized form"}}
  ],
  "interpreter_facts": [
    {{"type": "drug|dosage|frequency|condition|instruction", "value": "exact text", "normalized": "standardized form"}}
  ],
  "discrepancies": [
    {{"provider_fact": "X", "interpreter_fact": "Y or MISSING", "severity": "critical|high|medium|low", "reason": "explanation"}}
  ],
  "extractor_verdict": "MATCH|PARTIAL|MISMATCH|CRITICAL_ERROR"
}}

Be precise. Patient safety depends on accuracy."""

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

    Model: gemma2-9b-it (Google) - DIFFERENT training data for diversity

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
        provider_text: str,
        interpreter_text: str,
        patient_text: str = "",
    ) -> str:
        """
        Independently analyze the utterances without seeing Node A's output.
        Implements Trisul Protocol - triangulates all three streams.

        Returns:
            Plain-text critique
        """
        # Build patient context for triadic validation
        patient_section = f'''
PATIENT'S ACTUAL STATEMENT (in their language):
"{patient_text}"
''' if patient_text else ""

        triangulation_note = """
6. BACK-TRANSLATION VERIFICATION: If interpreter claims to translate what the patient said,
   does it actually match the patient's statement? Watch for malicious fabrications!""" if patient_text else ""

        prompt = f"""You are a SKEPTICAL medical interpretation monitor. You do NOT see any prior extraction or analysis. Read the text yourself.

PROVIDER'S ORIGINAL STATEMENT:
"{provider_text}"

INTERPRETER'S RENDITION:
"{interpreter_text}"
{patient_section}
Your job: Be a skeptic. Assume errors exist until proven otherwise.

Analyze for:
1. OMISSIONS: What critical info did the interpreter skip?
2. ADDITIONS: What did the interpreter add that wasn't in the original?
3. CHANGES: What was modified (numbers, negations, medications)?
4. NEGATION FLIPS: Did "do not take" become "take" or vice versa?
5. SEVERITY: If you find issues, are they life-threatening?{triangulation_note}

Write a plain-text critique. Be specific. Quote the exact words that concern you.

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
        provider_text: str,
        interpreter_text: str,
        extractor_json: Dict[str, Any],
        monitor_report: str,
        alignment: AlignmentMatch,
        patient_text: str = "",
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Make final judgment based on raw evidence and junior analysts' reports.
        Implements Trisul Protocol - triangulates all three streams.

        Returns:
            Tuple of (reasoning, list of error dicts)
        """
        # Build patient evidence section
        patient_evidence = f'''
PATIENT'S ACTUAL STATEMENT (in their language):
"{patient_text}"
''' if patient_text else ""

        triangulation_rule = """
6. TRIANGULATION (CRITICAL): If interpreter claims "the patient said X", verify against
   the patient's ACTUAL statement above. Malicious interpreters may fabricate insults
   or false claims - catch them by comparing to what the patient REALLY said!
""" if patient_text else ""

        prompt = f"""You are a SENIOR MEDICAL JUDGE presiding over a clinical interpretation case.

═══════════════════════════════════════════════════════════
PRIMARY EVIDENCE (Trust this above all else)
═══════════════════════════════════════════════════════════

PROVIDER'S ORIGINAL STATEMENT:
"{provider_text}"

INTERPRETER'S RENDITION:
"{interpreter_text}"
{patient_evidence}

═══════════════════════════════════════════════════════════
JUNIOR ANALYST REPORTS (These may contain errors)
═══════════════════════════════════════════════════════════

NODE A (Extractor - Structured Analysis):
{json.dumps(extractor_json, indent=2)}

NODE B (Monitor - Skeptical Critique):
{monitor_report}

═══════════════════════════════════════════════════════════
YOUR DUTY AS SENIOR JUDGE
═══════════════════════════════════════════════════════════

1. The PRIMARY EVIDENCE is your ground truth
2. Node A and B are junior analysts - they may have made errors
3. If Node A or B claims something that contradicts the raw text, OVERRIDE them
4. If Node A and B disagree, go back to the raw text to decide
5. Patient safety is paramount - when in doubt, flag for human review
{triangulation_rule}
SEVERITY GUIDE:
- CRITICAL: Wrong medication, wrong dosage, negation flip (e.g., "do not" → "do"), FABRICATED statements about what patient said
- HIGH: Omitted key medical information
- MEDIUM: Partial omission or imprecise translation
- LOW: Minor linguistic differences, acceptable paraphrasing

Return ONLY valid JSON:
{{
  "verdict": "NO_ERRORS|MINOR_ISSUES|ERRORS_DETECTED|CRITICAL_ERRORS",
  "reasoning": "Your judicial analysis (2-3 sentences)",
  "override_notes": "If you overrode Node A or B, explain why",
  "errors": [
    {{
      "severity": "critical|high|medium|low",
      "type": "omission|negation_flip|dosage_error|medication_error|other",
      "description": "Specific description of the error",
      "provider_said": "exact quote",
      "interpreter_said": "exact quote or MISSING"
    }}
  ]
}}

If no errors: return {{"verdict": "NO_ERRORS", "reasoning": "...", "override_notes": null, "errors": []}}"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a Senior Medical Judge. Raw evidence is primary. Junior analysts (Node A/B) may be wrong. Override them if needed."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=2000,
            )

            content = response.choices[0].message.content

            # Parse JSON from response
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                reasoning = parsed.get("reasoning", "No reasoning provided")
                if parsed.get("override_notes"):
                    reasoning += f" [OVERRIDE: {parsed['override_notes']}]"
                return (reasoning, parsed.get("errors", []))
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
        Run the Independent Tribunal with anti-telephone data flow.
        Implements Trisul Protocol - triangulates Provider ↔ Interpreter ↔ Patient.

        Flow:
        1. Node A (Extractor) and Node B (Monitor) run IN PARALLEL
        2. Node B does NOT see Node A's output (blind analysis)
        3. All nodes see patient_text for triangulation
        4. Node C (Arbiter) receives raw evidence + both reports
        5. Node C can OVERRIDE junior analysts
        """
        start_time = datetime.utcnow()

        provider_segment = alignment["provider_segment"]
        interpreter_segment = alignment["interpreter_segment"]

        provider_text = provider_segment["text"]
        interpreter_text = interpreter_segment["text"] if interpreter_segment else "[NO INTERPRETATION FOUND]"

        # Handle case where no interpreter match
        if not alignment["is_matched"] or not interpreter_segment:
            return self._handle_no_match(alignment, start_time)

        # ═══════════════════════════════════════════════════════════
        # PARALLEL EXECUTION: Node A and Node B run simultaneously
        # Node B is BLIND to Node A (anti-telephone pattern)
        # ═══════════════════════════════════════════════════════════

        extractor_task = asyncio.create_task(
            self.extractor.extract_comparison(provider_segment, interpreter_segment, alignment, patient_text)
        )
        monitor_task = asyncio.create_task(
            self.monitor.analyze_independently(provider_text, interpreter_text, patient_text)
        )

        # Wait for both to complete
        (extractor_json, extractor_notes), monitor_report = await asyncio.gather(
            extractor_task, monitor_task
        )

        # ═══════════════════════════════════════════════════════════
        # SEQUENTIAL: Node C (Arbiter) sees everything
        # ═══════════════════════════════════════════════════════════

        arbiter_reasoning, error_list = await self.arbiter.arbitrate(
            provider_text=provider_text,
            interpreter_text=interpreter_text,
            extractor_json=extractor_json,
            monitor_report=monitor_report,
            alignment=alignment,
            patient_text=patient_text,
        )

        # Convert error dicts to ClinicalError objects
        clinical_errors = []
        for err in error_list:
            severity_str = err.get("severity", "medium").lower()
            try:
                severity = ErrorSeverity(severity_str)
            except ValueError:
                severity = ErrorSeverity.MEDIUM

            clinical_error = ClinicalError(
                error_id=f"err_{datetime.utcnow().timestamp()}_{len(clinical_errors)}",
                severity=severity,
                error_type=err.get("type", "unknown"),
                provider_entity=self._extract_entity_from_text(err.get("provider_said", ""), provider_segment),
                interpreter_entity=self._extract_entity_from_text(err.get("interpreter_said", ""), interpreter_segment) if interpreter_segment else None,
                description=err.get("description", "Error detected"),
                arbiter_reasoning=arbiter_reasoning,
                confidence=0.85 if severity in [ErrorSeverity.CRITICAL, ErrorSeverity.HIGH] else 0.7,
                detected_at=datetime.utcnow(),
                alignment_info=alignment,
            )
            clinical_errors.append(clinical_error)

        processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000

        # Build monitor findings from report
        monitor_findings = [line.strip() for line in monitor_report.split('\n') if line.strip() and not line.strip().lower().startswith('no significant')]

        return AgentDebateResult(
            extractor_entities=self._json_to_entities(extractor_json, provider_segment),
            monitor_findings=monitor_findings[:5],  # Top 5 findings
            arbiter_decision=arbiter_reasoning,
            detected_errors=clinical_errors,
            processing_time_ms=processing_time,
        )

    def _handle_no_match(
        self,
        alignment: AlignmentMatch,
        start_time: datetime,
    ) -> AgentDebateResult:
        """Handle case where no interpreter match was found."""
        provider_segment = alignment["provider_segment"]

        error = ClinicalError(
            error_id=f"err_{datetime.utcnow().timestamp()}",
            severity=ErrorSeverity.CRITICAL,
            error_type="complete_omission",
            provider_entity=self._extract_entity_from_text(provider_segment["text"], provider_segment),
            interpreter_entity=None,
            description="No matching interpretation found within search window",
            arbiter_reasoning="Provider statement was not interpreted within expected timeframe. This is a critical omission.",
            confidence=0.95,
            detected_at=datetime.utcnow(),
            alignment_info=alignment,
        )

        processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000

        return AgentDebateResult(
            extractor_entities=[],
            monitor_findings=["CRITICAL: Complete omission - no interpretation detected"],
            arbiter_decision="Critical: Provider statement not interpreted",
            detected_errors=[error],
            processing_time_ms=processing_time,
        )

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
