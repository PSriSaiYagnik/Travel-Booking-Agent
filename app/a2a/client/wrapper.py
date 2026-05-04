import httpx
from app.a2a.schemas import (
    A2ATaskRequest,
    A2ATaskResponse,
    JsonRpcRequest,
    JsonRpcResponse,
)
from app.core.checkpointer import db_conn


def _get_agent_url(task_type: str) -> str:
    """
    Look up the active agent base_url from the agent_registry table.

    This is the core of the service-registry pattern — the Orchestrator
    never hardcodes agent URLs. If a URL changes, update the DB row.

    Raises:
        ValueError: If no active agent is registered for the given task_type.
    """
    cursor = db_conn.execute(
        "SELECT base_url FROM agent_registry WHERE task_type = ? AND is_active = 1",
        (task_type,),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError(
            f"No active agent registered for task_type: '{task_type}'. "
            "Check the agent_registry table."
        )
    return row["base_url"]


async def send_task(task_request: A2ATaskRequest) -> A2ATaskResponse:
    """
    Send an A2A task to the appropriate sub-agent via JSON-RPC over HTTP.

    Flow:
        1. Look up the agent URL from agent_registry (DB).
        2. Wrap the A2ATaskRequest in a JSON-RPC 2.0 envelope.
        3. POST to {base_url}/rpc.
        4. Unwrap the JSON-RPC response and return the A2ATaskResponse.

    Args:
        task_request: The structured A2A task to send.

    Returns:
        A2ATaskResponse from the sub-agent.

    Raises:
        RuntimeError: If the sub-agent returns a JSON-RPC error block.
        httpx.HTTPStatusError: If the HTTP request itself fails.
    """
    base_url = _get_agent_url(task_request.task_type)

    rpc_request = JsonRpcRequest(params=task_request)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{base_url}/rpc",
            json=rpc_request.model_dump(),
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

    rpc_response = JsonRpcResponse(**response.json())

    if rpc_response.error:
        raise RuntimeError(
            f"Sub-agent returned an error "
            f"[code {rpc_response.error.code}]: {rpc_response.error.message}"
        )

    return rpc_response.result
