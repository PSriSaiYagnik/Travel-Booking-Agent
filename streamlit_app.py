import json
import sqlite3
import uuid
from pathlib import Path

import requests
import streamlit as st

# ─── Page Config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TravelMind AI",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Constants ────────────────────────────────────────────────────────────────
ORCHESTRATOR_URL = "http://localhost:8000/chat"
DB_PATH = Path(__file__).parent / "app" / "db" / "database.db"

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Global ── */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

.stApp {
    background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    min-height: 100vh;
}

/* ── Hide default Streamlit elements ── */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1rem; padding-bottom: 0; }

/* ── Header ── */
.app-header {
    background: rgba(255,255,255,0.05);
    backdrop-filter: blur(20px);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 16px;
    padding: 1rem 1.5rem;
    margin-bottom: 1rem;
    display: flex;
    align-items: center;
    gap: 12px;
}
.app-header h1 {
    color: #ffffff;
    font-size: 1.5rem;
    font-weight: 700;
    margin: 0;
    background: linear-gradient(90deg, #a78bfa, #60a5fa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.app-header p {
    color: rgba(255,255,255,0.5);
    font-size: 0.8rem;
    margin: 0;
}
.status-dot {
    width: 8px; height: 8px;
    background: #22c55e;
    border-radius: 50%;
    display: inline-block;
    animation: pulse 2s infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}

/* ── Chat Container ── */
.chat-container {
    height: calc(100vh - 260px);
    overflow-y: auto;
    padding: 0.5rem 0;
    scrollbar-width: thin;
    scrollbar-color: rgba(255,255,255,0.2) transparent;
}

/* ── Message Bubbles ── */
.msg-row {
    display: flex;
    margin-bottom: 1rem;
    animation: fadeSlide 0.3s ease;
}
@keyframes fadeSlide {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}
.msg-row.user  { justify-content: flex-end; }
.msg-row.bot   { justify-content: flex-start; }

.msg-bubble {
    max-width: 72%;
    padding: 0.75rem 1rem;
    border-radius: 18px;
    font-size: 0.9rem;
    line-height: 1.55;
    white-space: pre-wrap;
    word-wrap: break-word;
}
.msg-bubble.user {
    background: linear-gradient(135deg, #6d28d9, #4f46e5);
    color: #ffffff;
    border-bottom-right-radius: 4px;
    box-shadow: 0 4px 15px rgba(109,40,217,0.3);
}
.msg-bubble.bot {
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.12);
    color: #e2e8f0;
    border-bottom-left-radius: 4px;
    backdrop-filter: blur(10px);
}
.avatar {
    width: 36px; height: 36px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 1rem;
    flex-shrink: 0;
}
.avatar.bot  { background: linear-gradient(135deg, #6d28d9, #4f46e5); margin-right: 8px; }
.avatar.user { background: rgba(255,255,255,0.15); margin-left: 8px; }

/* ── Input ── */
.stChatInput > div {
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
    border-radius: 14px !important;
}
.stChatInput input {
    color: #e2e8f0 !important;
    font-family: 'Inter', sans-serif !important;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: rgba(15, 12, 41, 0.95) !important;
    border-right: 1px solid rgba(255,255,255,0.08) !important;
}
section[data-testid="stSidebar"] * { color: #e2e8f0 !important; }

.sidebar-title {
    font-size: 1rem;
    font-weight: 700;
    color: #a78bfa !important;
    margin-bottom: 0.5rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}
.booking-card {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(167,139,250,0.25);
    border-radius: 12px;
    padding: 0.75rem;
    margin-bottom: 0.75rem;
    font-size: 0.8rem;
}
.booking-card .ref {
    font-weight: 700;
    color: #a78bfa !important;
    font-size: 0.75rem;
    letter-spacing: 0.05em;
    margin-bottom: 0.4rem;
}
.booking-card .detail-row {
    display: flex;
    gap: 6px;
    margin-bottom: 2px;
    align-items: flex-start;
}
.booking-card .icon { font-size: 0.8rem; flex-shrink: 0; }
.badge-confirmed {
    display: inline-block;
    background: rgba(34,197,94,0.15);
    color: #22c55e !important;
    border: 1px solid rgba(34,197,94,0.3);
    border-radius: 20px;
    padding: 1px 8px;
    font-size: 0.65rem;
    font-weight: 600;
    margin-top: 0.3rem;
}
.no-bookings {
    color: rgba(255,255,255,0.35) !important;
    font-size: 0.8rem;
    text-align: center;
    padding: 1.5rem 0;
}
.session-id-pill {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 20px;
    padding: 4px 10px;
    font-size: 0.7rem;
    color: rgba(255,255,255,0.4) !important;
    font-family: monospace;
    word-break: break-all;
}

/* ── GIANT Sidebar Toggle Arrow ── */
[data-testid="collapsedControl"] {
    background: linear-gradient(135deg, #6d28d9, #4f46e5) !important;
    border-radius: 50% !important;
    width: 52px !important;
    height: 52px !important;
    box-shadow: 0 4px 15px rgba(109,40,217,0.5) !important;
    margin: 15px !important;
    z-index: 999999 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    transition: transform 0.2s ease !important;
}
[data-testid="collapsedControl"]:hover {
    transform: scale(1.1) !important;
}
[data-testid="collapsedControl"] svg {
    width: 28px !important;
    height: 28px !important;
    fill: white !important;
    color: white !important;
}
</style>
""", unsafe_allow_html=True)


# ─── Session Init ─────────────────────────────────────────────────────────────
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []


# ─── DB Helpers ───────────────────────────────────────────────────────────────
def load_bookings(session_id: str) -> list[dict]:
    """Pull confirmed bookings for this session from SQLite."""
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM bookings WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ─── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p class="sidebar-title">✈️ TravelMind AI</p>', unsafe_allow_html=True)
    st.markdown("---")

    # New Conversation button
    if st.button("🔄 New Conversation", use_container_width=True):
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages   = []
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # Session ID
    st.markdown('<p style="font-size:0.7rem;color:rgba(255,255,255,0.4);margin-bottom:4px;">SESSION</p>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="session-id-pill">{st.session_state.session_id[:18]}…</div>',
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<p class="sidebar-title">📋 My Bookings</p>', unsafe_allow_html=True)

    bookings = load_bookings(st.session_state.session_id)

    if not bookings:
        st.markdown('<p class="no-bookings">No bookings yet.<br>Start chatting to plan your trip!</p>', unsafe_allow_html=True)
    else:
        for b in bookings:
            flights = json.loads(b.get("flight_details") or "[]")
            hotels  = json.loads(b.get("hotel_details")  or "[]")

            flight_line = ""
            if flights:
                f = flights[0]
                flight_line = f"{f.get('origin','?')} → {f.get('destination','?')}"

            hotel_line = ""
            if hotels:
                h = hotels[0]
                hotel_line = h.get("name", "")

            st.markdown(f"""<div class="booking-card">
<div class="ref">📋 {b['booking_id']}</div>
{'<div class="detail-row"><span class="icon">✈️</span><span>' + flight_line + '</span></div>' if flight_line else ''}
{'<div class="detail-row"><span class="icon">🏨</span><span>' + hotel_line + '</span></div>' if hotel_line else ''}
<span class="badge-confirmed">✓ Confirmed</span>
</div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown('<p style="font-size:0.7rem;color:rgba(255,255,255,0.3);text-align:center;">Powered by Cerebras · LangGraph · A2A</p>', unsafe_allow_html=True)


# ─── Main Area ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="app-header">
    <span style="font-size:2rem;">✈️</span>
    <div>
        <h1>TravelMind AI</h1>
        <p><span class="status-dot"></span> &nbsp;Your intelligent travel booking assistant</p>
    </div>
</div>
""", unsafe_allow_html=True)

# Chat history
chat_html = '<div class="chat-container">'

if not st.session_state.messages:
    chat_html += """
    <div style="text-align:center; padding:3rem 1rem; color:rgba(255,255,255,0.3);">
        <div style="font-size:3rem; margin-bottom:1rem;">🌍</div>
        <p style="font-size:1rem; font-weight:500; color:rgba(255,255,255,0.5);">Where would you like to go?</p>
        <p style="font-size:0.8rem;">Try: <em>"Book a flight from Singapore to Bangalore for 4 days"</em></p>
    </div>
    """

for msg in st.session_state.messages:
    role    = msg["role"]
    content = msg["content"].replace("<", "&lt;").replace(">", "&gt;")
    if role == "user":
        chat_html += f"""
        <div class="msg-row user">
            <div class="msg-bubble user">{content}</div>
            <div class="avatar user">👤</div>
        </div>"""
    else:
        chat_html += f"""
        <div class="msg-row bot">
            <div class="avatar bot">🤖</div>
            <div class="msg-bubble bot">{content}</div>
        </div>"""

chat_html += "</div>"
st.markdown(chat_html, unsafe_allow_html=True)


# ─── Chat Input ───────────────────────────────────────────────────────────────
if user_input := st.chat_input("Message TravelMind AI…"):
    # Add user message to history immediately
    st.session_state.messages.append({"role": "user", "content": user_input})

    # Call the Orchestrator
    with st.spinner(""):
        try:
            resp = requests.post(
                ORCHESTRATOR_URL,
                json={
                    "session_id": st.session_state.session_id,
                    "message":    user_input,
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()  

            # Sync session_id (in case server assigned one)
            st.session_state.session_id = data.get("session_id", st.session_state.session_id)
            bot_reply = data.get("response", "Sorry, I couldn't process that. Please try again.")

        except requests.exceptions.ConnectionError:
            bot_reply = (
                "⚠️ I can't reach the booking server right now. "
                "Please make sure the Orchestrator is running on port 8000."
            )   
        except Exception as e:
            bot_reply = f"⚠️ Something went wrong: {str(e)}"

    st.session_state.messages.append({"role": "assistant", "content": bot_reply})
    st.rerun()
