-- =============================================================================
-- Schema for Multi-Agent Booking System
-- =============================================================================
-- NOTE: LangGraph's SqliteSaver auto-creates its own internal tables
-- (checkpoints, checkpoint_blobs, checkpoint_writes) for state persistence.
-- This file defines the APPLICATION-LEVEL tables we own and manage.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. user_sessions
--    One row per conversation. Created when a user starts chatting.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_sessions (
    session_id   TEXT PRIMARY KEY,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- -----------------------------------------------------------------------------
-- 2. messages
--    Full readable chat history per session.
--    role: 'user' | 'assistant'
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    role         TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content      TEXT NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES user_sessions(session_id)
);


-- -----------------------------------------------------------------------------
-- 3. agent_registry
--    Agents self-register here on startup via app/common/registry.py.
--    The orchestrator queries this table dynamically — no in-memory dict.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_registry (
    agent_id   TEXT PRIMARY KEY,          -- e.g. "flight-agent-v1"
    name       TEXT NOT NULL,             -- human-readable name
    endpoint   TEXT NOT NULL,             -- full reachable URL, e.g. "http://localhost:8001/rpc"
    skills     TEXT NOT NULL,             -- JSON array, e.g. ["flight_search"]
    last_seen  TEXT NOT NULL              -- ISO-8601 UTC, compared via SQLite datetime()
);


-- -----------------------------------------------------------------------------
-- 4. bookings
--    Stores confirmed itineraries after user says "Yes, book it".
--    No real booking is made — this is the simulated confirmation record.
--    flight_details and hotel_details are stored as JSON strings.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bookings (
    booking_id      TEXT PRIMARY KEY,   -- e.g. 'BK-20250511-SIN-BLR'
    session_id      TEXT NOT NULL,
    flight_details  TEXT,               -- JSON: confirmed flight leg(s)
    hotel_details   TEXT,               -- JSON: confirmed hotel (nullable)
    status          TEXT DEFAULT 'confirmed',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES user_sessions(session_id)
);


-- -----------------------------------------------------------------------------
-- 5. airport_fallbacks
--    When the flight API returns zero results for a destination,
--    the flight agent tries these nearby airports in priority order.
--    Adding a new fallback = insert a row. Zero code changes required.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS airport_fallbacks (
    airport_code   TEXT NOT NULL,   -- IATA code the user requested
    fallback_code  TEXT NOT NULL,   -- Nearby airport to try instead
    priority       INTEGER DEFAULT 1, -- Lower number = try first
    PRIMARY KEY (airport_code, fallback_code)
);

-- Seed: pre-populate common Indian / Asian routes with limited connectivity
INSERT OR IGNORE INTO airport_fallbacks (airport_code, fallback_code, priority) VALUES
    ('HYD', 'BOM', 1), ('HYD', 'DEL', 2), ('HYD', 'MAA', 3), ('HYD', 'BLR', 4),
    ('CCU', 'DEL', 1), ('CCU', 'GAY', 2),
    ('BBI', 'CCU', 1), ('BBI', 'DEL', 2),
    ('GOI', 'BOM', 1), ('GOI', 'BLR', 2),
    ('IXB', 'CCU', 1), ('IXB', 'GAU', 2),
    ('SXR', 'DEL', 1), ('SXR', 'JAI', 2),
    ('LEH', 'DEL', 1);
