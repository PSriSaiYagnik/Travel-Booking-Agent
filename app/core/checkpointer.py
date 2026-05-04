import sqlite3
from pathlib import Path

from app.core.config import settings


def _get_connection() -> sqlite3.Connection:
    """
    Open a synchronous SQLite connection and apply the application schema.

    This connection is used ONLY for direct DB queries from application code
    (e.g. writing to bookings, messages, user_sessions).

    LangGraph state persistence uses a SEPARATE AsyncSqliteSaver that is
    created inside the FastAPI lifespan in orchestrator/main.py.
    """
    db_path = Path(settings.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    schema_path = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
    conn.executescript(schema_path.read_text())
    conn.commit()

    return conn


# Shared sync connection — for app-level DB operations (bookings, sessions, etc.)
db_conn: sqlite3.Connection = _get_connection()
