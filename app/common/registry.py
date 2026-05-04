"""
app/common/registry.py
======================
Shared agent self-registration helper.

All agents call register_agent() and heartbeat() from here.
No agent should ever contain raw SQL — only this module does.

Future-proofing note
--------------------
When you graduate from POC → full Registry Service, replace the two
public functions below with HTTP calls to the registry API.
Agents never need to change — only this file.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings


# ---------------------------------------------------------------------------
# Internal: get a WAL-enabled connection to the shared DB
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    db_path = Path(settings.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Public API — the only surface agents should touch
# ---------------------------------------------------------------------------

def register_agent(
    agent_id: str,
    name: str,
    endpoint: str,
    skills: list[str],
) -> None:
    """
    Insert or replace this agent in the agent_registry table.

    Parameters
    ----------
    agent_id : str   Unique identifier, e.g. "flight-agent-v1"
    name     : str   Human-readable name,  e.g. "Flight Booking Agent"
    endpoint : str   Reachable URL,         e.g. "http://localhost:8001/rpc"
    skills   : list  Task types the agent handles, e.g. ["flight_search"]
    """
    now = _utcnow()
    skills_json = json.dumps(skills)

    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO agent_registry (agent_id, name, endpoint, skills, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                name      = excluded.name,
                endpoint  = excluded.endpoint,
                skills    = excluded.skills,
                last_seen = excluded.last_seen
            """,
            (agent_id, name, endpoint, skills_json, now),
        )
        conn.commit()
        print(f"[REGISTRY] ✅ Registered: {agent_id} → {endpoint}")
    except Exception as exc:
        print(f"[REGISTRY] ❌ register_agent failed for {agent_id}: {exc}")
    finally:
        conn.close()


def heartbeat(agent_id: str) -> None:
    """
    Refresh last_seen for an already-registered agent.
    Call this every ~30 s from the agent's background loop.
    """
    now = _utcnow()
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE agent_registry SET last_seen = ? WHERE agent_id = ?",
            (now, agent_id),
        )
        conn.commit()
        print(f"[REGISTRY] 💓 Heartbeat: {agent_id} @ {now}")
    except Exception as exc:
        print(f"[REGISTRY] ❌ heartbeat failed for {agent_id}: {exc}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    """ISO-8601 UTC timestamp that SQLite datetime() functions can compare."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
