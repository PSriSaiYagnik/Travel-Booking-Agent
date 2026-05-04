import asyncio
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

from app.agents.orchestrator.graph import build_orchestrator_graph
from app.agents.orchestrator.registry import get_active_agents
from app.core.checkpointer import db_conn
from app.core.config import settings


# =============================================================================
# Background Tasks & Lifespan
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context.

    Creates an AsyncSqliteSaver (aiosqlite-backed) and builds the
    Orchestrator graph with it. This ensures async compatibility with
    orchestrator_graph.ainvoke().

    The saver stays alive for the entire life of the server process.
    Agent discovery is now fully dynamic (DB query per request) —
    no cleanup task needed here.
    """
    db_path = str(Path(settings.DB_PATH).resolve())

    async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
        await saver.setup()
        app.state.orchestrator_graph = build_orchestrator_graph(checkpointer=saver)
        yield   # Server runs here — everything after yield is teardown


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="Travel Booking Orchestrator",
    description=(
        "Main Orchestrator agent. Accepts user messages, coordinates "
        "Flight and Hotel sub-agents via A2A/JSON-RPC, and returns "
        "a conversational response."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# =============================================================================
# Request / Response Models
# =============================================================================

class ChatRequest(BaseModel):
    session_id: str | None = None   # None → new session is created
    message: str


class ChatResponse(BaseModel):
    session_id: str
    response: str

# Note: /register and /heartbeat endpoints have been removed.
# Agents self-register directly into SQLite via app/common/registry.py.


# =============================================================================
# DB Helpers  (sync — use the shared db_conn from checkpointer.py)
# =============================================================================

def _upsert_session(session_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        """INSERT INTO user_sessions (session_id, created_at, last_active)
           VALUES (?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET last_active = excluded.last_active""",
        (session_id, now, now),
    )
    db_conn.commit()


def _save_message(session_id: str, role: str, content: str) -> None:
    db_conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        (session_id, role, content),
    )
    db_conn.commit()


# =============================================================================
# Chat Endpoint
# =============================================================================

@app.post("/chat", response_model=ChatResponse)
async def chat(req: Request, body: ChatRequest) -> ChatResponse:
    """
    Main conversational endpoint called by the Streamlit UI.

    Flow:
        1. Assign or reuse session_id
        2. Upsert session in DB
        3. Persist user message
        4. Build graph input state (new HumanMessage)
        5. ainvoke() the orchestrator graph (resumes from checkpoint)
        6. Persist assistant response
        7. Return response
    """
    session_id = body.session_id or str(uuid.uuid4())

    _upsert_session(session_id)
    _save_message(session_id, "user", body.message)

    # Only provide fields that are NEW this turn.
    # All persistent state (travel_params, flight_results, booking_status, etc.)
    # is preserved by the AsyncSqliteSaver checkpoint — don't reset them here.
    graph_input = {
        "messages":    [HumanMessage(content=body.message)],
        "session_id":  session_id,
    }

    try:
        config      = {"configurable": {"thread_id": session_id}}
        graph       = req.app.state.orchestrator_graph
        final_state = await graph.ainvoke(graph_input, config=config)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Orchestrator error: {str(e)}")

    response_text = final_state.get(
        "final_response",
        "I'm sorry, something went wrong. Please try again.",
    )

    _save_message(session_id, "assistant", response_text)

    return ChatResponse(session_id=session_id, response=response_text)


# =============================================================================
# Health Check
# =============================================================================

@app.get("/health")
async def health():
    return {"status": "ok", "service": "orchestrator"}


@app.get("/agents")
async def list_agents():
    """
    Returns all agents currently alive in the registry (heartbeat within 60 s).
    Useful for debugging / health dashboards.
    """
    return {a["agent_id"]: a["endpoint"] for a in get_active_agents()}


# =============================================================================
# Run with: uvicorn app.agents.orchestrator.main:app --port 8000 --reload
# =============================================================================
