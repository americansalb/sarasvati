"""
SARASVATI Adversarial Agent System
===================================
The "Trisul Protocol" - Three agents debate clinical accuracy.

Node A (Extractor): Extracts medical entities from Provider stream
Node B (Monitor): Checks Interpreter stream for omissions
Node C (Arbiter): Makes final decision using weighted similarity + negation check

This module uses Groq API for fast inference with Llama-3 models.
"""

import os
import json
import re
from typing import List, Dict, Optional, Any
from datetime import datetime
import asyncio
from enum import Enum

try:
    from groq import AsyncGroq
except ImportError:
    # Fallback for development
    AsyncGroq = None

from .state import (
    MedicalEntity,
    TranscriptSegment,
    AlignmentMatch,
    ClinicalError,
    ErrorSeverity,
    AgentDebateResult,
)


class GroqModel(str, Enum):
    """Groq model identifiers."""
    LLAMA_70B = "llama-3.1-70b-versatile"  # For verification (high accuracy)
    LLAMA_8B = "llama-3.1-8b-instant"      # For speculative drafting (fast)


class NodeAExtractor:
    """
    Node A: The Extractor Agent

    Listens to Provider stream and extracts critical medical entities:
    - Medications/Drugs
    - Dosages
    - Frequencies
    - Conditions/Diagnoses
    - Critical instructions
    """

    def __init__(self, groq_client: AsyncGroq, model: str = GroqModel.LLAMA_8B):
        self.client = groq_client
        self.model = model

    async def extract_entities(
        self,
        provider_segment: TranscriptSegment,
    ) -> List[MedicalEntity]:
        """
        Extract medical entities from provider's speech.

        Uses Groq LLM with structured prompting to identify:
        1. Drug names
        2. Dosages (with units)
        3. Frequencies (daily, twice daily, etc.)
        4. Conditions/symptoms
        5. Instructions (take with food, avoid alcohol, etc.)

        Args:
            provider_segment: Transcript from provider

        Returns:
            List of extracted medical entities
        """
        text = provider_segment["text"]

        # Build extraction prompt
        prompt = self._build_extraction_prompt(text)

        # Call Groq API
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a medical entity extraction system. "
                            "Extract ONLY factual medical information from clinical speech. "
                            "Output valid JSON only."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,  # Low temperature for consistent extraction
                max_tokens=1000,
            )

            # Parse response
            content = response.choices[0].message.content
            entities = self._parse_extraction_response(
                content,
                provider_segment,
            )

            return entities

        except Exception as e:
            print(f"[NodeA] Extraction error: {e}")
            # Fallback to rule-based extraction
            return self._fallback_extraction(provider_segment)

    def _build_extraction_prompt(self, text: str) -> str:
        """Build the extraction prompt for the LLM."""
        return f"""Extract all medical entities from this clinical speech:

"{text}"

Extract the following entity types:
1. DRUG: Medication names (brand or generic)
2. DOSAGE: Drug amounts with units (e.g., "500mg", "two tablets")
3. FREQUENCY: How often to take medication (e.g., "twice daily", "every 8 hours")
4. CONDITION: Diagnoses, symptoms, medical conditions
5. INSTRUCTION: Critical directions (e.g., "take with food", "avoid alcohol")

Return ONLY a JSON array in this exact format:
[
  {{
    "entity_type": "drug",
    "text": "ibuprofen",
    "normalized": "ibuprofen",
    "confidence": 0.95
  }},
  {{
    "entity_type": "dosage",
    "text": "500 milligrams",
    "normalized": "500mg",
    "confidence": 0.90
  }}
]

If no entities found, return: []
"""

    def _parse_extraction_response(
        self,
        response_text: str,
        segment: TranscriptSegment,
    ) -> List[MedicalEntity]:
        """Parse LLM response into MedicalEntity objects."""
        entities: List[MedicalEntity] = []

        try:
            # Extract JSON from response (may have markdown code blocks)
            json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
            if not json_match:
                return []

            parsed = json.loads(json_match.group())

            for item in parsed:
                entity = MedicalEntity(
                    entity_type=item["entity_type"],
                    text=item["text"],
                    normalized=item.get("normalized", item["text"]),
                    confidence=item.get("confidence", 0.5),
                    timestamp=segment["timestamp"],
                    context=segment["text"],
                    embedding=None,  # Populated later by alignment engine
                )
                entities.append(entity)

        except json.JSONDecodeError:
            print(f"[NodeA] Failed to parse JSON: {response_text[:100]}")

        return entities

    def _fallback_extraction(
        self,
        segment: TranscriptSegment,
    ) -> List[MedicalEntity]:
        """
        Rule-based fallback extraction when LLM fails.

        Uses regex patterns for common medical entities.
        """
        text = segment["text"]
        entities: List[MedicalEntity] = []

        # Pattern: Dosage (number + unit)
        dosage_pattern = r'\b(\d+(?:\.\d+)?)\s*(mg|milligram|gram|g|ml|milliliter|tablet|capsule|unit)s?\b'
        for match in re.finditer(dosage_pattern, text, re.IGNORECASE):
            entities.append(MedicalEntity(
                entity_type="dosage",
                text=match.group(0),
                normalized=match.group(0).lower(),
                confidence=0.6,
                timestamp=segment["timestamp"],
                context=text,
                embedding=None,
            ))

        # Pattern: Frequency
        frequency_pattern = r'\b(once|twice|three times|daily|per day|every \d+ hours)\b'
        for match in re.finditer(frequency_pattern, text, re.IGNORECASE):
            entities.append(MedicalEntity(
                entity_type="frequency",
                text=match.group(0),
                normalized=match.group(0).lower(),
                confidence=0.7,
                timestamp=segment["timestamp"],
                context=text,
                embedding=None,
            ))

        return entities


class NodeBMonitor:
    """
    Node B: The Monitor Agent

    Checks the Interpreter stream for omissions or errors.
    Compares against entities extracted by Node A.
    """

    def __init__(self, groq_client: AsyncGroq, model: str = GroqModel.LLAMA_8B):
        self.client = groq_client
        self.model = model

    async def check_interpretation(
        self,
        provider_entities: List[MedicalEntity],
        interpreter_segment: TranscriptSegment,
    ) -> List[str]:
        """
        Check if interpreter covered all critical entities.

        Args:
            provider_entities: Entities extracted by Node A
            interpreter_segment: What the interpreter actually said

        Returns:
            List of findings (issues detected)
        """
        if not provider_entities:
            return []

        prompt = self._build_monitoring_prompt(
            provider_entities,
            interpreter_segment["text"],
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a medical interpretation quality monitor. "
                            "Your job is to identify OMISSIONS or ERRORS in medical interpretation. "
                            "Be strict: patient safety depends on accuracy."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=800,
            )

            content = response.choices[0].message.content
            findings = self._parse_monitoring_response(content)

            return findings

        except Exception as e:
            print(f"[NodeB] Monitoring error: {e}")
            return self._fallback_monitoring(provider_entities, interpreter_segment)

    def _build_monitoring_prompt(
        self,
        entities: List[MedicalEntity],
        interpreter_text: str,
    ) -> str:
        """Build the monitoring prompt."""
        entities_str = "\n".join([
            f"- {e['entity_type'].upper()}: {e['text']}"
            for e in entities
        ])

        return f"""The provider communicated these medical entities:
{entities_str}

The interpreter said:
"{interpreter_text}"

Analyze the interpretation for:
1. OMISSIONS: Did the interpreter skip any critical entities?
2. ERRORS: Did the interpreter change numbers, medications, or instructions?
3. NEGATION: Did the interpreter add or remove negations (no, not, never)?

List each issue found. Format:
- OMISSION: [entity] was not mentioned
- ERROR: [entity] was changed from X to Y
- NEGATION: Original had "no X" but interpretation has "X"

If interpretation is accurate, respond: "No issues detected."
"""

    def _parse_monitoring_response(self, response: str) -> List[str]:
        """Parse monitoring response into list of findings."""
        if "no issues detected" in response.lower():
            return []

        # Extract bullet points
        findings = []
        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("-") or line.startswith("•"):
                findings.append(line.lstrip("-•").strip())

        return findings

    def _fallback_monitoring(
        self,
        entities: List[MedicalEntity],
        interpreter_segment: TranscriptSegment,
    ) -> List[str]:
        """Rule-based fallback monitoring."""
        findings = []
        interpreter_text = interpreter_segment["text"].lower()

        for entity in entities:
            entity_text = entity["normalized"].lower()

            # Simple substring check (crude but better than nothing)
            if entity_text not in interpreter_text:
                findings.append(
                    f"OMISSION: {entity['entity_type']} '{entity['text']}' not found"
                )

        return findings


class NodeCArbiter:
    """
    Node C: The Arbiter Agent

    Makes final decision on whether an error occurred.
    Uses Groq Llama-3-70b for high-accuracy verification.

    Performs:
    1. Weighted cosine similarity check
    2. Cross-examination of Node A and Node B findings
    3. Negation-aware final judgment
    """

    def __init__(self, groq_client: AsyncGroq, model: str = GroqModel.LLAMA_70B):
        self.client = groq_client
        self.model = model

    async def arbitrate(
        self,
        provider_entities: List[MedicalEntity],
        monitor_findings: List[str],
        alignment: AlignmentMatch,
    ) -> AgentDebateResult:
        """
        Make final decision on interpretation quality.

        This is the critical decision point that determines if an alert
        should be sent to supervisors.

        Args:
            provider_entities: What Node A extracted
            monitor_findings: What Node B flagged
            alignment: Alignment info with similarity scores

        Returns:
            Final debate result with errors (if any)
        """
        start_time = datetime.utcnow()

        # If no findings from Monitor, likely no issues
        if not monitor_findings and alignment["similarity_score"] > 0.8:
            return self._create_clean_result(
                provider_entities,
                monitor_findings,
                start_time,
            )

        # Build arbitration prompt
        prompt = self._build_arbitration_prompt(
            provider_entities,
            monitor_findings,
            alignment,
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are the final arbiter in a medical interpretation quality system. "
                            "Patient safety is paramount. Make a definitive judgment on whether "
                            "the interpretation contains critical errors. Be conservative: "
                            "if uncertain, flag for human review."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,  # Very low temp for consistent judgments
                max_tokens=1500,
            )

            content = response.choices[0].message.content
            result = self._parse_arbitration(
                content,
                provider_entities,
                monitor_findings,
                alignment,
                start_time,
            )

            return result

        except Exception as e:
            print(f"[NodeC] Arbitration error: {e}")
            return self._fallback_arbitration(
                provider_entities,
                monitor_findings,
                alignment,
                start_time,
            )

    def _build_arbitration_prompt(
        self,
        entities: List[MedicalEntity],
        findings: List[str],
        alignment: AlignmentMatch,
    ) -> str:
        """Build the arbitration prompt."""
        entities_str = "\n".join([
            f"- {e['entity_type'].upper()}: {e['text']}"
            for e in entities
        ])

        findings_str = "\n".join([f"- {f}" for f in findings])

        provider_text = alignment["provider_segment"]["text"]
        interpreter_text = (
            alignment["interpreter_segment"]["text"]
            if alignment["interpreter_segment"]
            else "[NO MATCH FOUND]"
        )

        return f"""CASE FOR ARBITRATION

Provider said:
"{provider_text}"

Interpreter said:
"{interpreter_text}"

Extracted entities from provider:
{entities_str}

Monitor flagged these issues:
{findings_str}

Semantic similarity score: {alignment["similarity_score"]:.2f}

Your task: Determine if there are CRITICAL ERRORS that require alerting.

Classify each issue by severity:
- CRITICAL: Negation errors, wrong dosages, omitted medications
- HIGH: Missing key medical info
- MEDIUM: Partial omissions
- LOW: Minor linguistic differences

Return JSON:
{{
  "verdict": "ERRORS_DETECTED" or "NO_CRITICAL_ERRORS",
  "reasoning": "your analysis",
  "errors": [
    {{
      "severity": "critical",
      "type": "negation_mismatch",
      "description": "..."
    }}
  ]
}}
"""

    def _parse_arbitration(
        self,
        response: str,
        entities: List[MedicalEntity],
        findings: List[str],
        alignment: AlignmentMatch,
        start_time: datetime,
    ) -> AgentDebateResult:
        """Parse arbitration response into structured result."""
        try:
            # Extract JSON
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON found in response")

            parsed = json.loads(json_match.group())

            # Create clinical errors from parsed response
            clinical_errors = []
            for error_data in parsed.get("errors", []):
                error = ClinicalError(
                    error_id=f"err_{datetime.utcnow().timestamp()}",
                    severity=ErrorSeverity(error_data["severity"]),
                    error_type=error_data["type"],
                    provider_entity=entities[0] if entities else None,
                    interpreter_entity=None,
                    description=error_data["description"],
                    arbiter_reasoning=parsed["reasoning"],
                    confidence=0.85,
                    detected_at=datetime.utcnow(),
                    alignment_info=alignment,
                )
                clinical_errors.append(error)

            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            return AgentDebateResult(
                extractor_entities=entities,
                monitor_findings=findings,
                arbiter_decision=parsed["reasoning"],
                detected_errors=clinical_errors,
                processing_time_ms=processing_time,
            )

        except Exception as e:
            print(f"[NodeC] Parse error: {e}")
            return self._fallback_arbitration(
                entities,
                findings,
                alignment,
                start_time,
            )

    def _create_clean_result(
        self,
        entities: List[MedicalEntity],
        findings: List[str],
        start_time: datetime,
    ) -> AgentDebateResult:
        """Create result when no errors detected."""
        processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000

        return AgentDebateResult(
            extractor_entities=entities,
            monitor_findings=findings,
            arbiter_decision="No critical errors detected. Interpretation is accurate.",
            detected_errors=[],
            processing_time_ms=processing_time,
        )

    def _fallback_arbitration(
        self,
        entities: List[MedicalEntity],
        findings: List[str],
        alignment: AlignmentMatch,
        start_time: datetime,
    ) -> AgentDebateResult:
        """Fallback arbitration when LLM fails."""
        processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000

        # Conservative approach: if Monitor found issues, flag them
        errors = []
        if findings:
            for finding in findings:
                severity = ErrorSeverity.HIGH
                if "negation" in finding.lower():
                    severity = ErrorSeverity.CRITICAL
                elif "omission" in finding.lower() and "dosage" in finding.lower():
                    severity = ErrorSeverity.CRITICAL

                error = ClinicalError(
                    error_id=f"err_{datetime.utcnow().timestamp()}",
                    severity=severity,
                    error_type="potential_error",
                    provider_entity=entities[0] if entities else None,
                    interpreter_entity=None,
                    description=finding,
                    arbiter_reasoning="Fallback rule-based detection",
                    confidence=0.6,
                    detected_at=datetime.utcnow(),
                    alignment_info=alignment,
                )
                errors.append(error)

        return AgentDebateResult(
            extractor_entities=entities,
            monitor_findings=findings,
            arbiter_decision="Fallback arbitration used",
            detected_errors=errors,
            processing_time_ms=processing_time,
        )


class ClinicalDebateOrchestrator:
    """
    High-level orchestrator for the three-agent debate system.

    This class coordinates Node A, B, and C to produce final clinical
    error assessments.
    """

    def __init__(self, groq_api_key: str):
        if AsyncGroq is None:
            raise ImportError("groq package not installed. Install with: pip install groq")

        self.client = AsyncGroq(api_key=groq_api_key)

        # Initialize agents
        self.extractor = NodeAExtractor(self.client, GroqModel.LLAMA_8B)
        self.monitor = NodeBMonitor(self.client, GroqModel.LLAMA_8B)
        self.arbiter = NodeCArbiter(self.client, GroqModel.LLAMA_70B)

    async def run_debate(
        self,
        alignment: AlignmentMatch,
    ) -> AgentDebateResult:
        """
        Run the full three-agent debate pipeline.

        Flow:
        1. Node A extracts entities from provider
        2. Node B checks interpreter for omissions
        3. Node C arbitrates and makes final decision

        Args:
            alignment: Aligned provider-interpreter segments

        Returns:
            Debate result with detected errors
        """
        # Step 1: Node A extraction
        provider_entities = await self.extractor.extract_entities(
            alignment["provider_segment"]
        )

        # If no interpreter match, flag as omission
        if not alignment["is_matched"] or not alignment["interpreter_segment"]:
            return self._handle_no_match(provider_entities, alignment)

        # Step 2: Node B monitoring
        monitor_findings = await self.monitor.check_interpretation(
            provider_entities,
            alignment["interpreter_segment"],
        )

        # Step 3: Node C arbitration
        result = await self.arbiter.arbitrate(
            provider_entities,
            monitor_findings,
            alignment,
        )

        return result

    def _handle_no_match(
        self,
        entities: List[MedicalEntity],
        alignment: AlignmentMatch,
    ) -> AgentDebateResult:
        """Handle case where no interpreter match was found."""
        error = ClinicalError(
            error_id=f"err_{datetime.utcnow().timestamp()}",
            severity=ErrorSeverity.CRITICAL,
            error_type="complete_omission",
            provider_entity=entities[0] if entities else None,
            interpreter_entity=None,
            description="No matching interpretation found in search window",
            arbiter_reasoning="Provider statement was not interpreted within expected timeframe",
            confidence=0.9,
            detected_at=datetime.utcnow(),
            alignment_info=alignment,
        )

        return AgentDebateResult(
            extractor_entities=entities,
            monitor_findings=["Complete omission - no interpretation detected"],
            arbiter_decision="Critical: Provider statement not interpreted",
            detected_errors=[error],
            processing_time_ms=0.0,
        )
