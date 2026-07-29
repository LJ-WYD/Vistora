"""Vistora agent boundaries.

`EditingAgent` is the constrained production executor. `OperatorAgent` remains
an opt-in compatibility prototype and is intentionally not re-exported here.
"""

from .editing_agent import (
    EDITING_AGENT_VERSION,
    EditingAgent,
    EditingAgentExecutionReport,
    EditingAgentExecutionRequest,
    EditingAgentRecoveryReport,
    EditingAgentStepReport,
)

__all__ = [
    "EDITING_AGENT_VERSION",
    "EditingAgent",
    "EditingAgentExecutionReport",
    "EditingAgentExecutionRequest",
    "EditingAgentRecoveryReport",
    "EditingAgentStepReport",
]
