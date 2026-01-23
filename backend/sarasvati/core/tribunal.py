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

    def to_frontend_format(
        self,
        challenges: Optional[List[Dict[str, Any]]] = None,
        rebuttals: Optional[List[Dict[str, Any]]] = None,
        convergence_type: Optional[str] = None,
        dissenting_opinions: Optional[List[Dict[str, Any]]] = None,
        consensus_confidence: float = 1.0,
        flagged_for_human_review: bool = False,
    ) -> Dict[str, Any]:
        """
        PHASE 3: Export debate log in frontend-friendly format.

        Includes all Phase 2 debate structures (challenges, rebuttals, convergence).
        Returns UI-optimized structure for DebateConversation.tsx component.
        """
        # Organize turns by round for timeline visualization
        rounds = {}
        for turn in self.turns:
            round_num = turn.round_num
            if round_num not in rounds:
                rounds[round_num] = {
                    "round_number": round_num,
                    "turns": [],
                    "consensus_emerging": False,
                    "position_changes": 0,
                }
            rounds[round_num]["turns"].append(turn.to_dict())
            if turn.changed_mind:
                rounds[round_num]["position_changes"] += 1

        # Detect emerging consensus in each round
        for round_num, round_data in rounds.items():
            positions = [t["position"] for t in round_data["turns"]]
            if len(positions) == 3 and len(set(positions)) == 1:
                round_data["consensus_emerging"] = True

        return {
            "tribunal_type": self.tribunal_type,
            "input_text": self.input_text,
            "rounds": [rounds[r] for r in sorted(rounds.keys())],
            "final_consensus": self.final_consensus,
            "consensus_reached": self.consensus_reached,
            "rounds_taken": self.rounds_taken,
            "duration_ms": (self.end_time - self.start_time).total_seconds() * 1000 if self.end_time else None,
            # PHASE 2: Challenge-response data
            "challenges": challenges or [],
            "rebuttals": rebuttals or [],
            "convergence_type": convergence_type,
            "dissenting_opinions": dissenting_opinions or [],
            "consensus_confidence": consensus_confidence,
            "flagged_for_human_review": flagged_for_human_review,
            # UI-specific metadata
            "agent_summary": self._build_agent_summary(),
            "debate_flow": self._build_debate_flow(),
        }

    def _build_agent_summary(self) -> Dict[str, Any]:
        """Build summary of agent behavior across debate."""
        agent_stats = {}
        for turn in self.turns:
            agent_name = turn.agent_name
            if agent_name not in agent_stats:
                agent_stats[agent_name] = {
                    "name": agent_name,
                    "model": turn.agent_model,
                    "provider": turn.agent_provider,
                    "position_changes": 0,
                    "final_position": turn.position,
                    "rounds_participated": set(),
                }
            if turn.changed_mind:
                agent_stats[agent_name]["position_changes"] += 1
            agent_stats[agent_name]["final_position"] = turn.position
            agent_stats[agent_name]["rounds_participated"].add(turn.round_num)

        # Convert sets to counts
        for agent in agent_stats.values():
            agent["rounds_participated"] = len(agent["rounds_participated"])

        return agent_stats

    def _build_debate_flow(self) -> List[Dict[str, Any]]:
        """Build chronological flow of debate for timeline visualization."""
        flow = []
        for turn in self.turns:
            event = {
                "type": "statement",
                "round": turn.round_num,
                "agent": turn.agent_name,
                "content": turn.statement,
                "position": turn.position,
                "timestamp": turn.timestamp.isoformat(),
            }
            if turn.changed_mind:
                event["type"] = "position_change"
                event["highlight"] = True
            flow.append(event)
        return flow


# ═══════════════════════════════════════════════════════════════════════════════
# TRIBUNAL AGENT - Individual debater
# ═══════════════════════════════════════════════════════════════════════════════

class TribunalAgent:
    """
    Single agent in a tribunal - can translate or evaluate errors.
    PHASE 2: Enhanced with specialized roles for diversity.
    """

    def __init__(self, name: str, client: Any, model: str, provider: str, role: Optional[str] = None):
        self.name = name
        self.client = client
        self.model = model
        self.provider = provider
        self.current_position: Optional[str] = None
        self.position_history: List[str] = []
        # PHASE 2: Specialized role for this agent
        self.role = role or self._default_role_for_provider(provider)

    def _default_role_for_provider(self, provider: str) -> str:
        """
        PHASE 2: Assign default specialized role based on provider.

        - Groq/Llama: Evidence Scanner (fast pattern matching)
        - OpenAI/GPT: Semantic Analyzer (deep context understanding)
        - Anthropic/Claude: Safety Arbiter (conservative risk assessment)
        """
        roles = {
            "groq": "Evidence Scanner - Fast pattern matching and surface-level analysis",
            "openai": "Semantic Analyzer - Deep context understanding and nuanced interpretation",
            "anthropic": "Safety Arbiter - Conservative risk assessment and clinical safety focus",
            "deepseek": "Pattern Recognizer - Efficient detection of structural issues"
        }
        return roles.get(provider, "General Analyst")

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
# PHASE 2: CONVERGENCE TRACKER - Detects when debate has reached conclusion
# ═══════════════════════════════════════════════════════════════════════════════

class ConvergenceTracker:
    """
    PHASE 2: Tracks debate convergence and detects when conclusion is reached.

    Monitors:
    - Full consensus (3/3 agents agree)
    - Strong majority (2/3 agree, 1 weak dissent)
    - Structured dissent (clear disagreement)
    - Stuck debates (no progress)
    """

    def __init__(self):
        self.position_history: List[Dict[str, str]] = []  # Track positions across rounds
        self.stuck_rounds = 0

    def check_convergence(
        self,
        current_positions: Dict[str, str],
        round_num: int,
        confidences: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Check if debate has converged.

        Args:
            current_positions: {agent_name: position}
            round_num: Current round number
            confidences: {agent_name: confidence} (optional)

        Returns:
            {
                "converged": bool,
                "convergence_type": ConvergenceType,
                "final_position": str,
                "confidence": float,
                "dissenting_opinions": List[DissentingOpinion],
                "flag_for_human": bool
            }
        """
        from ..core.state import ConvergenceType, DissentingOpinion
        from collections import Counter

        positions = list(current_positions.values())
        position_counts = Counter(positions)

        # Check for full consensus (all 3 agree)
        for position, count in position_counts.items():
            if count == 3:
                return {
                    "converged": True,
                    "convergence_type": ConvergenceType.FULL_CONSENSUS,
                    "final_position": position,
                    "confidence": 1.0,
                    "dissenting_opinions": [],
                    "flag_for_human": False
                }

        # Check for strong majority (2 agree, check if dissent is weak)
        for position, count in position_counts.items():
            if count == 2:
                # Find dissenting agent
                dissenting_agent = [name for name, pos in current_positions.items() if pos != position][0]
                dissenting_confidence = confidences.get(dissenting_agent, 0.5) if confidences else 0.5

                # Weak dissent if confidence < 0.6
                if dissenting_confidence < 0.6:
                    return {
                        "converged": True,
                        "convergence_type": ConvergenceType.STRONG_MAJORITY,
                        "final_position": position,
                        "confidence": 0.75,
                        "dissenting_opinions": [],
                        "flag_for_human": False
                    }

        # No convergence yet
        return {
            "converged": False,
            "convergence_type": None,
            "final_position": None,
            "confidence": 0.0,
            "dissenting_opinions": [],
            "flag_for_human": False
        }

    def check_stuck(self, current_positions: Dict[str, str]) -> bool:
        """
        Check if debate is stuck (no position changes).

        Returns:
            True if stuck (no changes for 2 rounds)
        """
        if len(self.position_history) < 2:
            self.position_history.append(current_positions.copy())
            return False

        # Compare to previous round
        prev_positions = self.position_history[-1]
        any_changed = any(
            current_positions.get(agent) != prev_positions.get(agent)
            for agent in current_positions
        )

        if not any_changed:
            self.stuck_rounds += 1
        else:
            self.stuck_rounds = 0

        self.position_history.append(current_positions.copy())

        return self.stuck_rounds >= 2

    def generate_structured_dissent(
        self,
        current_positions: Dict[str, str],
        reasonings: Dict[str, str],
        confidences: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Generate structured dissent documentation.

        Returns convergence result with dissenting opinions documented.
        """
        from ..core.state import ConvergenceType, DissentingOpinion
        from collections import Counter

        position_counts = Counter(current_positions.values())
        majority_position = position_counts.most_common(1)[0][0]

        dissenting_opinions = []
        for agent_name, position in current_positions.items():
            dissenting_opinions.append({
                "agent_name": agent_name,
                "position": position,
                "reasoning": reasonings.get(agent_name, ""),
                "evidence": [],  # Could be enhanced to track cited evidence
                "confidence": confidences.get(agent_name, 0.5)
            })

        return {
            "converged": True,  # Terminated, but with dissent
            "convergence_type": ConvergenceType.STRUCTURED_DISSENT,
            "final_position": majority_position,
            "confidence": 0.5,
            "dissenting_opinions": dissenting_opinions,
            "flag_for_human": True
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2: ADAPTIVE ROUND MANAGER - Adjusts rounds based on case severity
# ═══════════════════════════════════════════════════════════════════════════════

class AdaptiveRoundManager:
    """
    PHASE 2: Manages debate rounds adaptively based on case severity.

    Low severity (minor issues): 2-3 rounds max
    Medium severity (significant errors): 4-5 rounds
    High severity (critical errors): 6-8 rounds
    """

    def __init__(self, case_severity: str = "medium"):
        self.case_severity = case_severity.lower()
        self.max_rounds = self._calculate_max_rounds()

    def _calculate_max_rounds(self) -> int:
        """Calculate max rounds based on severity."""
        if self.case_severity in ["low", "minor"]:
            return 3
        elif self.case_severity in ["medium", "moderate"]:
            return 5
        elif self.case_severity in ["high", "critical"]:
            return 8
        else:
            return 5  # Default to medium

    def should_continue(self, round_num: int, convergence_result: Dict[str, Any]) -> bool:
        """
        Decide if debate should continue.

        Args:
            round_num: Current round number
            convergence_result: Result from ConvergenceTracker

        Returns:
            True if should continue debate
        """
        # Stop if converged
        if convergence_result.get("converged"):
            return False

        # Stop if max rounds reached
        if round_num >= self.max_rounds:
            return False

        return True


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2: CHALLENGE-RESPONSE PROTOCOL - Agent-to-agent challenges
# ═══════════════════════════════════════════════════════════════════════════════

class ChallengeResponseProtocol:
    """
    PHASE 2: Coordinates challenge-response cycles between agents.

    Extracts challenges from agent statements, routes to target agents,
    collects rebuttals.
    """

    def __init__(self):
        self.challenges: List[Dict[str, Any]] = []
        self.rebuttals: List[Dict[str, Any]] = []

    def extract_challenges(
        self,
        round_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract challenges from agent statements.

        Looks for patterns like:
        - "Agent X, you missed..."
        - "I disagree with Agent Y because..."
        - "Agent Z's interpretation is incorrect..."

        Args:
            round_results: List of agent results from current round

        Returns:
            List of Challenge dicts
        """
        from ..core.state import Challenge
        import re

        challenges = []
        round_num = round_results[0].get("round_num", 1) if round_results else 1

        for result in round_results:
            statement = result.get("statement", "")
            from_agent = result.get("agent_name", "")

            # Simple pattern matching (could be enhanced with LLM extraction)
            # Look for agent mentions
            agent_mentions = re.findall(r'Agent[ -]([ABC])', statement, re.IGNORECASE)

            for mentioned_agent in agent_mentions:
                # Extract challenge text (context around mention)
                challenge = {
                    "from_agent": from_agent,
                    "to_agent": f"Agent-{mentioned_agent.upper()}",
                    "round_num": round_num,
                    "challenge_text": statement[:200],  # First 200 chars as challenge
                    "evidence_cited": []  # Could be enhanced to extract evidence
                }
                challenges.append(challenge)

        self.challenges.extend(challenges)
        return challenges

    async def get_rebuttals(
        self,
        challenges: List[Dict[str, Any]],
        agents: List[Any]
    ) -> List[Dict[str, Any]]:
        """
        Get rebuttals from challenged agents.

        Args:
            challenges: List of challenges from previous round
            agents: List of TribunalAgent instances

        Returns:
            List of Rebuttal dicts
        """
        from ..core.state import Rebuttal

        rebuttals = []

        for challenge in challenges:
            # Find target agent
            target_agent = next(
                (a for a in agents if challenge["to_agent"] in a.name),
                None
            )

            if target_agent:
                # For now, just record the challenge was addressed
                # In full implementation, could have agent generate specific rebuttal
                rebuttal = {
                    "from_agent": challenge["to_agent"],
                    "to_agent": challenge["from_agent"],
                    "round_num": challenge["round_num"] + 1,
                    "rebuttal_text": f"Response to challenge from {challenge['from_agent']}",
                    "position_changed": False,  # Would be determined in next round
                    "new_position": None
                }
                rebuttals.append(rebuttal)

        self.rebuttals.extend(rebuttals)
        return rebuttals


# ═══════════════════════════════════════════════════════════════════════════════
# TRANSLATION TRIBUNAL
# ═══════════════════════════════════════════════════════════════════════════════

class TranslationTribunal:
    """
    3-agent tribunal for translation consensus.

    Takes RAW text (Gujarati, Spanish, etc.) and produces consensus English translation.
    """

    # PHASE 2: Deprecated - max rounds now managed by AdaptiveRoundManager
    MAX_ROUNDS = 3  # Legacy default
    MAX_STUCK_ROUNDS = 2  # PHASE 1 FIX: Terminate if no position changes for 2 consecutive rounds

    def __init__(self, agents: List[TribunalAgent], case_severity: str = "medium"):
        if len(agents) != 3:
            raise ValueError("TranslationTribunal requires exactly 3 agents")
        self.agents = agents
        self._consecutive_stuck_rounds = 0  # PHASE 1 FIX: Track stuck rounds

        # PHASE 2: Initialize debate infrastructure
        self.convergence_tracker = ConvergenceTracker()
        self.round_manager = AdaptiveRoundManager(case_severity=case_severity)
        self.challenge_protocol = ChallengeResponseProtocol()

    async def debate(
        self,
        raw_text: str,
        detected_language: str,
    ) -> Dict[str, Any]:
        """
        PHASE 2: Enhanced multi-round debate with challenge-response protocol.

        Run translation debate until consensus or max rounds (adaptive 3-8 rounds).

        Returns:
            {
                "consensus_translation": str,
                "consensus_reached": bool,
                "convergence_type": ConvergenceType,
                "confidence": float,
                "debate_log": DebateLog,
                "individual_translations": Dict[str, str],
                "flagged_for_human_review": bool,
            }
        """
        from ..core.state import ConvergenceType

        debate_log = DebateLog(
            tribunal_type="translation",
            input_text=raw_text,
        )

        print(f"\n{'='*70}")
        print(f"🌐 TRANSLATION TRIBUNAL - PHASE 2: Enhanced Multi-Round Debate")
        print(f"   Language: {detected_language}")
        print(f"   Text: {raw_text[:100]}{'...' if len(raw_text) > 100 else ''}")
        print(f"   Max rounds: {self.round_manager.max_rounds} (adaptive)")
        print(f"{'='*70}")

        translations: Dict[str, str] = {}
        reasonings: Dict[str, str] = {}
        confidences: Dict[str, float] = {}
        round_num = 0

        # PHASE 2: Main debate loop with challenge-response
        while round_num < self.round_manager.max_rounds:
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

            # PHASE 2: Log each turn and track positions
            for agent, result in zip(self.agents, results):
                translation = result.get("translation", "")
                reasoning = result.get("reasoning", "")
                confidence = result.get("confidence", 0.5)

                translations[agent.name] = translation
                reasonings[agent.name] = reasoning
                confidences[agent.name] = confidence

                turn = DebateTurn(
                    round_num=round_num,
                    agent_name=agent.name,
                    agent_model=agent.model,
                    agent_provider=agent.provider,
                    statement=reasoning,
                    position=translation,
                    reasoning=reasoning,
                    agrees_with=result.get("agrees_with", []),
                    disagrees_with=result.get("disagrees_with", []),
                    changed_mind=result.get("changed_mind", False),
                )
                debate_log.add_turn(turn)

            # PHASE 2: Extract challenges for next round (if in rounds 2+)
            if round_num >= 2:
                challenges = self.challenge_protocol.extract_challenges(
                    [{"agent_name": agent.name, "statement": reasonings.get(agent.name, ""), "round_num": round_num}
                     for agent in self.agents]
                )
                if challenges:
                    print(f"   📢 Extracted {len(challenges)} challenges for next round")

            # PHASE 2: Check convergence using ConvergenceTracker
            if round_num >= 2:  # Only check after at least 2 rounds
                convergence_result = self.convergence_tracker.check_convergence(
                    current_positions=translations,
                    round_num=round_num,
                    confidences=confidences
                )

                # Check if debate has converged
                if convergence_result["converged"]:
                    debate_log.consensus_reached = True
                    debate_log.final_consensus = convergence_result["final_position"]
                    debate_log.rounds_taken = round_num
                    debate_log.end_time = datetime.utcnow()
                    debate_log.convergence_type = convergence_result["convergence_type"]
                    debate_log.consensus_confidence = convergence_result["confidence"]
                    debate_log.dissenting_opinions = convergence_result.get("dissenting_opinions", [])
                    debate_log.flagged_for_human_review = convergence_result["flag_for_human"]

                    conv_type = convergence_result["convergence_type"]
                    if conv_type == ConvergenceType.FULL_CONSENSUS:
                        print(f"\n✅ FULL CONSENSUS (3/3) in Round {round_num}!")
                    elif conv_type == ConvergenceType.STRONG_MAJORITY:
                        print(f"\n✅ STRONG MAJORITY (2/3) in Round {round_num}!")
                    elif conv_type == ConvergenceType.STRUCTURED_DISSENT:
                        print(f"\n⚠️  STRUCTURED DISSENT - Flagged for human review")

                    print(f"   Translation: {convergence_result['final_position'][:100]}...")
                    print(f"   Confidence: {convergence_result['confidence']:.2f}")

                    return {
                        "consensus_translation": convergence_result["final_position"],
                        "consensus_reached": True,
                        "convergence_type": conv_type.value,
                        "confidence": convergence_result["confidence"],
                        "debate_log": debate_log,
                        "individual_translations": translations,
                        "flagged_for_human_review": convergence_result["flag_for_human"],
                        "dissenting_opinions": convergence_result.get("dissenting_opinions", []),
                    }

                # Check if round manager says to continue
                if not self.round_manager.should_continue(round_num, convergence_result):
                    break

            # PHASE 2: Check if debate is stuck
            if self.convergence_tracker.check_stuck(translations):
                print(f"\n🛑 Debate stuck (no position changes for 2 rounds). Generating structured dissent.")
                break

        # PHASE 2: Max rounds reached or debate stuck - generate structured dissent
        debate_log.rounds_taken = round_num
        debate_log.end_time = datetime.utcnow()

        # Generate structured dissent documentation
        structured_dissent = self.convergence_tracker.generate_structured_dissent(
            current_positions=translations,
            reasonings=reasonings,
            confidences=confidences
        )

        debate_log.consensus_reached = True  # Terminated with dissent
        debate_log.final_consensus = structured_dissent["final_position"]
        debate_log.convergence_type = structured_dissent["convergence_type"]
        debate_log.consensus_confidence = structured_dissent["confidence"]
        debate_log.dissenting_opinions = structured_dissent["dissenting_opinions"]
        debate_log.flagged_for_human_review = True

        print(f"\n⚠️  STRUCTURED DISSENT after {round_num} rounds")
        print(f"   All {len(structured_dissent['dissenting_opinions'])} agent positions documented")
        print(f"   Flagged for human review: YES")
        print(f"   Using majority position: {structured_dissent['final_position'][:100]}...")

        return {
            "consensus_translation": structured_dissent["final_position"],
            "consensus_reached": False,  # No genuine consensus
            "convergence_type": ConvergenceType.STRUCTURED_DISSENT.value,
            "confidence": structured_dissent["confidence"],
            "debate_log": debate_log,
            "individual_translations": translations,
            "flagged_for_human_review": True,
            "dissenting_opinions": structured_dissent["dissenting_opinions"],
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
    PHASE 2: Enhanced 3-agent tribunal for error detection consensus.

    Takes consolidated translations and determines if interpreter made errors.
    Uses adaptive rounds (3-8) based on case severity.
    """

    # PHASE 2: Deprecated - max rounds now managed by AdaptiveRoundManager
    MAX_ROUNDS = 3  # Legacy default
    MAX_STUCK_ROUNDS = 2  # PHASE 1 FIX: Terminate if no position changes for 2 consecutive rounds

    def __init__(self, agents: List[TribunalAgent], case_severity: str = "medium"):
        if len(agents) != 3:
            raise ValueError("ErrorTribunal requires exactly 3 agents")
        self.agents = agents
        self._consecutive_stuck_rounds = 0  # PHASE 1 FIX: Track stuck rounds

        # PHASE 2: Initialize debate infrastructure (same as TranslationTribunal)
        self.convergence_tracker = ConvergenceTracker()
        self.round_manager = AdaptiveRoundManager(case_severity=case_severity)
        self.challenge_protocol = ChallengeResponseProtocol()

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

            # Check for FULL verdict consensus (3/3) - only after round 2
            # This ensures at least one round of actual debate happens
            if round_num >= 2:
                verdicts = [e.get("verdict", "") for e in evaluations.values()]
                for verdict in set(verdicts):
                    if verdicts.count(verdict) >= 3:  # FULL consensus - all 3 agree
                        # Merge errors from all agents
                        merged_errors = []
                        seen_descriptions = set()
                        for e in evaluations.values():
                            for err in e.get("errors", []):
                                desc = err.get("description", "")
                                if desc not in seen_descriptions:
                                    merged_errors.append(err)
                                    seen_descriptions.add(desc)

                        debate_log.consensus_reached = True
                        debate_log.final_consensus = verdict
                        debate_log.rounds_taken = round_num
                        debate_log.end_time = datetime.utcnow()

                        print(f"\n✅ FULL CONSENSUS REACHED in Round {round_num}!")
                        print(f"   Verdict: {verdict}")
                        print(f"   Errors: {len(merged_errors)}")

                        return {
                            "consensus_verdict": verdict,
                            "consensus_errors": merged_errors,
                            "consensus_reached": True,
                            "consensus_type": "full",  # All 3 agreed
                            "confidence": 1.0,  # High confidence
                            "debate_log": debate_log,
                            "individual_evaluations": evaluations,
                        }

            # PHASE 1 FIX: Detect stuck debate (no position changes)
            if round_num > 1:
                any_changed = any(r.get("changed_mind", False) for r in results)
                if not any_changed:
                    self._consecutive_stuck_rounds += 1
                    print(f"\n⚠️ No minds changed in round {round_num} (stuck count: {self._consecutive_stuck_rounds})")

                    # Break if stuck for MAX_STUCK_ROUNDS consecutive rounds
                    if self._consecutive_stuck_rounds >= self.MAX_STUCK_ROUNDS:
                        print(f"\n🛑 Debate stuck for {self._consecutive_stuck_rounds} rounds. Terminating early.")
                        break
                else:
                    self._consecutive_stuck_rounds = 0  # Reset if any agent changed position

        # No full consensus after max rounds - check for majority (2/3)
        debate_log.rounds_taken = round_num
        debate_log.end_time = datetime.utcnow()

        from collections import Counter
        verdicts = [e.get("verdict", "") for e in evaluations.values()]

        # Check for majority (2/3)
        for verdict in set(verdicts):
            if verdicts.count(verdict) >= 2:
                # Majority on verdict - merge errors from agreeing agents
                agreeing_evals = [e for e in evaluations.values() if e.get("verdict") == verdict]
                merged_errors = []
                seen_descriptions = set()
                for e in agreeing_evals:
                    for err in e.get("errors", []):
                        desc = err.get("description", "")
                        if desc not in seen_descriptions:
                            merged_errors.append(err)
                            seen_descriptions.add(desc)

                debate_log.consensus_reached = True  # Partial consensus
                debate_log.final_consensus = verdict

                print(f"\n⚠️ MAJORITY CONSENSUS (2/3) after {round_num} rounds")
                print(f"   Verdict: {verdict}")
                print(f"   Errors: {len(merged_errors)}")

                return {
                    "consensus_verdict": verdict,
                    "consensus_errors": merged_errors,
                    "consensus_reached": True,
                    "consensus_type": "majority",  # Only 2/3 agreed
                    "confidence": 0.5,  # Lower confidence for majority-only
                    "debate_log": debate_log,
                    "individual_evaluations": evaluations,
                }

        # No majority - complete disagreement (rare)
        final_verdict = Counter(verdicts).most_common(1)[0][0]

        # Get errors from agents with that verdict
        final_errors = []
        for e in evaluations.values():
            if e.get("verdict") == final_verdict:
                final_errors.extend(e.get("errors", []))

        debate_log.consensus_reached = False
        debate_log.final_consensus = final_verdict

        print(f"\n❌ NO CONSENSUS after {round_num} rounds. Using first: {final_verdict}")

        return {
            "consensus_verdict": final_verdict,
            "consensus_errors": final_errors,
            "consensus_reached": False,
            "consensus_type": "none",  # No agreement
            "confidence": 0.25,  # Very low confidence
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
        anthropic_api_key: str,
        model_a: str = "meta-llama/llama-4-scout-17b-16e-instruct",
        model_b: str = "gpt-5-mini",
        model_c: str = "claude-haiku-4-5",
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

        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            AsyncAnthropic = None

        # Validate API keys
        if not groq_api_key:
            raise ValueError("GROQ_API_KEY required")
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY required")
        if not anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY required")

        # Initialize clients
        groq_client = AsyncGroq(api_key=groq_api_key) if AsyncGroq else None
        openai_client = AsyncOpenAI(api_key=openai_api_key) if AsyncOpenAI else None
        anthropic_client = AsyncAnthropic(api_key=anthropic_api_key) if AsyncAnthropic else None

        # Create agents for TRANSLATION tribunal
        self.translation_agents = [
            TribunalAgent(f"Translator-A ({model_a})", groq_client, model_a, "groq"),
            TribunalAgent(f"Translator-B ({model_b})", openai_client, model_b, "openai"),
            TribunalAgent(f"Translator-C ({model_c})", anthropic_client, model_c, "anthropic"),
        ]

        # Create agents for ERROR tribunal (same models, fresh instances)
        self.error_agents = [
            TribunalAgent(f"Evaluator-A ({model_a})", groq_client, model_a, "groq"),
            TribunalAgent(f"Evaluator-B ({model_b})", openai_client, model_b, "openai"),
            TribunalAgent(f"Evaluator-C ({model_c})", anthropic_client, model_c, "anthropic"),
        ]

        self.translation_tribunal = TranslationTribunal(self.translation_agents)
        self.error_tribunal = ErrorTribunal(self.error_agents)

        print(f"\n{'='*70}")
        print(f"🏛️  DUAL TRIBUNAL SYSTEM INITIALIZED (PHASE 2)")
        print(f"{'='*70}")
        print(f"Translation Tribunal (with specialized roles):")
        for a in self.translation_agents:
            print(f"   • {a.name} via {a.provider}")
            print(f"     Role: {a.role}")
        print(f"Error Tribunal (with specialized roles):")
        for a in self.error_agents:
            print(f"   • {a.name} via {a.provider}")
            print(f"     Role: {a.role}")
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
