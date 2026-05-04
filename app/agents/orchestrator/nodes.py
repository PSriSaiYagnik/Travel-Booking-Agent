import json
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage

from app.a2a.client.wrapper import send_task
from app.a2a.schemas import A2ATaskRequest
from app.agents.orchestrator.prompts import (
    DIRECT_ANSWER_PROMPT,
    SEMANTIC_ROUTER_PROMPT,
)
from app.agents.orchestrator.state import OrchestratorState
from app.agents.orchestrator.registry import get_agent, get_all_capabilities
from app.core.checkpointer import db_conn
from app.core.llm import llm
import re


# =============================================================================
# Shared Helpers
# =============================================================================

def _last_user_message(state: OrchestratorState) -> str:
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            return msg.content
        if isinstance(msg, dict) and msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _recent_history(state: OrchestratorState, n: int = 10) -> str:
    lines = []
    for msg in state["messages"][-n:]:
        if isinstance(msg, (HumanMessage, dict)):
            content = msg.content if hasattr(msg, "content") else msg.get("content", "")
            role = "User"
        else:
            content = msg.content if hasattr(msg, "content") else msg.get("content", "")
            role = "Assistant"
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _safe_json(text: str) -> dict:
    """Parse LLM JSON response. Handles markdown fences and text surrounding the JSON."""
    import re
    text = text.strip()

    # Strip ```json ... ``` or ``` ... ``` fences
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif text.startswith("```"):
        text = "\n".join(text.split("\n")[1:-1]).strip()

    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract JSON object — greedy so it spans the FULL object (first { to last })
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {}


from app.guardrails.input_validator import evaluate_guardrail
from app.guardrails.types import GuardrailDecision

# =============================================================================
# Node 0: Guardrail
# =============================================================================

def guardrail_node(state: OrchestratorState) -> dict:
    print("[GUARDRAIL] Evaluating input")
    user_msg = _last_user_message(state)
    booking_status = state.get("booking_status", "idle")
    
    decision = evaluate_guardrail(user_msg, booking_status)
    print(f"[GUARDRAIL] Decision: {decision.value}")
    
    return {"guardrail_decision": decision.value}

def reject_response_node(state: OrchestratorState) -> dict:
    msg = "I am a specialized travel assistant. I can only help you with searching and booking flights and hotels. How can I help you with your travel plans today?"
    return {
        "final_response": msg,
        "messages": [AIMessage(content=msg)],
    }

# =============================================================================
# Node 1: intent_classifier
# =============================================================================
import json
import re
from langchain_core.messages import HumanMessage
def intent_classifier_node(state: OrchestratorState) -> dict:
    print("[INTENT_CLASSIFIER] Entering intent classification")

    booking_status  = state.get("booking_status", "idle")
    awaiting_agent  = state.get("awaiting_clarification_from") or ""
    travel_params   = state.get("travel_params", {})

    print(f"[INTENT_CLASSIFIER] State → booking_status={booking_status!r}, awaiting={awaiting_agent!r}, hotel_results={bool(state.get('hotel_results'))}")

    # ── Fetch live agent capabilities from DB ────────────────────────────────
    _capabilities      = get_all_capabilities()          # {agent_id: [skills...]}
    _active_agent_ids  = set(_capabilities.keys())

    # Graceful empty-state: if no agents are registered yet, tell the user
    if not _active_agent_ids:
        msg = "I'm sorry, there are no travel agents online right now. Please try again in a few moments."
        print("[INTENT_CLASSIFIER] No active agents found in registry.")
        return {
            "intent": "no_agents", 
            "final_response": msg,
            "messages": [AIMessage(content=msg)]
        }

    # Build the {available_agents} block injected into the prompt
    # e.g.  "  flight-agent-v1  - skills: flight_search\n  hotel-agent-v1  - skills: hotel_search"
    _agent_lines = "\n".join(
        f"  {aid}  - skills: {', '.join(skills)}"
        for aid, skills in _capabilities.items()
    )

    # ── Control intents (always valid regardless of DB) ──────────────────────
    _CONTROL_INTENTS = {"both", "off_topic", "clarification", "confirmation", "change_request", "unsupported_service"}
    VALID_INTENTS    = _CONTROL_INTENTS | _active_agent_ids
    print(f"[INTENT_CLASSIFIER] Active agents from DB: {_active_agent_ids}")

    context = {
        "booking_status":              booking_status,
        "awaiting_clarification_from": awaiting_agent or "none",
        "has_flight_results":          bool(state.get("flight_results")),
        "has_hotel_results":           bool(state.get("hotel_results")),
        "confirmed_destination":       travel_params.get("destination", "none"),
    }

    recent_history = "\n".join(
        f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}"
        for m in state["messages"][-6:]
        if hasattr(m, "content")
    )

    prompt = SEMANTIC_ROUTER_PROMPT.format(
        available_agents=_agent_lines,
        context_json=json.dumps(context, indent=2),
        recent_history=recent_history,
        user_message=_last_user_message(state),
    )

    response = llm.invoke(prompt)
    raw = response.content.strip()

    print("\n[INTENT_CLASSIFIER] Raw LLM response:\n", raw)

    matches = re.findall(r'"intent"\s*:\s*"([^"]+)"', raw)
    
    if not matches:
        raise ValueError(f"[INTENT_CLASSIFIER] No intent found in LLM output:\n{raw}")

    parsed = matches[-1].strip() # Get the LAST occurrence, in case of CoT reasoning
    print(f"[INTENT_CLASSIFIER] Extracted intent: {parsed}")

    if parsed not in VALID_INTENTS:
        print(f"[INTENT_CLASSIFIER] WARNING: LLM hallucinated invalid intent '{parsed}'. Falling back to 'unsupported_service'.")
        parsed = "unsupported_service"

    intent = parsed

    if intent == "unsupported_service":
        msg = "I'm sorry, the travel service you are looking for (like flights or hotels) is currently offline or not supported."
        return {
            "intent": "unsupported_service",
            "final_response": msg,
            "messages": [AIMessage(content=msg)]
        }

    # ── Post-process clarification → route to awaiting agent ────────────────
    if intent == "clarification" and awaiting_agent:
        print(f"[INTENT_CLASSIFIER] clarification → routing to awaiting agent '{awaiting_agent}'")
        intent = awaiting_agent

    print(f"[INTENT_CLASSIFIER] Final intent: {intent!r}")

    return {"intent": intent}   



# =============================================================================
# Node 3: dispatch_to_agent  (Dynamic A2A Dispatcher)
# =============================================================================

async def dispatch_to_agent_node(state: OrchestratorState) -> dict:
    """Dynamically sends A2A task to whatever agent_id the router decided on."""
    agent_id   = state.get("intent")
    agent_info = get_agent(agent_id)   # live DB query — works even after restarts

    if not agent_info:
        print(f"[ORCHESTRATOR] Agent '{agent_id}' not found or offline (no recent heartbeat).")
        msg = f"I'm sorry, the {agent_id} service is currently unavailable. Please try again in a moment."
        return {"final_response": msg, "messages": [AIMessage(content=msg)]}

    print(f"[ORCHESTRATOR] Dispatching to agent: {agent_id}")

    # Build the parameters to pass to the agent
    params = state.get("travel_params", {}).copy()

    # ── Auto-populate hotel params from confirmed flight data ─────────────────
    # When the user says "yes" to a hotel offer after confirming a flight,
    # the destination and dates are already known — no need to ask again.
    if agent_id == "hotel-agent":
        # Infer hotel destination from flight destination if not set
        if not params.get("destination"):
            confirmed = state.get("confirmed_booking", {})
            for f in confirmed.get("flights", []):
                if f.get("destination"):
                    params["destination"] = f["destination"]
                    break

        # Infer check-in from departure_date
        if not params.get("check_in_date") and params.get("departure_date"):
            params["check_in_date"] = params["departure_date"]

        # IMPORTANT: Do NOT auto-set check_out_date with a guess.
        # If it is missing or invalid, hotel validate_input will ask the user.
        # Only carry over check_out if it was explicitly set (e.g. from "for N days" round trip).
        if params.get("check_out_date") and params.get("check_in_date"):
            from datetime import date as _date
            try:
                if params["check_out_date"] <= params["check_in_date"]:
                    del params["check_out_date"]   # invalid, let agent ask
            except Exception:
                params.pop("check_out_date", None)

        # Infer guests from passengers count
        if not params.get("guests") and params.get("passengers"):
            params["guests"] = params["passengers"]

        print(f"[ORCHESTRATOR] Hotel params: destination={params.get('destination')}, "
              f"check_in={params.get('check_in_date')}, check_out={params.get('check_out_date')}, "
              f"guests={params.get('guests')}")
    # ─────────────────────────────────────────────────────────────────────────

    # -- endpoint is already the full RPC URL stored in DB
    full_url  = agent_info["endpoint"]

    raw_msgs = [{"role": m.type if hasattr(m, "type") else m.get("role", "user"),
                 "content": m.content if hasattr(m, "content") else m.get("content", "")} 
                for m in state["messages"]]
                
    task = A2ATaskRequest(
        task_type=agent_info["skills"][0] if agent_info["skills"] else "unknown",
        session_id=state["session_id"],
        parameters=params,   # enriched params (hotel auto-populated from flight if applicable)
        raw_messages=raw_msgs
    )
    
    print(f"[ORCHESTRATOR] calling {full_url}")
    try:
        # Override the default send_task URL with our dynamic one
        import httpx
        from app.a2a.schemas import JsonRpcRequest, JsonRpcResponse
        import uuid
        
        rpc_req = JsonRpcRequest(
            method="execute_task",
            params=task,
            id=str(uuid.uuid4())
        )
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(full_url, json=rpc_req.model_dump())
            resp.raise_for_status()
            rpc_res = JsonRpcResponse(**resp.json())
            if rpc_res.error:
                raise Exception(rpc_res.error.message)
            agent_resp = rpc_res.result
            
        # ── Merge extracted params into accumulated travel_params ────────────
        # CRITICAL: always MERGE, never replace — earlier turns collected
        # origin/destination/trip_type etc. that must survive across turns.
        existing_params = state.get("travel_params", {})
        new_extracted   = {k: v for k, v in (agent_resp.extracted_params or {}).items() if v is not None}
        merged_params   = {**existing_params, **new_extracted}

        update_dict = {
            "travel_params": merged_params,
        }


        
        if agent_resp.agent_message:
            update_dict["final_response"] = agent_resp.agent_message
            update_dict["messages"] = [AIMessage(content=agent_resp.agent_message)]
            
        # Track which agent is waiting for clarification
        if agent_resp.status == "needs_clarification":
            update_dict["awaiting_clarification_from"] = agent_id
        else:
            update_dict["awaiting_clarification_from"] = None
            
        if agent_resp.status == "success" and agent_resp.results:
            update_dict["booking_status"] = "awaiting_confirmation"

            if task.task_type == "flight_search":
                update_dict["flight_results"] = agent_resp.results
                update_dict["pending_itinerary"] = {
                    "flights": agent_resp.results,
                    "hotels": [],   # no hotels yet in this itinerary
                }
            elif task.task_type == "hotel_search":
                update_dict["hotel_results"] = agent_resp.results
                # CRITICAL: do NOT carry over old flight_results here.
                # confirm_booking_node checks hotels_in_itinerary and flights_in_itinerary
                # to decide which confirmation path to take.
                # If we include stale flights, it wrongly confirms a flight instead of the hotel.
                update_dict["flight_results"] = []   # clear so confirm goes to hotel path
                update_dict["pending_itinerary"] = {
                    "flights": [],                   # hotel-only confirmation
                    "hotels": agent_resp.results,
                }
            
        return update_dict
        
    except Exception as e:
        import traceback
        print(f"[{agent_id.upper()}] ERROR: {e}")
        print(traceback.format_exc())
        msg = f"I'm sorry, I encountered an error while talking to the {agent_id}."
        return {"final_response": msg, "messages": [AIMessage(content=msg)]}



# =============================================================================
# Node 6: confirm_booking
# =============================================================================

def confirm_booking_node(state: OrchestratorState) -> dict:
    """
    Simulates booking confirmation.
    Persists the itinerary to the bookings table and generates a booking ID.
    No real airline/hotel API is called — this is a simulated confirmation.
    """
    import re
    itinerary = state.get("pending_itinerary", {})
    user_msg  = _last_user_message(state).lower()

    # ── Determine what is being confirmed: hotel or flight ───────────────────
    hotels_in_itinerary  = itinerary.get("hotels", [])
    flights_in_itinerary = itinerary.get("flights", [])

    # ── Hotel confirmation path ───────────────────────────────────────────────
    if hotels_in_itinerary and not flights_in_itinerary:
        # User is picking a hotel option by number
        selected_hotel = None
        opt_match = re.search(r'(?:option|opt|number)?\s*(\d+)(?:st|nd|rd|th)?\s*(?:one)?', user_msg)
        if opt_match:
            try:
                idx = int(opt_match.group(1)) - 1
                if 0 <= idx < len(hotels_in_itinerary):
                    selected_hotel = hotels_in_itinerary[idx]
            except Exception:
                pass
        if not selected_hotel and hotels_in_itinerary:
            selected_hotel = hotels_in_itinerary[0]  # fallback to first

        existing_confirmed = state.get("confirmed_booking", {})
        previously_confirmed_flights = existing_confirmed.get("flights", [])
        previously_confirmed_hotels  = existing_confirmed.get("hotels", [])
        all_hotels = previously_confirmed_hotels + ([selected_hotel] if selected_hotel else [])

        booking_id = existing_confirmed.get("booking_id") or (
            f"BK-{datetime.now(timezone.utc).strftime('%Y%m%d')}-"
            f"{state['session_id'][:6].upper()}"
        )

        db_conn.execute(
            """INSERT OR REPLACE INTO bookings
               (booking_id, session_id, flight_details, hotel_details, status)
               VALUES (?, ?, ?, ?, 'confirmed')""",
            (
                booking_id,
                state["session_id"],
                json.dumps(previously_confirmed_flights),
                json.dumps(all_hotels),
            ),
        )
        db_conn.commit()

        msg = f" Booking confirmed!\n**Booking Reference:** `{booking_id}`\n\n"
        if selected_hotel:
            price = selected_hotel.get("price_per_night", {})
            msg += (
                f" **{selected_hotel.get('name', 'Hotel')}**\n"
                f"   Check-in: {state.get('travel_params', {}).get('check_in_date', 'TBD')} | "
                f"Check-out: {state.get('travel_params', {}).get('check_out_date', 'TBD')}\n"
                f"   {price.get('currency', '')} {price.get('amount', '')} / night\n"
            )
        msg += "\nHave a wonderful trip! Is there anything else I can help you with?"

        return {
            "confirmed_booking": {
                "booking_id": booking_id,
                "flights":    previously_confirmed_flights,
                "hotels":     all_hotels,
            },
            "booking_status":            "confirmed",
            "awaiting_clarification_from": None,
            "hotel_results":             [],
            "pending_itinerary":         {},
            "final_response":            msg,
            "messages":                  [AIMessage(content=msg)],
        }

    # ── Flight confirmation path ──────────────────────────────────────────────
    flights = flights_in_itinerary
    selected_flight = None
    if flights:
        # Check for explicit index mentions like "option 2", "2nd one", or just "2"
        opt_match = re.search(r'(?:option|opt|number)?\s*(\d+)(?:st|nd|rd|th)?\s*(?:one)?', user_msg)
        if opt_match:
            try:
                idx = int(opt_match.group(1)) - 1
                if 0 <= idx < len(flights):
                    selected_flight = flights[idx]
            except Exception:
                pass
                
        if not selected_flight:
            for f in flights:
                f_num = f.get("flight_number", "").lower()
                a_name = f.get("airline", "").lower().split()[0]
                
                # Extract "HH:MM" from ISO string "2026-05-15T19:40:00"
                dep_time = ""
                if "T" in f.get("departure_time", ""):
                    dep_time = f["departure_time"].split("T")[1][:5]
                    
                # Highest priority: Exact flight number OR departure time
                if (f_num and f_num in user_msg) or (dep_time and dep_time in user_msg):
                    selected_flight = f
                    break
                    
                # Lower priority: Airline name
                if a_name and a_name in user_msg and not selected_flight:
                    selected_flight = f
                    
        if not selected_flight:
            selected_flight = flights[0]  # fallback
            
    existing_confirmed = state.get("confirmed_booking", {})
    previously_confirmed_flights = existing_confirmed.get("flights", [])
    
    previously_confirmed_hotels = existing_confirmed.get("hotels", [])
    new_hotels = itinerary.get("hotels", [])[:1]
    all_hotels = previously_confirmed_hotels + new_hotels if new_hotels else previously_confirmed_hotels
    
    final_flights = previously_confirmed_flights + ([selected_flight] if selected_flight else [])

    booking_id = existing_confirmed.get("booking_id") or (
        f"BK-{datetime.now(timezone.utc).strftime('%Y%m%d')}-"
        f"{state['session_id'][:6].upper()}"
    )

    db_conn.execute(
        """INSERT OR REPLACE INTO bookings
           (booking_id, session_id, flight_details, hotel_details, status)
           VALUES (?, ?, ?, ?, 'confirmed')""",
        (
            booking_id,
            state["session_id"],
            json.dumps(final_flights),
            json.dumps(all_hotels),
        ),
    )
    db_conn.commit()

    new_confirmed_booking = {
        "booking_id": booking_id,
        "flights":    final_flights,
        "hotels":     all_hotels,
    }
    
    params = state.get("travel_params", {})
    if params.get("trip_type") == "multi_city" and not itinerary.get("hotels"): 
        current_idx = state.get("current_leg_index", 0)
        legs = params.get("legs", [])
        
        if current_idx < len(legs) - 1:
            next_leg = legs[current_idx + 1]
            response = f" Leg {current_idx + 1} Confirmed!\n\n"
            if selected_flight:
                response += f"️ {selected_flight.get('airline')} {selected_flight.get('flight_number')} | {selected_flight.get('origin')} -> {selected_flight.get('destination')} | {selected_flight.get('price', {}).get('currency', 'USD')} {selected_flight.get('price', {}).get('amount', 0)}\n\n"
            response += f"Now, let's plan the next leg! What date would you like to fly from {next_leg.get('origin')} to {next_leg.get('destination')}?"
            
            return {
                "current_leg_index": current_idx + 1,
                "flight_results": [],
                "booking_status": "idle",
                "confirmed_booking": new_confirmed_booking,
                "messages": [AIMessage(content=response)]
            }

    # Generate confirmation text
    msg = f" Great news! Your booking has been confirmed.\n**Booking Reference:** `{booking_id}`\n\n"
    if selected_flight:
        msg += f"️ Confirmed Flight: **{selected_flight.get('airline')}** ({selected_flight.get('flight_number')})\n"
    
    msg += "\n**Shall we search for a hotel for this trip?**"
    
    return {
        "confirmed_booking": new_confirmed_booking,
        "booking_status": "confirmed",
        # Signal that we asked about hotel — router will send user's yes/no straight to hotel-agent
        "awaiting_clarification_from": "hotel-agent",
        "final_response": msg,
        "messages": [AIMessage(content=msg)]
    }



# =============================================================================
# Node 7: direct_answer
# =============================================================================

def direct_answer_node(state: OrchestratorState) -> dict:
    """
    Answers general travel questions directly without calling sub-agents.
    Used for off_topic (polite redirect) and general (travel info) intents.
    """
    prompt   = DIRECT_ANSWER_PROMPT.format(user_message=_last_user_message(state))
    response = llm.invoke(prompt).content
    return {
        "final_response": response,
        "messages":       [AIMessage(content=response)],
    }


# =============================================================================
# Node 8: generate_response
# =============================================================================

