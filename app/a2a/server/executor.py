from typing import Callable

from app.a2a.schemas import A2ATaskRequest, A2ATaskResponse, ResponseMetadata
from datetime import datetime, timezone

# =============================================================================
# Task Handler Registry
# =============================================================================
# Maps task_type → the async handler function that processes it.
# Each sub-agent's main.py calls register_handler() on startup to plug in
# its LangGraph. The executor never imports agent graphs directly —
# this keeps the A2A layer fully decoupled from agent implementations.
# =============================================================================

_TASK_REGISTRY: dict[str, Callable] = {}


def register_handler(task_type: str, handler: Callable) -> None:
    """
    Register an async handler function for a given task_type.

    Called by each agent's main.py at startup:
        from app.a2a.server.executor import register_handler
        register_handler("flight_search", handle_flight_task)

    Args:
        task_type: The task identifier (e.g. 'flight_search', 'hotel_search').
        handler:   An async function (task: A2ATaskRequest) -> A2ATaskResponse.
    """
    _TASK_REGISTRY[task_type] = handler


async def execute_task(task_request: A2ATaskRequest) -> A2ATaskResponse:
    """
    Route an incoming A2A task to the correct registered handler.

    If no handler is found for the given task_type, returns a 'failed'
    A2ATaskResponse instead of raising an exception — the error is
    safely propagated back to the Orchestrator via JSON-RPC.
    """
    handler = _TASK_REGISTRY.get(task_request.task_type)

    if not handler:
        return A2ATaskResponse(
            task_id=task_request.task_id,
            status="failed",
            error=f"No handler registered for task_type: '{task_request.task_type}'",
            metadata=ResponseMetadata(
                agent_id="executor",
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
        )

    return await handler(task_request)
