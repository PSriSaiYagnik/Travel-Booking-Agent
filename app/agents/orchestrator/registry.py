"""
app/agents/orchestrator/registry.py
====================================
Orchestrator-side agent discovery.

Instead of an in-memory dict that evaporates on restart, every lookup
queries the shared SQLite DB for agents whose last_seen is within the
last 60 seconds (the heartbeat TTL).

This means:
  - Orchestrator can start before any agent — it simply sees an empty list.
  - When an agent comes online it appears automatically on the next query.
  - No restart of the orchestrator is needed for new agents to be discovered.

Future migration path
---------------------
Replace get_active_agents() and get_agent() with HTTP calls to a
Registry Service without changing any other file.
"""

import json
import sqlite3
from pathlib import Path

from app.core.config import settings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    db_path = Path(settings.DB_PATH)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Public API — used by orchestrator nodes
# ---------------------------------------------------------------------------

def get_active_agents() -> list[dict]:
    """
    Return all agents that sent a heartbeat within the last 60 seconds.

    Each entry is a plain dict:
    {
        "agent_id" : "flight-agent-v1",
        "name"     : "Flight Booking Agent",
        "endpoint" : "http://localhost:8001/rpc",
        "skills"   : ["flight_search"],
    }
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT agent_id, name, endpoint, skills
            FROM   agent_registry
            WHERE  last_seen > datetime('now', '-60 seconds')
            """
        ).fetchall()
        return [
            {
                "agent_id": row["agent_id"],
                "name":     row["name"],
                "endpoint": row["endpoint"],
                "skills":   json.loads(row["skills"]),
            }
            for row in rows
        ]
    except Exception as exc:
        print(f"[REGISTRY] ❌ get_active_agents failed: {exc}")
        return []
    finally:
        conn.close()


def get_agent(agent_id: str) -> dict | None:
    """
    Return a single active agent by its agent_id, or None if not found / stale.

    The 'endpoint' field is the full RPC URL the orchestrator should POST to.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            """
            SELECT agent_id, name, endpoint, skills
            FROM   agent_registry
            WHERE  agent_id  = ?
            AND    last_seen  > datetime('now', '-60 seconds')
            """,
            (agent_id,),
        ).fetchone()

        if row is None:
            return None

        return {
            "agent_id": row["agent_id"],
            "name":     row["name"],
            "endpoint": row["endpoint"],
            "skills":   json.loads(row["skills"]),
        }
    except Exception as exc:
        print(f"[REGISTRY] ❌ get_agent({agent_id}) failed: {exc}")
        return None
    finally:
        conn.close()


def get_all_capabilities() -> dict:
    """
    Returns { agent_id: skills_list } for every active agent.
    Used by the intent-classifier node to build the LLM routing prompt.
    """
    return {
        a["agent_id"]: a["skills"]
        for a in get_active_agents()
    }
