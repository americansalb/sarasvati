"""
SARASVATI Independent Tribunal System
======================================
The "Trisul Protocol" - Three UNIQUE agents in CONSENSUS DEBATE.

Architecture (3 UNIQUE MODELS - EQUAL capability, all CHEAP!):
- Agent A: Llama 3.1 8B (Groq) - FREE, Meta architecture
- Agent B: GPT-4o-mini (OpenAI) - $0.15/1M, OpenAI newest efficient
- Agent C: GPT-3.5-turbo (OpenAI) - $0.50/1M, OpenAI older (different training)

All 3 are "efficient tier" models with EQUAL capability but DIFFERENT:
- Different training data (Meta vs OpenAI 2024 vs OpenAI 2022)
- Different architectures (Llama vs GPT-4 family vs GPT-3.5 family)

DEBATE FLOW (not hierarchical - true consensus):
1. ROUND 1 - Independent Analysis:
   - All 3 agents see ONLY raw evidence (source + interpreter text)
   - Each forms their own opinion WITHOUT seeing the others
   - This prevents anchoring bias

2. ROUND 2 - Cross-Examination:
   - All 3 agents see each other's Round 1 opinions
   - Each can CHALLENGE or AGREE with the others
   - They refine their positions based on peer arguments

3. ROUND 3+ - Consensus:
   - If 2/3 agree → consensus reached
   - If all disagree → continue debate (max 3 rounds)
   - Final verdict = majority or "needs human review"

Providers: Groq (FREE) + OpenAI (cheap)
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

try:
    from anthropic import AsyncAnthropic
except ImportError:
    AsyncAnthropic = None

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

# DeepSeek uses OpenAI-compatible API
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

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
# MUST BE 3 SEPARATE LLMs - Configure via environment variables:
#
# TRIBUNAL_MODEL_A = Model for Agent A (default: llama-3.1-8b-instant)
# TRIBUNAL_MODEL_B = Model for Agent B (default: gpt-4o-mini)
# TRIBUNAL_MODEL_C = Model for Agent C (default: gpt-3.5-turbo)
#
# TRIBUNAL_PROVIDER_A = Provider for Agent A: "groq" | "openai" | "deepseek" (default: groq)
# TRIBUNAL_PROVIDER_B = Provider for Agent B: "groq" | "openai" | "deepseek" (default: openai)
# TRIBUNAL_PROVIDER_C = Provider for Agent C: "groq" | "openai" | "deepseek" (default: openai)
#
# API Keys needed:
# - GROQ_API_KEY (for Groq models)
# - OPENAI_API_KEY (for OpenAI models)
# - DEEPSEEK_API_KEY (for DeepSeek models) - optional

DEFAULT_MODEL_A = os.getenv("TRIBUNAL_MODEL_A", "llama-3.1-8b-instant")
DEFAULT_MODEL_B = os.getenv("TRIBUNAL_MODEL_B", "gpt-4o-mini")
DEFAULT_MODEL_C = os.getenv("TRIBUNAL_MODEL_C", "gpt-3.5-turbo")

DEFAULT_PROVIDER_A = os.getenv("TRIBUNAL_PROVIDER_A", "groq").lower()
DEFAULT_PROVIDER_B = os.getenv("TRIBUNAL_PROVIDER_B", "openai").lower()
DEFAULT_PROVIDER_C = os.getenv("TRIBUNAL_PROVIDER_C", "openai").lower()

# Legacy defaults (for backwards compatibility)
DEFAULT_MODEL_EXTRACTOR = DEFAULT_MODEL_A
DEFAULT_MODEL_MONITOR = DEFAULT_MODEL_A  # Fallback
DEFAULT_MODEL_MONITOR_OPENAI = DEFAULT_MODEL_B
DEFAULT_MODEL_ARBITER = DEFAULT_MODEL_C

# Future Claude integration (disabled by default - expensive)
DEFAULT_MODEL_MONITOR_CLAUDE = "claude-sonnet-4-20250514"

# Provider selection for Monitor node
# Options: "openai" (default), "groq", "claude"
MONITOR_PROVIDER = os.getenv("TRIBUNAL_MONITOR_PROVIDER", "openai").lower()


class NodeAExtractor:
    """
    Node A: The Extractor (Prosecution)

    Model: llama-3.1-8b-instant (Meta Llama 8B) - Fast extraction model
    NOTE: Previously used Mixtral, but Groq decommissioned it in late 2024.

    Inputs: Raw provider_segment, Raw interpreter_segment, Alignment metadata
    Output: Structured JSON comparing Provider Facts vs Interpreter Facts

    Role: "You are a clinical extraction engine. Produce STRICT JSON."

    Why Llama 8B: Fast enough for extraction, paired with OpenAI for provider diversity.
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
        # ═══════════════════════════════════════════════════════════
        # CRITICAL: Use English translations, not raw text
        # ═══════════════════════════════════════════════════════════
        # Source (provider/patient) uses SMOOTH translation (ground truth)
        # Interpreter uses LITERAL translation (error-preserving)
        # This matches the orchestrator's logic in run_debate()
        if source_segment:
            source_text = (
                source_segment.get("text_english_smooth")  # Natural English for provider/patient
                or source_segment.get("text_english")      # Backwards compat
                or source_segment.get("text")              # Fallback to raw
                or "[NO SOURCE]"
            )
        else:
            source_text = "[NO SOURCE]"

        if interpreter_segment:
            interpreter_text = (
                interpreter_segment.get("text_english_literal")  # Error-preserving for interpreter
                or interpreter_segment.get("text_english_smooth") # Fallback if literal not available
                or interpreter_segment.get("text_english")        # Backwards compat
                or interpreter_segment.get("text")                # Fallback to raw
                or "[NO INTERPRETATION]"
            )
        else:
            interpreter_text = "[NO INTERPRETATION]"

        # Build context string
        patient_context = f'\nPATIENT CONTEXT:\n"{patient_text}"\n' if patient_text else ""

        prompt = f"""You are a clinical extraction engine evaluating INTERPRETER PERFORMANCE.

CRITICAL: You are ONLY judging the interpreter's accuracy. The {source_role.upper()} is GROUND TRUTH.

⚠️ CANONICAL ENGLISH TRANSLATION: The English text below is from a medical translation ensemble.
DO NOT re-translate or reinterpret non-English text yourself. Use the provided English as ground truth.

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

    Model: llama-3.1-8b-instant (fallback) or gpt-4o-mini (preferred via OpenAI)
    NOTE: Previously used Mixtral, but Groq decommissioned it in late 2024.

    Inputs: Raw provider_segment["text"], Raw interpreter_segment["text"]
    Constraint: Node B MUST NOT see Node A's JSON. It is BLIND to prevent anchoring bias.

    Role: "You are a skeptic. Read the utterances directly. Identify omissions/shifts yourself."
    Output: Plain-text critique (NOT JSON)

    Why OpenAI preferred: Different provider than Groq ensures independence.
    Fallback to Llama 8B if no OpenAI key available.
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

⚠️ CANONICAL ENGLISH TRANSLATION: The English text below is from a medical translation ensemble.
DO NOT re-translate or reinterpret non-English text yourself. Use the provided English as ground truth.

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


class NodeBMonitorClaude:
    """
    Node B: The Monitor (Defense/Skeptic) - CLAUDE VERSION

    Model: Claude Sonnet (Anthropic) - True provider diversity

    This is an OPTIONAL alternative to NodeBMonitor that uses Anthropic's Claude
    instead of Groq's Mixtral. Provides true provider diversity in the tribunal.

    Enable with: TRIBUNAL_USE_CLAUDE=true and ANTHROPIC_API_KEY set

    Why Claude for Monitor:
    - Different training philosophy than Meta/Mistral models
    - Excellent at critical analysis and finding edge cases
    - Reduces systematic bias from using all-Groq models
    """

    def __init__(self, anthropic_client: "AsyncAnthropic", model: str = DEFAULT_MODEL_MONITOR_CLAUDE):
        self.client = anthropic_client
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
        Independently analyze INTERPRETER PERFORMANCE using Claude.

        Same interface as NodeBMonitor for drop-in replacement.
        """
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
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                messages=[
                    {"role": "user", "content": prompt},
                ],
                system="You are a skeptical medical monitor. You see NO prior analysis. Read the text directly and identify issues yourself.",
            )

            return response.content[0].text

        except Exception as e:
            return f"Claude Monitor error: {e}. Flagging for manual review."


class NodeBMonitorOpenAI:
    """
    Node B: The Monitor (Defense/Skeptic) - OPENAI VERSION

    Model: GPT-4o-mini (OpenAI) - Cost-effective provider diversity

    This uses OpenAI's GPT-4o-mini for the Monitor node, providing true
    provider diversity (Groq + OpenAI) at a reasonable cost.

    Why OpenAI for Monitor:
    - Different provider than Groq (Meta/Mistral)
    - GPT-4o-mini is fast and cost-effective
    - Good at critical analysis
    """

    def __init__(self, openai_client: "AsyncOpenAI", model: str = DEFAULT_MODEL_MONITOR_OPENAI):
        self.client = openai_client
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
        Independently analyze INTERPRETER PERFORMANCE using OpenAI.

        Same interface as NodeBMonitor for drop-in replacement.
        """
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
            return f"OpenAI Monitor error: {e}. Flagging for manual review."


class NodeCArbiter:
    """
    Node C: The Arbiter (Senior Judge)

    Model: llama-3.3-70b-versatile (Meta 70B) - Largest model for complex judicial reasoning

    Inputs:
        - Raw Evidence (Provider + Interpreter Text)
        - Node A's JSON (Prosecution)
        - Node B's Report (Defense)

    Role: "You are a Senior Medical Judge. Node A and B are junior analysts.
           If their claims conflict with the Raw Evidence, OVERRIDE them."

    Output: Final ClinicalError JSON

    Why 70B: The Arbiter prompt has 15+ distinct rules, 30+ error types, cultural
    equivalency exceptions, and severity calibration logic. This is the most complex
    reasoning task in the tribunal - it NEEDS the biggest model to follow all rules
    reliably. An 8B model would miss nuances and fail to apply the full ruleset.
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

⚠️ CANONICAL ENGLISH TRANSLATION REQUIREMENT ⚠️
For any non-English utterance, you MUST use the provided English text as the true meaning.
The English translations below are from a specialized medical translation ensemble (single source of truth).
DO NOT reinterpret or re-translate the original script yourself.
DO NOT second-guess the English translations provided.
Assume the English text is accurate and represents the speaker's true intent.

ZERO TOLERANCE for:
1. MEDICAL FABRICATIONS: Any invented diagnosis, symptom, treatment, or medical fact → ALWAYS CRITICAL
2. BODY-SHAMING/HARASSMENT: Insulting patient's appearance, weight, or person → ALWAYS HIGH or CRITICAL
3. FABRICATED CLINICAL CONTENT: Adding medical info not in source → ALWAYS CRITICAL

═══════════════════════════════════════════════════════════
LOGICAL CONSISTENCY CHECK (CRITICAL)
═══════════════════════════════════════════════════════════

⚠️ Check whether the INTERPRETER's rendition is logically possible and clinically sensible.

RED FLAGS indicating distortion or incoherent output:
- **Plural bodies**: "pain in other bodies" (a person has ONE body) → CRITICAL
- **Broken idioms**: "I'm sorry because I listen" instead of "I'm sorry to hear that" → HIGH/CRITICAL
- **Impossible anatomy**: Multiple heads, extra organs, etc. → CRITICAL
- **Nonsensical phrasing**: "I talk that you have pain" → HIGH
- **Absurd contradictions**: Saying opposite things in same sentence → HIGH/CRITICAL

If the interpreter's sentence is physically impossible, medically absurd, or sounds nonsensical
to a fluent speaker, flag it as distortion_medical or incoherent, EVEN IF keywords look similar.

EXAMPLES:
- Provider: "Do you have pain anywhere else?"
  Interpreter: "Do you have pain in other bodies?"
  → FLAG as CRITICAL distortion_medical (plural "bodies" is absurd)

- Provider: "I'm sorry to hear that."
  Interpreter: "I'm sorry because I listen."
  → FLAG as HIGH distortion (broken idiom, nonsensical)

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

ACCEPTABLE PARAPHRASES (not distortion_medical):
- "breathing with some difficulty" ↔ "difficulty breathing / difficulty to breathe" (same symptom)
- "tightness in the chest" ↔ "pressure in the chest / chest pressure" (same symptom)
- "shortness of breath" ↔ "lack of breathing / lack of air" (same symptom)
- "since his admission this morning" ↔ "since they admitted him to the hospital this morning" (same timeframe)
- "history of COPD" ↔ "his history of COPD / with his COPD history" (same medical fact)
- "recent pneumonia" ↔ "the pneumonia he had recently" (same medical fact)

⚠️ EXAMPLE OF CORRECT (NO ERROR) INTERPRETATION:
Provider: "He has been breathing with some difficulty, tightness in the chest and shortness of breath, which is expected given his history of COPD and the recent pneumonia."

Interpreter (ES→EN): "He has been with difficulty to breathe and has felt pressure in the chest and a little lack of breathing, which is to be expected with his history of COPD and the pneumonia that he had recently."

→ This is ACCURATE. All symptoms preserved (difficulty breathing, chest pressure, shortness of breath).
→ All context preserved (COPD history, recent pneumonia, expected outcome).
→ DO NOT flag as distortion_medical. This is acceptable paraphrase.

ONLY flag distortion_medical when there is a CLINICALLY MEANINGFUL change:
1. Drug/medicine name (e.g., "insulin" → "paracetamol")
2. Dose (e.g., "one pill" → "three pills")
3. Frequency (e.g., "twice" → "once", "morning" → "evening")
4. Body part (e.g., "head" → "stomach", "chest" → "abdomen")
5. Symptom addition/removal (e.g., adding "fever" when not mentioned)
6. Negation flip (e.g., "no pain" → "has pain", "don't take" → "take")
7. Laterality (e.g., "left arm" → "right arm")
8. Severity change (e.g., "mild" → "severe", "some" → "extreme")
9. Temporal change (e.g., "today" → "last week", "recent" → "chronic")

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

            # ═══════════════════════════════════════════════════════════
            # ROBUST JSON EXTRACTION
            # ═══════════════════════════════════════════════════════════
            # The Arbiter sometimes returns valid JSON followed by extra text, causing
            # "Extra data: line X column Y" errors. We need to extract ONLY the first
            # complete JSON object, ignoring any trailing content.

            # Try to find the first complete JSON object by matching braces
            def extract_first_json(text: str) -> Optional[str]:
                """Extract the first complete JSON object from text, handling nested braces."""
                first_brace = text.find('{')
                if first_brace == -1:
                    return None

                brace_count = 0
                in_string = False
                escape_next = False

                for i in range(first_brace, len(text)):
                    char = text[i]

                    # Handle escape sequences in strings
                    if escape_next:
                        escape_next = False
                        continue

                    if char == '\\':
                        escape_next = True
                        continue

                    # Track string boundaries (ignore braces inside strings)
                    if char == '"':
                        in_string = not in_string
                        continue

                    if not in_string:
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            # Found the closing brace for the first complete JSON object
                            if brace_count == 0:
                                return text[first_brace:i+1]

                return None  # No complete JSON object found

            json_str = extract_first_json(content)

            if json_str:
                try:
                    parsed = json.loads(json_str)

                    # Log if there was extra data after the JSON (for debugging)
                    remaining = content[content.find(json_str) + len(json_str):].strip()
                    if remaining:
                        print(f"⚠️ ARBITER WARNING: Extra content after JSON (length={len(remaining)})")
                        print(f"   First 100 chars: {remaining[:100]}")

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

                except json.JSONDecodeError as json_err:
                    # Still failed to parse - log full details
                    print(f"🚨 ARBITER JSON PARSE ERROR: {json_err}")
                    print(f"   Attempted to parse: {json_str[:200]}...")
                    print(f"   Full response length: {len(content)}")
                    print(f"   Full response:\n{content}")
                    return (
                        f"Failed to parse arbiter JSON: {json_err}",
                        [{"severity": "high", "type": "system_error", "description": f"Arbiter JSON parse error: {json_err}"}]
                    )
            else:
                # No JSON object found at all
                print(f"🚨 ARBITER NO JSON FOUND in response:")
                print(f"   Response length: {len(content)}")
                print(f"   Response: {content[:500]}...")
                return (
                    "No JSON found in arbiter response",
                    [{"severity": "high", "type": "system_error", "description": "Arbiter returned no JSON"}]
                )

        except Exception as e:
            # Catch all other errors (API errors, timeout, etc.)
            print(f"🚨 ARBITER EXCEPTION: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return (
                f"Arbiter error: {e}",
                [{"severity": "high", "type": "system_error", "description": f"Arbiter failed: {e}"}]
            )


# ═══════════════════════════════════════════════════════════════════════════════
# DEBATE AGENT - Unified agent for consensus-based tribunal
# ═══════════════════════════════════════════════════════════════════════════════

class DebateAgent:
    """
    A unified debate agent that can use any provider (Groq, OpenAI, Anthropic).

    Each agent participates in a multi-round debate:
    - Round 1: Form independent opinion from raw evidence
    - Round 2+: See peer opinions, refine/challenge
    - Vote: Final position for consensus
    """

    def __init__(
        self,
        name: str,
        client: Any,
        model: str,
        provider: str,  # "groq", "openai", or "anthropic"
    ):
        self.name = name
        self.client = client
        self.model = model
        self.provider = provider

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call the LLM with provider-specific API."""
        try:
            if self.provider == "anthropic":
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=1500,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                return response.content[0].text
            else:  # groq or openai (same API)
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=1500,
                )
                return response.choices[0].message.content
        except Exception as e:
            return f"[{self.name} ERROR: {e}]"

    async def round1_analyze(
        self,
        source_text: str,
        interpreter_text: str,
        source_role: str,
        case_type: str,
    ) -> Dict[str, Any]:
        """
        ROUND 1: Form independent opinion from raw evidence only.
        No peer opinions visible yet.
        """
        system_prompt = f"""You are {self.name}, a medical interpretation analyst.
You are part of a 3-agent tribunal evaluating interpreter performance.

CRITICAL: Form your OWN opinion. You will see peer opinions in Round 2.
For now, analyze ONLY the raw evidence below."""

        user_prompt = f"""CASE TYPE: {case_type}

{source_role.upper()} SAID (GROUND TRUTH):
"{source_text}"

INTERPRETER'S RENDITION:
"{interpreter_text}"

Analyze the interpreter's performance. Look for:
1. OMISSIONS - Did they miss critical info?
2. FABRICATIONS - Did they add things not said?
3. DISTORTIONS - Did they change meaning (especially numbers, negations, medications)?
4. If accurate, say so clearly.

Respond with JSON:
{{
  "verdict": "accurate" | "minor_issues" | "significant_errors" | "critical_errors",
  "errors": [
    {{"type": "omission|fabrication|distortion", "severity": "low|medium|high|critical", "description": "..."}}
  ],
  "reasoning": "Brief explanation of your analysis"
}}"""

        response = await self._call_llm(system_prompt, user_prompt)

        # Parse JSON from response
        try:
            # Find JSON in response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️ {self.name} round1 JSON parse error: {e}")

        return {
            "verdict": "error",
            "errors": [],
            "reasoning": response,
            "raw_response": response
        }

    async def round2_crossexamine(
        self,
        source_text: str,
        interpreter_text: str,
        source_role: str,
        case_type: str,
        peer_opinions: Dict[str, Dict],
    ) -> Dict[str, Any]:
        """
        ROUND 2: See peer opinions, challenge or agree, refine position.
        """
        # Format peer opinions
        peers_text = ""
        for peer_name, opinion in peer_opinions.items():
            if peer_name != self.name:
                peers_text += f"\n{peer_name}'s ANALYSIS:\n"
                peers_text += f"  Verdict: {opinion.get('verdict', 'unknown')}\n"
                peers_text += f"  Reasoning: {opinion.get('reasoning', 'N/A')}\n"
                if opinion.get('errors'):
                    peers_text += f"  Errors found: {len(opinion['errors'])}\n"
                    for err in opinion['errors'][:3]:  # Show first 3
                        peers_text += f"    - {err.get('severity', '?')}: {err.get('description', '?')[:100]}\n"

        system_prompt = f"""You are {self.name}, a medical interpretation analyst.
This is ROUND 2 of the debate. You now see your peers' opinions.

You may:
- AGREE with a peer's finding you missed
- CHALLENGE a peer's finding you think is wrong
- MAINTAIN your position with new justification
- CHANGE your verdict based on peer arguments"""

        user_prompt = f"""ORIGINAL EVIDENCE:
{source_role.upper()}: "{source_text}"
INTERPRETER: "{interpreter_text}"

YOUR ROUND 1 ANALYSIS:
Verdict: {peer_opinions.get(self.name, {}).get('verdict', 'unknown')}
Reasoning: {peer_opinions.get(self.name, {}).get('reasoning', 'N/A')}

PEER OPINIONS:{peers_text}

After considering your peers' analysis, what is your REFINED position?

Respond with JSON:
{{
  "verdict": "accurate" | "minor_issues" | "significant_errors" | "critical_errors",
  "errors": [...],
  "reasoning": "Your refined analysis, noting agreements/disagreements with peers",
  "agreements": ["Agent X correctly identified...", ...],
  "challenges": ["I disagree with Agent Y because...", ...]
}}"""

        response = await self._call_llm(system_prompt, user_prompt)

        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️ {self.name} round2 JSON parse error: {e}")

        return {
            "verdict": "error",
            "errors": [],
            "reasoning": response,
            "raw_response": response
        }

    async def final_vote(
        self,
        source_text: str,
        interpreter_text: str,
        all_round2_opinions: Dict[str, Dict],
    ) -> Dict[str, Any]:
        """
        FINAL VOTE: After debate, cast final vote on interpreter performance.
        """
        # Summarize all positions
        positions = ""
        for agent_name, opinion in all_round2_opinions.items():
            positions += f"\n{agent_name}: {opinion.get('verdict', 'unknown')}"
            if opinion.get('errors'):
                positions += f" ({len(opinion['errors'])} errors found)"

        system_prompt = f"""You are {self.name}. This is your FINAL VOTE.
The debate is over. Cast your final verdict on the interpreter's performance."""

        user_prompt = f"""FINAL POSITIONS AFTER DEBATE:{positions}

YOUR ROUND 2 POSITION:
{json.dumps(all_round2_opinions.get(self.name, {}), indent=2)}

Cast your FINAL vote. The majority wins.

Respond with JSON:
{{
  "final_verdict": "accurate" | "minor_issues" | "significant_errors" | "critical_errors",
  "final_errors": [...],
  "confidence": 0.0-1.0,
  "consensus_note": "Do you agree with the majority? Why/why not?"
}}"""

        response = await self._call_llm(system_prompt, user_prompt)

        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️ {self.name} final_vote JSON parse error: {e}")

        return {"final_verdict": "error", "raw_response": response}


class ClinicalDebateOrchestrator:
    """
    Consensus-Based Tribunal Orchestrator

    Implements TRUE DEBATE between 3 agents:
    1. ROUND 1: All 3 analyze independently (no peer visibility)
    2. ROUND 2: All 3 see each other's opinions, refine positions
    3. VOTE: Majority verdict wins (2/3 agreement)

    Provider Diversity - FULLY CONFIGURABLE via environment variables:
    - TRIBUNAL_MODEL_A/B/C: Model names for each agent
    - TRIBUNAL_PROVIDER_A/B/C: Provider for each agent (groq/openai/deepseek)

    Example configurations:
    - Default: Groq (Llama 8B) + OpenAI (GPT-4o-mini) + OpenAI (GPT-3.5-turbo)
    - All Groq: 3 different Llama models (FREE but same family)
    - Mixed: Groq + OpenAI + DeepSeek (maximum diversity)
    """

    def __init__(
        self,
        groq_api_key: str,
        openai_api_key: str = "",
        anthropic_api_key: str = "",
        deepseek_api_key: str = "",
        model_a: str = DEFAULT_MODEL_A,
        model_b: str = DEFAULT_MODEL_B,
        model_c: str = DEFAULT_MODEL_C,
        provider_a: str = DEFAULT_PROVIDER_A,
        provider_b: str = DEFAULT_PROVIDER_B,
        provider_c: str = DEFAULT_PROVIDER_C,
    ):
        """
        Initialize the tribunal with configurable models and providers.

        Args:
            groq_api_key: API key for Groq (required)
            openai_api_key: API key for OpenAI (optional)
            anthropic_api_key: API key for Anthropic (optional, for future use)
            deepseek_api_key: API key for DeepSeek (optional)
            model_a: Model name for Agent A (default: llama-3.1-8b-instant)
            model_b: Model name for Agent B (default: gpt-4o-mini)
            model_c: Model name for Agent C (default: gpt-3.5-turbo)
            provider_a: Provider for Agent A: "groq" | "openai" | "deepseek"
            provider_b: Provider for Agent B: "groq" | "openai" | "deepseek"
            provider_c: Provider for Agent C: "groq" | "openai" | "deepseek"
        """
        # ═══════════════════════════════════════════════════════════
        # INITIALIZE ALL CLIENTS
        # ═══════════════════════════════════════════════════════════
        self.groq_client = None
        self.openai_client = None
        self.anthropic_client = None
        self.deepseek_client = None

        # Groq client (primary free option)
        if groq_api_key and AsyncGroq is not None:
            try:
                self.groq_client = AsyncGroq(api_key=groq_api_key)
                print(f"✅ Groq client initialized")
            except Exception as e:
                print(f"⚠️ Failed to initialize Groq client: {e}")

        # OpenAI client (cheap option)
        if openai_api_key and AsyncOpenAI is not None:
            try:
                self.openai_client = AsyncOpenAI(api_key=openai_api_key)
                print(f"✅ OpenAI client initialized")
            except Exception as e:
                print(f"⚠️ Failed to initialize OpenAI client: {e}")

        # DeepSeek client (cheap + different architecture)
        # Uses OpenAI-compatible API with different base URL
        if deepseek_api_key and AsyncOpenAI is not None:
            try:
                self.deepseek_client = AsyncOpenAI(
                    api_key=deepseek_api_key,
                    base_url=DEEPSEEK_BASE_URL,
                )
                print(f"✅ DeepSeek client initialized")
            except Exception as e:
                print(f"⚠️ Failed to initialize DeepSeek client: {e}")

        # Anthropic client (for future use - expensive)
        if anthropic_api_key and AsyncAnthropic is not None:
            try:
                self.anthropic_client = AsyncAnthropic(api_key=anthropic_api_key)
                print(f"✅ Anthropic client initialized")
            except Exception as e:
                print(f"⚠️ Failed to initialize Anthropic client: {e}")

        # ═══════════════════════════════════════════════════════════
        # HELPER: Get client for a provider
        # ═══════════════════════════════════════════════════════════
        def get_client_for_provider(provider: str, agent_name: str):
            """Get the appropriate client for a provider, with fallback logic."""
            provider = provider.lower()

            if provider == "groq":
                if self.groq_client:
                    return self.groq_client, "groq"
                print(f"⚠️ {agent_name}: Groq requested but no API key - falling back")

            elif provider == "openai":
                if self.openai_client:
                    return self.openai_client, "openai"
                print(f"⚠️ {agent_name}: OpenAI requested but no API key - falling back")

            elif provider == "deepseek":
                if self.deepseek_client:
                    return self.deepseek_client, "deepseek"
                print(f"⚠️ {agent_name}: DeepSeek requested but no API key - falling back")

            elif provider == "anthropic":
                if self.anthropic_client:
                    return self.anthropic_client, "anthropic"
                print(f"⚠️ {agent_name}: Anthropic requested but no API key - falling back")

            # Fallback priority: Groq (free) > OpenAI (cheap) > DeepSeek
            if self.groq_client:
                return self.groq_client, "groq"
            if self.openai_client:
                return self.openai_client, "openai"
            if self.deepseek_client:
                return self.deepseek_client, "deepseek"

            raise ValueError(f"No valid API client available for {agent_name}. Set at least one API key.")

        # ═══════════════════════════════════════════════════════════
        # CREATE 3 UNIQUE DEBATE AGENTS
        # ═══════════════════════════════════════════════════════════
        print(f"\n{'='*60}")
        print(f"🏛️  TRIBUNAL CONFIGURATION")
        print(f"{'='*60}")

        # Agent A
        client_a, actual_provider_a = get_client_for_provider(provider_a, "Agent-A")
        self.agent_a = DebateAgent(
            name=f"Agent-A ({model_a})",
            client=client_a,
            model=model_a,
            provider=actual_provider_a,
        )
        print(f"✅ Agent A: {model_a} via {actual_provider_a}")

        # Agent B
        client_b, actual_provider_b = get_client_for_provider(provider_b, "Agent-B")
        self.agent_b = DebateAgent(
            name=f"Agent-B ({model_b})",
            client=client_b,
            model=model_b,
            provider=actual_provider_b,
        )
        print(f"✅ Agent B: {model_b} via {actual_provider_b}")

        # Agent C
        client_c, actual_provider_c = get_client_for_provider(provider_c, "Agent-C")
        self.agent_c = DebateAgent(
            name=f"Agent-C ({model_c})",
            client=client_c,
            model=model_c,
            provider=actual_provider_c,
        )
        print(f"✅ Agent C: {model_c} via {actual_provider_c}")

        self.agents = [self.agent_a, self.agent_b, self.agent_c]

        # Store model info for debugging
        self.models = {
            "agent_a": {"name": self.agent_a.name, "model": self.agent_a.model, "provider": self.agent_a.provider},
            "agent_b": {"name": self.agent_b.name, "model": self.agent_b.model, "provider": self.agent_b.provider},
            "agent_c": {"name": self.agent_c.name, "model": self.agent_c.model, "provider": self.agent_c.provider},
        }

        # Check for model diversity
        unique_models = len(set([model_a, model_b, model_c]))
        unique_providers = len(set([actual_provider_a, actual_provider_b, actual_provider_c]))

        if unique_models < 3:
            print(f"⚠️ WARNING: Only {unique_models} unique models. Tribunal works best with 3 DIFFERENT models.")
        if unique_providers < 2:
            print(f"⚠️ WARNING: All agents use same provider ({actual_provider_a}). Consider adding provider diversity.")

        print(f"{'='*60}")
        print(f"📊 Diversity: {unique_models} unique models, {unique_providers} unique providers")
        print(f"{'='*60}\n")

        # Keep legacy references for backward compatibility
        self.extractor = NodeAExtractor(self.groq_client or client_a, model_a)
        self.monitor = NodeBMonitor(self.groq_client or client_a, DEFAULT_MODEL_MONITOR)
        self.arbiter = NodeCArbiter(self.groq_client or client_a, model_c)

    async def run_consensus_debate(
        self,
        source_text: str,
        interpreter_text: str,
        source_role: str,
        case_type: str,
    ) -> Dict[str, Any]:
        """
        Run a TRUE CONSENSUS DEBATE between all 3 agents.

        Flow:
        1. ROUND 1: All 3 agents analyze independently (parallel)
        2. ROUND 2: All 3 see each other's opinions, refine (parallel)
        3. CONSENSUS: Majority verdict wins (2/3 agreement)

        Returns dict with:
        - round1_opinions: Each agent's independent analysis
        - round2_opinions: Each agent's refined position after seeing peers
        - final_votes: Each agent's final vote
        - consensus_verdict: The majority verdict
        - consensus_errors: Merged error list from majority
        - debate_log: Full debate transcript for debugging
        """
        debate_log = []

        # ═══════════════════════════════════════════════════════════
        # ROUND 1: Independent Analysis (all 3 in parallel)
        # ═══════════════════════════════════════════════════════════
        print(f"\n{'='*60}")
        print(f"🗣️ DEBATE ROUND 1: Independent Analysis")
        print(f"{'='*60}")

        round1_tasks = [
            agent.round1_analyze(source_text, interpreter_text, source_role, case_type)
            for agent in self.agents
        ]
        round1_results = await asyncio.gather(*round1_tasks)

        round1_opinions = {}
        for agent, result in zip(self.agents, round1_results):
            round1_opinions[agent.name] = result
            print(f"\n{agent.name} verdict: {result.get('verdict', 'error')}")
            if result.get('errors'):
                print(f"  Errors: {len(result['errors'])}")
            debate_log.append({"round": 1, "agent": agent.name, "opinion": result})

        # ═══════════════════════════════════════════════════════════
        # ROUND 2: Cross-Examination (all 3 see peers, refine in parallel)
        # ═══════════════════════════════════════════════════════════
        print(f"\n{'='*60}")
        print(f"🔍 DEBATE ROUND 2: Cross-Examination")
        print(f"{'='*60}")

        round2_tasks = [
            agent.round2_crossexamine(
                source_text, interpreter_text, source_role, case_type, round1_opinions
            )
            for agent in self.agents
        ]
        round2_results = await asyncio.gather(*round2_tasks)

        round2_opinions = {}
        for agent, result in zip(self.agents, round2_results):
            round2_opinions[agent.name] = result
            print(f"\n{agent.name} refined verdict: {result.get('verdict', 'error')}")
            if result.get('agreements'):
                print(f"  Agreements: {result['agreements'][:2]}")
            if result.get('challenges'):
                print(f"  Challenges: {result['challenges'][:2]}")
            debate_log.append({"round": 2, "agent": agent.name, "opinion": result})

        # ═══════════════════════════════════════════════════════════
        # CONSENSUS: Count votes and determine majority
        # ═══════════════════════════════════════════════════════════
        print(f"\n{'='*60}")
        print(f"🗳️ CONSENSUS VOTING")
        print(f"{'='*60}")

        # Count verdicts
        verdict_counts = {}
        for agent_name, opinion in round2_opinions.items():
            verdict = opinion.get('verdict', 'error')
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1

        # Find majority (2/3 or more)
        consensus_verdict = None
        for verdict, count in verdict_counts.items():
            if count >= 2:
                consensus_verdict = verdict
                break

        # If no 2/3 majority, use the most severe verdict
        if not consensus_verdict:
            severity_order = ['critical_errors', 'significant_errors', 'minor_issues', 'accurate', 'error']
            for severity in severity_order:
                if severity in verdict_counts:
                    consensus_verdict = severity
                    break

        print(f"\n📊 Verdict counts: {verdict_counts}")
        print(f"✅ CONSENSUS: {consensus_verdict}")

        # Merge errors from agents who agree with consensus
        consensus_errors = []
        for agent_name, opinion in round2_opinions.items():
            if opinion.get('verdict') == consensus_verdict:
                for err in opinion.get('errors', []):
                    # Avoid duplicates
                    if not any(e.get('description') == err.get('description') for e in consensus_errors):
                        consensus_errors.append(err)

        # Map verdict to severity for compatibility
        verdict_to_severity = {
            'accurate': None,
            'minor_issues': 'medium',
            'significant_errors': 'high',
            'critical_errors': 'critical',
            'error': 'high',
        }

        return {
            "round1_opinions": round1_opinions,
            "round2_opinions": round2_opinions,
            "verdict_counts": verdict_counts,
            "consensus_verdict": consensus_verdict,
            "consensus_errors": consensus_errors,
            "consensus_severity": verdict_to_severity.get(consensus_verdict),
            "debate_log": debate_log,
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
        # CRITICAL: Use correct English translation mode:
        # - Provider/Patient: text_english_smooth (natural, fluent English)
        # - Interpreter: text_english_literal (error-preserving, literal English)
        if case_type in (TribunalCaseType.ALIGNED_OUTBOUND, TribunalCaseType.OMISSION_OUTBOUND):
            source_role = "provider"
            source_segment = provider_segment
            target_role = "patient"
            direction = "Provider → Interpreter → Patient"

            # Provider = ground truth, use smooth translation (explicit precedence)
            if provider_segment:
                source_text = (
                    provider_segment.get("text_english_smooth")
                    or provider_segment.get("text_english")  # backwards compat
                    or provider_segment.get("text")
                    or ""
                )
            else:
                source_text = ""

        elif case_type in (TribunalCaseType.ALIGNED_INBOUND, TribunalCaseType.OMISSION_INBOUND):
            source_role = "patient"
            source_segment = patient_segment
            target_role = "provider"
            direction = "Patient → Interpreter → Provider"

            # Patient = ground truth, use smooth translation (explicit precedence)
            if patient_segment:
                source_text = (
                    patient_segment.get("text_english_smooth")
                    or patient_segment.get("text_english")  # backwards compat
                    or patient_segment.get("text")
                    or ""
                )
            else:
                source_text = ""

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
            target_role = "patient"
            direction = "Unknown case type"

            # Provider = ground truth, use smooth translation (explicit precedence)
            if provider_segment:
                source_text = (
                    provider_segment.get("text_english_smooth")
                    or provider_segment.get("text_english")  # backwards compat
                    or provider_segment.get("text")
                    or ""
                )
            else:
                source_text = ""

        # Interpreter uses LITERAL translation (error-preserving)
        # This is CRITICAL: we must see the interpreter's actual errors
        # Example: "Lo siento porque yo escucho" → "I'm sorry because I listen" (NOT "I'm sorry to hear that")
        # FIXED: Explicit precedence to avoid operator precedence bugs
        if interpreter_segment:
            interpreter_text = (
                interpreter_segment.get("text_english_literal")  # Priority 1: literal for interpreter eval
                or interpreter_segment.get("text_english_smooth")  # Priority 2: smooth if literal not available
                or interpreter_segment.get("text_english")  # Priority 3: backwards compat
                or interpreter_segment.get("text")  # Priority 4: raw text
                or "[NO INTERPRETATION]"
            )
        else:
            interpreter_text = "[NO INTERPRETATION]"

        # ═══════════════════════════════════════════════════════════
        # ALIGNMENT SANITY CHECK: ALIGNED cases must have valid source
        # ═══════════════════════════════════════════════════════════
        # CRITICAL BUG FIX: If we have an ALIGNED case but no source text, this is a logic error
        # in the alignment layer, NOT an interpreter error. Never judge on invalid state.
        if case_type in (TribunalCaseType.ALIGNED_OUTBOUND, TribunalCaseType.ALIGNED_INBOUND):
            if not source_segment or not source_text or not source_text.strip():
                print(f"🚨 TRIBUNAL BUG: {case_type} case with NO_SOURCE segment")
                print(f"   Source segment exists: {source_segment is not None}")
                print(f"   Source text: '{source_text[:50] if source_text else 'EMPTY'}...'")
                print(f"   Segment IDs for debugging:")
                print(f"     provider_segment_id: {provider_segment.get('segment_id') if provider_segment else None}")
                print(f"     patient_segment_id: {patient_segment.get('segment_id') if patient_segment else None}")
                print(f"     interpreter_segment_id: {interpreter_segment.get('segment_id') if interpreter_segment else None}")
                print(f"   This is an alignment layer bug - returning system diagnostic (NOT interpreter error)")

                processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000

                # Return system diagnostic error (prefixed with "system_" for UI filtering)
                # This is NOT an interpreter error - it's a backend alignment bug
                system_error = ClinicalError(
                    error_id=f"err_{datetime.utcnow().timestamp()}_alignment_bug",
                    severity=ErrorSeverity.MEDIUM,
                    error_type="system_alignment_bug",  # system_ prefix excludes from interpreter metrics
                    provider_entity=None,
                    interpreter_entity=None,
                    description=f"Backend alignment bug: {case_type} case created without valid source segment. This is NOT an interpreter error - do not count toward interpreter QA metrics.",
                    arbiter_reasoning="System diagnostic: Alignment layer created ALIGNED case without source text. This indicates a bug in the Temporal-Semantic Buffer or DTW alignment, not interpreter performance.",
                    confidence=0.95,
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
                    monitor_findings=[f"System diagnostic: {case_type} with no source text (alignment layer bug)"],
                    arbiter_decision="Alignment layer bug - no source segment for ALIGNED case. Not grading interpreter.",
                    detected_errors=[system_error],
                    processing_time_ms=processing_time,
                )

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
        # TRIBUNAL CASE LOGGING (for debugging)
        # ═══════════════════════════════════════════════════════════
        print(f"\n{'='*70}")
        print(f"⚖️  TRIBUNAL CASE: {case_type}")
        print(f"{'='*70}")
        print(f"📋 Direction: {direction}")
        print(f"🎯 Source Role: {source_role} → Target Role: {target_role}")
        print(f"\n💬 SOURCE TEXT ({source_role}):")
        print(f"   {source_text[:200] if source_text else '[NONE]'}{'...' if source_text and len(source_text) > 200 else ''}")
        print(f"\n🔄 INTERPRETER TEXT:")
        print(f"   {interpreter_text[:200] if interpreter_text else '[NONE]'}{'...' if interpreter_text and len(interpreter_text) > 200 else ''}")
        print(f"\n📊 Segment IDs:")
        print(f"   Provider: {provider_segment.get('segment_id') if provider_segment else 'N/A'}")
        print(f"   Patient: {patient_segment.get('segment_id') if patient_segment else 'N/A'}")
        print(f"   Interpreter: {interpreter_segment.get('segment_id') if interpreter_segment else 'N/A'}")
        print(f"{'='*70}\n")

        # ═══════════════════════════════════════════════════════════
        # CONSENSUS DEBATE: All 3 agents debate and reach consensus
        # ═══════════════════════════════════════════════════════════
        try:
            # Run the 2-round consensus debate
            debate_result = await self.run_consensus_debate(
                source_text=source_text,
                interpreter_text=interpreter_text,
                source_role=source_role,
                case_type=case_type.value if hasattr(case_type, 'value') else str(case_type),
            )

            # Extract results from debate
            consensus_verdict = debate_result.get("consensus_verdict", "error")
            consensus_errors = debate_result.get("consensus_errors", [])
            round1_opinions = debate_result.get("round1_opinions", {})
            round2_opinions = debate_result.get("round2_opinions", {})

            # Build arbiter_reasoning from debate summary
            arbiter_reasoning = f"CONSENSUS: {consensus_verdict}. "
            arbiter_reasoning += f"Votes: {debate_result.get('verdict_counts', {})}. "

            # Collect agreements and challenges from round 2
            for agent_name, opinion in round2_opinions.items():
                if opinion.get('agreements'):
                    arbiter_reasoning += f"{agent_name} agreed: {opinion['agreements'][:1]}. "
                if opinion.get('challenges'):
                    arbiter_reasoning += f"{agent_name} challenged: {opinion['challenges'][:1]}. "

            # Convert consensus errors to error_list format
            error_list = []
            for err in consensus_errors:
                error_list.append({
                    "severity": err.get("severity", "medium"),
                    "type": err.get("type", "unknown"),
                    "description": err.get("description", "No description"),
                })

            # Log consensus results
            print(f"\n⚖️  CONSENSUS RESULT:")
            print(f"   Verdict: {consensus_verdict}")
            print(f"   Votes: {debate_result.get('verdict_counts', {})}")
            print(f"   Errors detected: {len(error_list)}")
            if error_list:
                for idx, err in enumerate(error_list):
                    print(f"   [{idx+1}] {err.get('severity', '?').upper()}: {err.get('type', '?')} - {err.get('description', '?')[:80]}...")
            else:
                print(f"   ✅ No errors detected")
            print()

            # ═══════════════════════════════════════════════════════════
            # DEDUPLICATION: Prevent double-tagging same issue
            # ═══════════════════════════════════════════════════════════
            # If we have both distortion and omission for the same content,
            # keep only the distortion (more specific) and drop the omission
            error_list = self._deduplicate_errors(error_list)

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

            # Build monitor findings from consensus debate round 1 opinions
            # Extract key findings from each agent's reasoning
            monitor_findings = []
            for agent_name, opinion in round1_opinions.items():
                reasoning = opinion.get('reasoning', '')
                if reasoning and not reasoning.lower().startswith('no significant'):
                    monitor_findings.append(f"{agent_name}: {reasoning[:150]}")

            # Build extractor entities from round 1 opinions (errors found)
            extractor_entities = []
            if source_segment:
                for agent_name, opinion in round1_opinions.items():
                    for err in opinion.get('errors', []):
                        if isinstance(err, dict):
                            extractor_entities.append(MedicalEntity(
                                entity_type=err.get('type', 'unknown'),
                                text=err.get('description', '')[:100],
                                normalized=err.get('description', '')[:100].lower(),
                                confidence=0.7,
                                timestamp=source_segment.get('timestamp', 0.0),
                                context=source_text[:200] if source_text else '',
                                embedding=None,
                            ))

            return AgentDebateResult(
                extractor_entities=extractor_entities,
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
        case_type: TribunalCaseType,
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

        # Get case_type value for display (handle both enum and string)
        case_type_str = case_type.value if hasattr(case_type, 'value') else str(case_type)

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
            arbiter_decision=f"Critical: Interpreter omission in {case_type_str} case",
            detected_errors=[error],
            processing_time_ms=processing_time,
        )

    def _deduplicate_errors(self, error_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Prevent double-tagging: Remove redundant error classifications.

        Hierarchy (from most to least dominant):
        1. Fabrication: Interpreter spoke without prompt → Can't also be distortion/omission
        2. Distortion: Interpreter changed meaning → More specific than omission
        3. Omission: Interpreter missed info → Generic, least specific

        Note: This handles subtypes like fabrication_medical, distortion_medical, omission_critical
        by checking if the base type is contained in the error_type string.

        Logic:
        - If fabrication* exists, drop ALL distortion*/omission* tags (can't distort/omit non-existent source)
        - If distortion* exists (but no fabrication*), drop omissions* (distortion is more specific)
        - Otherwise, keep all errors
        """
        if len(error_list) <= 1:
            return error_list

        # Categorize errors by base type family (handles subtypes like *_medical, *_critical)
        fabrications = []
        distortions = []
        omissions = []
        others = []

        for err in error_list:
            error_type = err.get("type", "").lower()
            # Check base type family
            if "fabrication" in error_type:
                fabrications.append(err)
            elif "distortion" in error_type:
                distortions.append(err)
            elif "omission" in error_type:
                omissions.append(err)
            else:
                others.append(err)

        # Rule 1: Fabrication is dominant - can't distort/omit what doesn't exist
        if fabrications:
            if distortions or omissions:
                fab_types = [e.get("type") for e in fabrications]
                dist_types = [e.get("type") for e in distortions]
                omit_types = [e.get("type") for e in omissions]
                print(f"      🔧 DEDUPLICATION: Dropping {len(distortions)} distortion(s) {dist_types} and {len(omissions)} omission(s) {omit_types} because {len(fabrications)} fabrication(s) {fab_types} found (fabrication is dominant)")
            return fabrications + others

        # Rule 2: Distortion is more specific than omission
        if distortions and omissions:
            dist_types = [e.get("type") for e in distortions]
            omit_types = [e.get("type") for e in omissions]
            print(f"      🔧 DEDUPLICATION: Dropping {len(omissions)} omission(s) {omit_types} because {len(distortions)} distortion(s) {dist_types} found (distortion is more specific)")
            return distortions + others

        # Otherwise return all errors
        return error_list

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
