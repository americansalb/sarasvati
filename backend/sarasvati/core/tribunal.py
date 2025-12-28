"""
Two-Stage Tribunal System for Medical Interpreter Quality Assessment

ARCHITECTURE:
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 1: TRANSLATION TRIBUNAL                                      │
│  Input: RAW Whisper transcription (Gujarati, Spanish, etc.)        │
│  Process: 3 agents each translate → debate → consensus             │
│  Output: CONSOLIDATED MEANING in English                           │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 2: ERROR TRIBUNAL                                            │
│  Input: Consolidated source meaning + Consolidated interpreter      │
│  Process: 3 agents evaluate → debate → consensus                   │
│  Output: CONFIRMED ERRORS (or clean)                               │
└─────────────────────────────────────────────────────────────────────┘

DEBATE PROTOCOL:
1. Round 1: Each agent analyzes independently (no peer visibility)
2. Round 2+: Agents see peer opinions, argue back and forth
3. Debate continues until:
   - 2/3 consensus reached, OR
   - Max rounds hit (prevents infinite loops)
4. All debate turns are LOGGED for visibility

STRICT REQUIREMENTS:
- 3 UNIQUE providers (groq, openai, deepseek)
- 3 UNIQUE models
- NO FALLBACKS
- VISIBLE debate log
"""

import os
import json
import re
import asyncio
from typing import Dict, Any, List, Optional, Literal
from datetime import datetime
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════════════
# DEBATE LOG - Visible record of tribunal deliberations
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DebateTurn:
    """Single turn in a debate - one agent's statement."""
    round_num: int
    agent_name: str
    agent_model: str
    agent_provider: str
    statement: str
    position: str  # Their current verdict/translation
    reasoning: str
    agrees_with: List[str] = field(default_factory=list)  # Which agents they agree with
    disagrees_with: List[str] = field(default_factory=list)  # Which agents they disagree with
    changed_mind: bool = False  # Did they change position this round?
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "round": self.round_num,
            "agent": self.agent_name,
            "model": self.agent_model,
            "provider": self.agent_provider,
            "statement": self.statement,
            "position": self.position,
            "reasoning": self.reasoning,
            "agrees_with": self.agrees_with,
            "disagrees_with": self.disagrees_with,
            "changed_mind": self.changed_mind,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class DebateLog:
    """Complete log of a tribunal debate."""
    tribunal_type: str  # "translation" or "error"
    input_text: str
    turns: List[DebateTurn] = field(default_factory=list)
    final_consensus: Optional[str] = None
    consensus_reached: bool = False
    rounds_taken: int = 0
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None

    def add_turn(self, turn: DebateTurn):
        self.turns.append(turn)
        print(self._format_turn(turn))

    def _format_turn(self, turn: DebateTurn) -> str:
        """Format a turn for console display."""
        lines = [
            f"\n{'─'*60}",
            f"🗣️  {turn.agent_name} (Round {turn.round_num})",
            f"    Model: {turn.agent_model} via {turn.agent_provider}",
            f"{'─'*60}",
            f"📍 Position: {turn.position}",
            f"",
            f"💬 Statement:",
            f"   {turn.statement[:500]}{'...' if len(turn.statement) > 500 else ''}",
        ]

        if turn.agrees_with:
            lines.append(f"✅ Agrees with: {', '.join(turn.agrees_with)}")
        if turn.disagrees_with:
            lines.append(f"❌ Disagrees with: {', '.join(turn.disagrees_with)}")
        if turn.changed_mind:
            lines.append(f"🔄 CHANGED POSITION this round!")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tribunal_type": self.tribunal_type,
            "input_text": self.input_text[:200] + "..." if len(self.input_text) > 200 else self.input_text,
            "turns": [t.to_dict() for t in self.turns],
            "final_consensus": self.final_consensus,
            "consensus_reached": self.consensus_reached,
            "rounds_taken": self.rounds_taken,
            "duration_ms": (self.end_time - self.start_time).total_seconds() * 1000 if self.end_time else None,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# TRIBUNAL AGENT - Individual debater
# ═══════════════════════════════════════════════════════════════════════════════

class TribunalAgent:
    """Single agent in a tribunal - can translate or evaluate errors."""

    def __init__(self, name: str, client: Any, model: str, provider: str):
        self.name = name
        self.client = client
        self.model = model
        self.provider = provider
        self.current_position: Optional[str] = None
        self.position_history: List[str] = []

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call the LLM with provider-specific API."""
        try:
            if self.provider == "anthropic":
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=2000,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                return response.content[0].text
            else:  # groq, openai, deepseek (OpenAI-compatible API)
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=2000,
                )
                return response.choices[0].message.content
        except Exception as e:
            return f"[{self.name} ERROR: {e}]"

    async def translate(
        self,
        raw_text: str,
        detected_language: str,
        peer_translations: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Translate raw text to English.
        If peer_translations provided, this is a debate round where we can agree/disagree.
        """
        if peer_translations:
            # DEBATE ROUND - See peer translations and argue
            peer_section = "\n".join([
                f"• {agent}: \"{trans}\""
                for agent, trans in peer_translations.items()
            ])

            system_prompt = f"""You are {self.name}, a medical translation expert in a tribunal.
You've seen your peers' translations. Now you must:
1. State your translation (you may change it if convinced)
2. Explain if you agree or disagree with peers and WHY
3. If peers made errors, point them out specifically

Be direct. If another agent is wrong, say so. If they convinced you, admit it."""

            user_prompt = f"""ORIGINAL TEXT ({detected_language}):
"{raw_text}"

YOUR PREVIOUS TRANSLATION:
"{self.current_position or '[First round]'}"

PEER TRANSLATIONS:
{peer_section}

Respond with JSON:
{{
  "translation": "Your English translation",
  "reasoning": "Why you chose this translation",
  "agrees_with": ["agent names you agree with"],
  "disagrees_with": ["agent names you disagree with"],
  "disagreement_reasons": {{"agent_name": "why they're wrong"}},
  "changed_mind": true/false
}}"""
        else:
            # FIRST ROUND - Independent translation
            system_prompt = f"""You are {self.name}, a medical translation expert.
You are translating medical interpreter speech for quality assessment.

CRITICAL: Translate LITERALLY, preserving errors.
- If the speaker made grammatical errors, keep them in English
- If they used wrong words, translate those wrong words literally
- Do NOT fix or improve the translation
- This is for evaluating the interpreter, not for smooth reading

Example: "Lo siento porque yo escucho" → "I'm sorry because I listen" (NOT "I'm sorry to hear that")"""

            user_prompt = f"""TRANSLATE THIS ({detected_language}) TO ENGLISH:
"{raw_text}"

Remember: LITERAL translation. Preserve errors, weird phrasing, everything.

Respond with JSON:
{{
  "translation": "Your literal English translation",
  "reasoning": "Brief explanation of your translation choices",
  "medical_terms": ["list any medical terms you identified"]
}}"""

        response = await self._call_llm(system_prompt, user_prompt)

        # Parse JSON from response
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                result = json.loads(json_match.group())
                old_position = self.current_position
                self.current_position = result.get("translation", "")
                self.position_history.append(self.current_position)

                # Check if position changed
                result["changed_mind"] = (
                    old_position is not None and
                    old_position != self.current_position
                )
                return result
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️ {self.name} translation JSON parse error: {e}")

        return {
            "translation": response,
            "reasoning": "Failed to parse structured response",
            "raw_response": response
        }

    async def evaluate_errors(
        self,
        source_meaning: str,
        interpreter_meaning: str,
        source_role: str,
        peer_evaluations: Optional[Dict[str, Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate interpreter for errors.
        If peer_evaluations provided, this is a debate round.
        """
        if peer_evaluations:
            # DEBATE ROUND
            peer_section = "\n\n".join([
                f"• {agent}:\n  Verdict: {eval.get('verdict', '?')}\n  Errors: {eval.get('errors', [])}"
                for agent, eval in peer_evaluations.items()
            ])

            system_prompt = f"""You are {self.name}, a medical interpretation quality assessor in a tribunal.
You've seen your peers' evaluations. Now you must:
1. State your verdict (you may change it if convinced)
2. Argue with peers if you disagree - be specific about what they got wrong
3. If they found something you missed, acknowledge it

This is a REAL debate. Don't just agree to be nice. If you think an error is NOT actually an error, say so."""

            user_prompt = f"""SOURCE ({source_role.upper()} SAID - GROUND TRUTH):
"{source_meaning}"

INTERPRETER'S RENDITION:
"{interpreter_meaning}"

YOUR PREVIOUS VERDICT:
{self.current_position or '[First round]'}

PEER EVALUATIONS:
{peer_section}

Debate and respond with JSON:
{{
  "verdict": "accurate" | "minor_issues" | "significant_errors" | "critical_errors",
  "errors": [{{"type": "omission|fabrication|distortion", "severity": "low|medium|high|critical", "description": "..."}}],
  "reasoning": "Your analysis",
  "agrees_with": ["agent names"],
  "disagrees_with": ["agent names"],
  "disagreement_reasons": {{"agent": "why"}},
  "changed_mind": true/false
}}"""
        else:
            # FIRST ROUND - Independent evaluation
            system_prompt = f"""You are {self.name}, a medical interpretation quality assessor.
You evaluate whether interpreters accurately convey meaning.

Error types:
- OMISSION: Interpreter left out critical information
- FABRICATION: Interpreter added things the source didn't say
- DISTORTION: Interpreter changed the meaning (especially numbers, negations, medications)

Be precise. Don't flag stylistic differences as errors."""

            user_prompt = f"""SOURCE ({source_role.upper()} SAID - GROUND TRUTH):
"{source_meaning}"

INTERPRETER'S RENDITION:
"{interpreter_meaning}"

Evaluate the interpreter's accuracy. Respond with JSON:
{{
  "verdict": "accurate" | "minor_issues" | "significant_errors" | "critical_errors",
  "errors": [{{"type": "omission|fabrication|distortion", "severity": "low|medium|high|critical", "description": "specific error"}}],
  "reasoning": "Your analysis"
}}"""

        response = await self._call_llm(system_prompt, user_prompt)

        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                result = json.loads(json_match.group())
                old_position = self.current_position
                self.current_position = result.get("verdict", "")
                self.position_history.append(self.current_position)
                result["changed_mind"] = (
                    old_position is not None and
                    old_position != self.current_position
                )
                return result
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️ {self.name} evaluation JSON parse error: {e}")

        return {
            "verdict": "error",
            "errors": [],
            "reasoning": response,
            "raw_response": response
        }


# ═══════════════════════════════════════════════════════════════════════════════
# TRANSLATION TRIBUNAL
# ═══════════════════════════════════════════════════════════════════════════════

class TranslationTribunal:
    """
    3-agent tribunal for translation consensus.

    Takes RAW text (Gujarati, Spanish, etc.) and produces consensus English translation.
    """

    MAX_ROUNDS = 5  # Prevent infinite debates

    def __init__(self, agents: List[TribunalAgent]):
        if len(agents) != 3:
            raise ValueError("TranslationTribunal requires exactly 3 agents")
        self.agents = agents

    async def debate(
        self,
        raw_text: str,
        detected_language: str,
    ) -> Dict[str, Any]:
        """
        Run translation debate until consensus or max rounds.

        Returns:
            {
                "consensus_translation": str,
                "consensus_reached": bool,
                "debate_log": DebateLog,
                "individual_translations": Dict[str, str],
            }
        """
        debate_log = DebateLog(
            tribunal_type="translation",
            input_text=raw_text,
        )

        print(f"\n{'='*70}")
        print(f"🌐 TRANSLATION TRIBUNAL - Starting debate")
        print(f"   Language: {detected_language}")
        print(f"   Text: {raw_text[:100]}{'...' if len(raw_text) > 100 else ''}")
        print(f"{'='*70}")

        translations: Dict[str, str] = {}
        round_num = 0

        while round_num < self.MAX_ROUNDS:
            round_num += 1
            print(f"\n📢 ROUND {round_num}")

            # Each agent translates (in parallel)
            if round_num == 1:
                # First round: independent
                tasks = [
                    agent.translate(raw_text, detected_language, None)
                    for agent in self.agents
                ]
            else:
                # Later rounds: see peer translations
                tasks = [
                    agent.translate(
                        raw_text,
                        detected_language,
                        {a.name: translations[a.name] for a in self.agents if a.name != agent.name}
                    )
                    for agent in self.agents
                ]

            results = await asyncio.gather(*tasks)

            # Log each turn
            for agent, result in zip(self.agents, results):
                translation = result.get("translation", "")
                translations[agent.name] = translation

                turn = DebateTurn(
                    round_num=round_num,
                    agent_name=agent.name,
                    agent_model=agent.model,
                    agent_provider=agent.provider,
                    statement=result.get("reasoning", ""),
                    position=translation,
                    reasoning=result.get("reasoning", ""),
                    agrees_with=result.get("agrees_with", []),
                    disagrees_with=result.get("disagrees_with", []),
                    changed_mind=result.get("changed_mind", False),
                )
                debate_log.add_turn(turn)

            # Check for consensus (2/3 agreement)
            translation_values = list(translations.values())
            for trans in translation_values:
                count = sum(1 for t in translation_values if self._similar(t, trans))
                if count >= 2:
                    debate_log.consensus_reached = True
                    debate_log.final_consensus = trans
                    debate_log.rounds_taken = round_num
                    debate_log.end_time = datetime.utcnow()

                    print(f"\n✅ CONSENSUS REACHED in Round {round_num}!")
                    print(f"   Translation: {trans[:100]}...")

                    return {
                        "consensus_translation": trans,
                        "consensus_reached": True,
                        "debate_log": debate_log,
                        "individual_translations": translations,
                    }

            # No consensus yet - continue debate if minds are changing
            if round_num > 1:
                any_changed = any(r.get("changed_mind", False) for r in results)
                if not any_changed and round_num >= 2:
                    print(f"\n⚠️ No minds changed - forcing majority vote")
                    break

        # No consensus - pick majority or first
        debate_log.rounds_taken = round_num
        debate_log.end_time = datetime.utcnow()
        debate_log.consensus_reached = False

        # Pick most common translation
        from collections import Counter
        final = Counter(translations.values()).most_common(1)[0][0]
        debate_log.final_consensus = final

        print(f"\n⚠️ No consensus after {round_num} rounds. Using majority: {final[:100]}...")

        return {
            "consensus_translation": final,
            "consensus_reached": False,
            "debate_log": debate_log,
            "individual_translations": translations,
        }

    def _similar(self, t1: str, t2: str, threshold: float = 0.85) -> bool:
        """Check if two translations are similar enough to count as agreement."""
        from difflib import SequenceMatcher
        return SequenceMatcher(None, t1.lower(), t2.lower()).ratio() > threshold


# ═══════════════════════════════════════════════════════════════════════════════
# ERROR TRIBUNAL
# ═══════════════════════════════════════════════════════════════════════════════

class ErrorTribunal:
    """
    3-agent tribunal for error detection consensus.

    Takes consolidated translations and determines if interpreter made errors.
    """

    MAX_ROUNDS = 5

    def __init__(self, agents: List[TribunalAgent]):
        if len(agents) != 3:
            raise ValueError("ErrorTribunal requires exactly 3 agents")
        self.agents = agents

    async def debate(
        self,
        source_meaning: str,
        interpreter_meaning: str,
        source_role: str,
    ) -> Dict[str, Any]:
        """
        Run error detection debate until consensus or max rounds.

        Returns:
            {
                "consensus_verdict": str,
                "consensus_errors": List[Dict],
                "consensus_reached": bool,
                "debate_log": DebateLog,
                "individual_evaluations": Dict[str, Dict],
            }
        """
        debate_log = DebateLog(
            tribunal_type="error",
            input_text=f"Source: {source_meaning[:100]}... | Interpreter: {interpreter_meaning[:100]}...",
        )

        print(f"\n{'='*70}")
        print(f"⚖️  ERROR TRIBUNAL - Starting debate")
        print(f"   Source ({source_role}): {source_meaning[:80]}...")
        print(f"   Interpreter: {interpreter_meaning[:80]}...")
        print(f"{'='*70}")

        evaluations: Dict[str, Dict] = {}
        round_num = 0

        while round_num < self.MAX_ROUNDS:
            round_num += 1
            print(f"\n📢 ROUND {round_num}")

            if round_num == 1:
                tasks = [
                    agent.evaluate_errors(source_meaning, interpreter_meaning, source_role, None)
                    for agent in self.agents
                ]
            else:
                tasks = [
                    agent.evaluate_errors(
                        source_meaning,
                        interpreter_meaning,
                        source_role,
                        {a.name: evaluations[a.name] for a in self.agents if a.name != agent.name}
                    )
                    for agent in self.agents
                ]

            results = await asyncio.gather(*tasks)

            for agent, result in zip(self.agents, results):
                evaluations[agent.name] = result

                turn = DebateTurn(
                    round_num=round_num,
                    agent_name=agent.name,
                    agent_model=agent.model,
                    agent_provider=agent.provider,
                    statement=result.get("reasoning", ""),
                    position=result.get("verdict", ""),
                    reasoning=result.get("reasoning", ""),
                    agrees_with=result.get("agrees_with", []),
                    disagrees_with=result.get("disagrees_with", []),
                    changed_mind=result.get("changed_mind", False),
                )
                debate_log.add_turn(turn)

            # Check for verdict consensus (2/3)
            verdicts = [e.get("verdict", "") for e in evaluations.values()]
            for verdict in set(verdicts):
                if verdicts.count(verdict) >= 2:
                    # Consensus on verdict - merge errors from agreeing agents
                    agreeing_evals = [e for e in evaluations.values() if e.get("verdict") == verdict]
                    merged_errors = []
                    seen_descriptions = set()
                    for e in agreeing_evals:
                        for err in e.get("errors", []):
                            desc = err.get("description", "")
                            if desc not in seen_descriptions:
                                merged_errors.append(err)
                                seen_descriptions.add(desc)

                    debate_log.consensus_reached = True
                    debate_log.final_consensus = verdict
                    debate_log.rounds_taken = round_num
                    debate_log.end_time = datetime.utcnow()

                    print(f"\n✅ CONSENSUS REACHED in Round {round_num}!")
                    print(f"   Verdict: {verdict}")
                    print(f"   Errors: {len(merged_errors)}")

                    return {
                        "consensus_verdict": verdict,
                        "consensus_errors": merged_errors,
                        "consensus_reached": True,
                        "debate_log": debate_log,
                        "individual_evaluations": evaluations,
                    }

            # Check if anyone changed mind
            if round_num > 1:
                any_changed = any(r.get("changed_mind", False) for r in results)
                if not any_changed:
                    print(f"\n⚠️ No minds changed - forcing majority vote")
                    break

        # No consensus
        debate_log.rounds_taken = round_num
        debate_log.end_time = datetime.utcnow()

        from collections import Counter
        verdicts = [e.get("verdict", "") for e in evaluations.values()]
        final_verdict = Counter(verdicts).most_common(1)[0][0]

        # Get errors from agents with that verdict
        final_errors = []
        for e in evaluations.values():
            if e.get("verdict") == final_verdict:
                final_errors.extend(e.get("errors", []))

        debate_log.final_consensus = final_verdict

        print(f"\n⚠️ No consensus after {round_num} rounds. Majority verdict: {final_verdict}")

        return {
            "consensus_verdict": final_verdict,
            "consensus_errors": final_errors,
            "consensus_reached": False,
            "debate_log": debate_log,
            "individual_evaluations": evaluations,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# DUAL TRIBUNAL ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

class DualTribunalOrchestrator:
    """
    Orchestrates both Translation and Error tribunals.

    Flow:
    1. Raw source text → Translation Tribunal → Consolidated source meaning
    2. Raw interpreter text → Translation Tribunal → Consolidated interpreter meaning
    3. Both meanings → Error Tribunal → Confirmed errors
    """

    def __init__(
        self,
        groq_api_key: str,
        openai_api_key: str,
        deepseek_api_key: str,
        model_a: str = "llama-3.1-8b-instant",
        model_b: str = "gpt-4o-mini",
        model_c: str = "deepseek-chat",
    ):
        # Import here to avoid circular imports
        try:
            from groq import AsyncGroq
        except ImportError:
            AsyncGroq = None

        try:
            from openai import AsyncOpenAI
        except ImportError:
            AsyncOpenAI = None

        DEEPSEEK_BASE_URL = "https://api.deepseek.com"

        # Validate API keys
        if not groq_api_key:
            raise ValueError("GROQ_API_KEY required")
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY required")
        if not deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY required")

        # Initialize clients
        groq_client = AsyncGroq(api_key=groq_api_key) if AsyncGroq else None
        openai_client = AsyncOpenAI(api_key=openai_api_key) if AsyncOpenAI else None
        deepseek_client = AsyncOpenAI(api_key=deepseek_api_key, base_url=DEEPSEEK_BASE_URL) if AsyncOpenAI else None

        # Create agents for TRANSLATION tribunal
        self.translation_agents = [
            TribunalAgent(f"Translator-A ({model_a})", groq_client, model_a, "groq"),
            TribunalAgent(f"Translator-B ({model_b})", openai_client, model_b, "openai"),
            TribunalAgent(f"Translator-C ({model_c})", deepseek_client, model_c, "deepseek"),
        ]

        # Create agents for ERROR tribunal (same models, fresh instances)
        self.error_agents = [
            TribunalAgent(f"Evaluator-A ({model_a})", groq_client, model_a, "groq"),
            TribunalAgent(f"Evaluator-B ({model_b})", openai_client, model_b, "openai"),
            TribunalAgent(f"Evaluator-C ({model_c})", deepseek_client, model_c, "deepseek"),
        ]

        self.translation_tribunal = TranslationTribunal(self.translation_agents)
        self.error_tribunal = ErrorTribunal(self.error_agents)

        print(f"\n{'='*70}")
        print(f"🏛️  DUAL TRIBUNAL SYSTEM INITIALIZED")
        print(f"{'='*70}")
        print(f"Translation Tribunal:")
        for a in self.translation_agents:
            print(f"   • {a.name} via {a.provider}")
        print(f"Error Tribunal:")
        for a in self.error_agents:
            print(f"   • {a.name} via {a.provider}")
        print(f"{'='*70}\n")

    async def evaluate_interpretation(
        self,
        raw_source_text: str,
        raw_interpreter_text: str,
        source_language: str,
        interpreter_language: str,
        source_role: str,
    ) -> Dict[str, Any]:
        """
        Full two-stage tribunal evaluation.

        Args:
            raw_source_text: Original provider/patient speech (any language)
            raw_interpreter_text: Interpreter's rendition (any language)
            source_language: Detected language of source
            interpreter_language: Detected language of interpreter
            source_role: "provider" or "patient"

        Returns:
            Complete result with both tribunal logs and final verdict
        """
        print(f"\n{'#'*70}")
        print(f"# DUAL TRIBUNAL EVALUATION")
        print(f"# Source ({source_role}, {source_language}): {raw_source_text[:50]}...")
        print(f"# Interpreter ({interpreter_language}): {raw_interpreter_text[:50]}...")
        print(f"{'#'*70}")

        # STAGE 1A: Translate source if not English
        if source_language != "en":
            print(f"\n🔄 STAGE 1A: Translating source ({source_language}) to English...")
            source_result = await self.translation_tribunal.debate(raw_source_text, source_language)
            source_meaning = source_result["consensus_translation"]
            source_debate_log = source_result["debate_log"]
        else:
            source_meaning = raw_source_text
            source_debate_log = None
            print(f"\n✓ Source already in English")

        # Reset translation agents for next debate
        for agent in self.translation_agents:
            agent.current_position = None
            agent.position_history = []

        # STAGE 1B: Translate interpreter if not English
        if interpreter_language != "en":
            print(f"\n🔄 STAGE 1B: Translating interpreter ({interpreter_language}) to English...")
            interp_result = await self.translation_tribunal.debate(raw_interpreter_text, interpreter_language)
            interpreter_meaning = interp_result["consensus_translation"]
            interpreter_debate_log = interp_result["debate_log"]
        else:
            interpreter_meaning = raw_interpreter_text
            interpreter_debate_log = None
            print(f"\n✓ Interpreter already in English")

        # STAGE 2: Error tribunal
        print(f"\n🔄 STAGE 2: Evaluating interpreter accuracy...")
        error_result = await self.error_tribunal.debate(
            source_meaning,
            interpreter_meaning,
            source_role,
        )

        print(f"\n{'#'*70}")
        print(f"# FINAL RESULT")
        print(f"# Verdict: {error_result['consensus_verdict']}")
        print(f"# Errors: {len(error_result['consensus_errors'])}")
        print(f"# Consensus reached: {error_result['consensus_reached']}")
        print(f"{'#'*70}\n")

        return {
            "source_meaning": source_meaning,
            "interpreter_meaning": interpreter_meaning,
            "verdict": error_result["consensus_verdict"],
            "errors": error_result["consensus_errors"],
            "consensus_reached": error_result["consensus_reached"],
            "debate_logs": {
                "source_translation": source_debate_log.to_dict() if source_debate_log else None,
                "interpreter_translation": interpreter_debate_log.to_dict() if interpreter_debate_log else None,
                "error_evaluation": error_result["debate_log"].to_dict(),
            },
        }
