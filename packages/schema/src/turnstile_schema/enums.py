from enum import Enum

class EndReason(str, Enum):
    caller_hangup = "caller_hangup"
    agent_hangup = "agent_hangup"
    escalated = "escalated"
    timeout = "timeout"
    error = "error"

class SpeakerFirst(str, Enum):
    caller = "caller"
    agent = "agent"

class PruningStrategy(str, Enum):
    none = "none"
    window = "window"
    summarize = "summarize"
    semantic = "semantic"

class DecisionKind(str, Enum):
    route = "route"
    slot_fill = "slot_fill"
    tool_select = "tool_select"
    compose = "compose"
    escalate_check = "escalate_check"

class ToolKind(str, Enum):
    retrieval = "retrieval"
    mutation = "mutation"
    lookup = "lookup"
    handoff = "handoff"

class Direction(str, Enum):
    inbound = "inbound"
    outbound = "outbound"

class VerdictLabel(str, Enum):
    RESOLVED = "RESOLVED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    ESCALATED = "ESCALATED"
    ABANDONED = "ABANDONED"
    MISROUTED = "MISROUTED"
    FALSE_RESOLVE = "FALSE_RESOLVE"

class ToolStatus(str, Enum):
    ok = "ok"
    error = "error"

class Effect(str, Enum):
    committed = "committed"
    pending = "pending"
    rejected = "rejected"
    none = "none"
    unknown = "unknown"
