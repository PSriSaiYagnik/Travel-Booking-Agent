import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# =============================================================================
# A2A Inner Schemas  (Assignment-required fields — must not be removed)
# =============================================================================

class TaskMetadata(BaseModel):
    """Metadata attached by the Orchestrator to every outgoing task."""
    requested_by: str = "orchestrator"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ResponseMetadata(BaseModel):
    """Metadata attached by the sub-agent to every response."""
    agent_id: str                           # e.g. 'flight-agent' | 'hotel-agent'
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AgentCard(BaseModel):
    """
    Standardized 'digital business card' for an AI Agent.
    Served via the /.well-known/agent.json endpoint for auto-discovery.
    """
    id: str
    name: str
    description: str
    endpoint: str
    supported_tasks: list[str]
    required_params: list[str]


class A2ATaskRequest(BaseModel):
    """
    Structured task payload sent from Orchestrator → Sub-Agent.
    All fields below are mandatory per the assignment specification.
    """
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_type: Literal["flight_search", "hotel_search"]
    session_id: str
    parameters: dict[str, Any]             # Current known parameters (if any)
    raw_messages: list[dict[str, Any]] = Field(default_factory=list) # Full conversation
    metadata: TaskMetadata = Field(default_factory=TaskMetadata)


class A2ATaskResponse(BaseModel):
    """
    Structured response payload sent from Sub-Agent → Orchestrator.
    All fields below are mandatory per the assignment specification.
    """
    task_id: str
    status: Literal["success", "partial", "failed", "needs_clarification"]
    results: list[Any] = Field(default_factory=list)
    extracted_params: dict[str, Any] = Field(default_factory=dict) # What the agent extracted
    agent_message: Optional[str] = None                            # Ready-to-display markdown
    clarification_needed: Optional[str] = None
    fallback_note: Optional[str] = None
    error: Optional[str] = None
    metadata: ResponseMetadata


# =============================================================================
# JSON-RPC 2.0 Envelope Schemas  (wraps the A2A schemas above)
# =============================================================================

class JsonRpcRequest(BaseModel):
    """
    JSON-RPC 2.0 request envelope.
    The A2ATaskRequest lives inside 'params'.
    """
    jsonrpc: Literal["2.0"] = "2.0"
    method: str = "a2a.execute_task"
    params: A2ATaskRequest
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class JsonRpcError(BaseModel):
    """Standard JSON-RPC 2.0 error object."""
    code: int
    message: str
    data: Optional[Any] = None


class JsonRpcResponse(BaseModel):
    """
    JSON-RPC 2.0 response envelope.
    On success → 'result' contains the A2ATaskResponse.
    On failure → 'error' contains a JsonRpcError.
    """
    jsonrpc: Literal["2.0"] = "2.0"
    result: Optional[A2ATaskResponse] = None
    error: Optional[JsonRpcError] = None
    id: str
