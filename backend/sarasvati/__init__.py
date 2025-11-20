"""
SARASVATI - Medical Interpreter Monitoring System
=================================================
The Trisul Protocol: Real-time clinical error detection using adversarial agents.

Main Components:
- State Management (core.state)
- Temporal Alignment (core.alignment)
- Adversarial Agents (core.agent)
- LangGraph Processing Loop (core.graph)
- Redis Buffer (utils.redis_buffer)
"""

__version__ = "0.1.0"
__author__ = "SARASVATI Team"

from .core.state import (
    SarasvatiState,
    TranscriptSegment,
    MedicalEntity,
    ClinicalError,
    ErrorSeverity,
    StreamRole,
    GraphConfig,
    create_initial_state,
)

from .core.graph import (
    SarasvatiEngine,
    create_engine,
)

from .core.alignment import (
    AlignmentEngine,
    create_alignment_engine,
)

from .core.agent import (
    ClinicalDebateOrchestrator,
    NodeAExtractor,
    NodeBMonitor,
    NodeCArbiter,
)

__all__ = [
    # State
    "SarasvatiState",
    "TranscriptSegment",
    "MedicalEntity",
    "ClinicalError",
    "ErrorSeverity",
    "StreamRole",
    "GraphConfig",
    "create_initial_state",
    # Engine
    "SarasvatiEngine",
    "create_engine",
    # Alignment
    "AlignmentEngine",
    "create_alignment_engine",
    # Agents
    "ClinicalDebateOrchestrator",
    "NodeAExtractor",
    "NodeBMonitor",
    "NodeCArbiter",
]
