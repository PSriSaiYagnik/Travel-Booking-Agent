from datetime import datetime, timezone

from fastapi import FastAPI

from app.a2a.schemas import A2ATaskRequest, A2ATaskResponse, ResponseMetadata, AgentCard
from app.a2a.server.executor import register_handler
from app.a2a.server.router import router as rpc_router
import os
import json
from pathlib import Path
from app.core.checkpointer import db_conn
from app.agents.hotel.graph import hotel_graph

# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="Hotel Booking Agent",
    description="A2A sub-agent that handles hotel searches. Communicates via JSON-RPC 2.0.",
    version="1.0.0",
)

app.include_router(rpc_router)

@app.get("/.well-known/agent.json", response_model=AgentCard)
def get_agent_card():
    card_path = Path(__file__).parent / "agent.json"
    with open(card_path, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# A2A Handler
# =============================================================================

async def handle_hotel_task(task_request: A2ATaskRequest) -> A2ATaskResponse:
    """
    Invokes the Hotel LangGraph and converts the final state into
    a structured A2ATaskResponse.
    """
    initial_state = {
        "task_id":           task_request.task_id,
        "parameters":        task_request.parameters,
        "raw_messages":      task_request.raw_messages,
        "agent_message":     None,
        "validation_errors": [],
        "raw_api_data":      [],
        "formatted_results": [],
        "status":            "",
    }

    final_state = await hotel_graph.ainvoke(initial_state)

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
        error="No hotels found for your request." if final_state["status"] == "failed" else None,
        metadata=ResponseMetadata(
            agent_id="hotel-agent",
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
            print(f"[HOTEL-AGENT] Heartbeat error: {exc}")


@app.on_event("startup")
async def startup():
    """
    1. Register A2A task handler with the executor.
    2. Self-register in the shared SQLite DB (no orchestrator dependency).
    3. Start background heartbeat loop.
    """
    # -- A2A executor handler
    register_handler("hotel_search", handle_hotel_task)

    # -- Build the full RPC endpoint URL
    port     = os.getenv("PORT", "8002")
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
# Run with: uvicorn app.agents.hotel.main:app --port 8002
# =============================================================================


# =============================================================================
# Run with: uvicorn app.agents.hotel.main:app --port 8002
# =============================================================================
