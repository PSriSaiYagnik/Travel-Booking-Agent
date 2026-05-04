from typing import Annotated, TypedDict, Optional
import operator
from langgraph.graph.message import add_messages


class OrchestratorState(TypedDict):
    """
    Persistent state for the Orchestrator's LangGraph StateGraph.

    Unlike sub-agent states (which are short-lived per A2A task),
    this state persists across ALL turns of a user session via
    the SqliteSaver checkpointer.

    ── Conversation ─────────────────────────────────────────────────────────
    messages:       Full chat history between user and assistant.
                    Uses LangGraph's add_messages reducer — new messages are
                    APPENDED, not replaced, on every turn.
    session_id:     UUID identifying this conversation. Passed as thread_id
                    to the LangGraph checkpointer.

    ── Intent & Routing ─────────────────────────────────────────────────────
    intent:         What the Orchestrator classified the user's last message as.
                    One of:
                        "flight_only"    → search flights only
                        "hotel_only"     → search hotels only
                        "both"           → search both
                        "general"        → travel question, answer directly
                        "off_topic"      → unrelated, politely redirect
                        "clarification"  → user answering our follow-up question
                        "confirmation"   → user said yes / book it
                        "change_request" → user wants to modify something

    ── Extracted Parameters ─────────────────────────────────────────────────
    travel_params:  Dict of all extracted travel details so far.
                    Keys vary by trip type, e.g.:
                        { "origin": "SIN", "destination": "BLR",
                          "departure_date": "2025-05-11",
                          "return_date": "2025-05-15",
                          "trip_type": "round_trip",
                          "guests": 1, "rooms": 1,
                          "check_in_date": "2025-05-11",
                          "check_out_date": "2025-05-15",
                          "location_preference": "near Whitefield" }
    missing_fields: Fields still needed from the user before we can delegate.
                    e.g. ["departure_date", "passengers"]
    changed_fields: Fields the user just changed mid-conversation.
                    Used to selectively clear stale results.
                    e.g. ["destination"] → clear flight_results + hotel_results
                         ["location_preference"] → clear hotel_results only

    ── Sub-Agent Results ────────────────────────────────────────────────────
    flight_results: Results returned by the Flight Agent (list of flight dicts).
                    Reset to [] when changed_fields affects flights.
    hotel_results:  Results returned by the Hotel Agent (list of hotel dicts).
                    Reset to [] when changed_fields affects hotels.

    ── Booking Flow ─────────────────────────────────────────────────────────
    booking_status: Tracks where we are in the confirmation lifecycle.
                    One of:
                        "idle"                  → no search done yet
                        "searching"             → agents being called
                        "awaiting_confirmation" → itinerary shown, waiting for yes/no
                        "confirmed"             → user said yes, stored in DB
                        "cancelled"             → user said no / cancelled

    pending_itinerary: The last itinerary shown to the user.
                       Stored here while waiting for confirmation.
                       {"flights": [...], "hotels": [...]}
    confirmed_booking: What was written to the DB after confirmation.
                       {"booking_id": "BK-...", "flight_details": ..., "hotel_details": ...}

    ── Response ─────────────────────────────────────────────────────────────
    final_response: The assistant message to be sent to the user.
                    Set by generate_response node at the end of every turn.
    """

    # Conversation
    messages:   Annotated[list, add_messages]
    session_id: str
    fallback_note: Optional[str]

    # Intent & routing
    intent:                     str
    missing_fields:             list[str]
    changed_fields:             list[str]
    awaiting_clarification_from: Optional[str]
    guardrail_decision:          Optional[str]

    # Extracted travel parameters
    travel_params: dict

    # Sub-agent results
    flight_results: list[dict]
    hotel_results:  list[dict]

    # Booking flow
    booking_status:    str
    current_leg_index: int
    pending_itinerary: dict
    confirmed_booking: dict
    round_trip_phase:  Optional[str]   # "outbound" | "return" | None

    # Final message to display
    final_response: str
