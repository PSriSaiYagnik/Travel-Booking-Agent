from datetime import datetime, timezone

from fastapi import FastAPI

from app.a2a.schemas import A2ATaskRequest, A2ATaskResponse, ResponseMetadata, AgentCard
from app.a2a.server.executor import register_handler
from app.a2a.server.router import router as rpc_router
import os
import json
from pathlib import Path
from app.core.checkpointer import db_conn
from app.agents.flight.graph import flight_graph

# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="Flight Booking Agent",
    description="A2A sub-agent that handles flight searches. Communicates via JSON-RPC 2.0.",
    version="1.0.0",
)

# Mount the A2A JSON-RPC endpoint at /rpc
app.include_router(rpc_router)

@app.get("/.well-known/agent.json", response_model=AgentCard)
def get_agent_card():
    card_path = Path(__file__).parent / "agent.json"
    with open(card_path, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# A2A Handler — registered with executor on startup
# =============================================================================

async def handle_flight_task(task_request: A2ATaskRequest) -> A2ATaskResponse:
    """
    Invokes the Flight LangGraph with the incoming A2A task parameters.
    Converts the graph's final state into a structured A2ATaskResponse.
    """
    # Build initial state from the A2A task request
    initial_state = {
        "task_id":           task_request.task_id,
        "parameters":        task_request.parameters,
        "raw_messages":      task_request.raw_messages,
        "agent_message":     None,
        "validation_errors": [],
        "raw_api_data":      [],
        "formatted_results": [],
        "fallback_notes":    [],
        "trip_type":         task_request.parameters.get("trip_type", "one_way"),
        "status":            "",
    }

    # Run the LangGraph (asynchronous invoke — flight graph now uses async nodes)
    final_state = await flight_graph.ainvoke(initial_state)

    # Build clarification message if validation failed
    clarification = None
    if final_state["status"] == "needs_clarification" and final_state["validation_errors"]:
        clarification = "Please provide: " + ", ".join(final_state["validation_errors"])

    return A2ATaskResponse(
        task_id=task_request.task_id,
        status=final_state["status"],
        results=final_state.get("formatted_results", []),
        extracted_params=final_state.get("parameters", {}),
        agent_message=final_state.get("agent_message"),
        clarification_needed=clarification,
        fallback_note=final_state.get("fallback_notes", [""])[0] if final_state.get("fallback_notes") else None,
        error="No flights found for your request." if final_state["status"] == "failed" else None,
        metadata=ResponseMetadata(
            agent_id="flight-agent",
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )


# =============================================================================
# Background Tasks & Startup
# =============================================================================

import asyncio
from app.common.registry import register_agent, heartbeat

async def _heartbeat_loop(agent_id: str):
    """Background task: refresh last_seen in the registry every 30 s."""
    while True:
        await asyncio.sleep(30)
        try:
            heartbeat(agent_id)
        except Exception as exc:
            print(f"[FLIGHT-AGENT] Heartbeat error: {exc}")


@app.on_event("startup")
async def startup():
    """
    1. Register A2A task handler with the executor.
    2. Self-register in the shared SQLite DB (no orchestrator dependency).
    3. Start background heartbeat loop.
    """
    # -- A2A executor handler
    register_handler("flight_search", handle_flight_task)

    # -- Build the full RPC endpoint URL
    port     = os.getenv("PORT", "8001")
    endpoint = f"http://localhost:{port}/rpc"

    # -- Read identity from agent.json
    card_dict = get_agent_card()

    # -- Write to DB directly (orchestrator-independent)
    register_agent(
        agent_id = card_dict["id"],
        name     = card_dict["name"],
        endpoint = endpoint,
        skills   = card_dict["supported_tasks"],
    )

    # -- Keep liveness record fresh
    asyncio.create_task(_heartbeat_loop(card_dict["id"]))


# =============================================================================
# Run with: uvicorn app.agents.flight.main:app --port 8001
# =============================================================================
