"""
Flight Agent Nodes — LangGraph nodes for the Flight sub-agent.

Three nodes, executed in order by flight/graph.py:

    validate_input   → checks required fields are present & valid
    search_flights   → calls flight_service to hit AeroDataBox API
    format_response  → normalises raw API data into A2ATaskResponse shape

All business logic (API calls, fallback logic) lives in app/services/flight_service.py.
These nodes are purely responsible for state transitions and error handling.
"""

from datetime import date, datetime, timedelta
import json

from app.agents.flight.state import FlightAgentState
from app.services.flight_service import search_flights as svc_search_flights
from app.core.llm import llm
from app.agents.orchestrator.prompts import PARAM_EXTRACTION_PROMPT, RESPONSE_GENERATION_PROMPT



# =============================================================================
# Internal helpers
# =============================================================================

def _get_fallback_airports(destination: str) -> list[str]:
    """
    DB-seeded fallback airports for common routes where the destination
    airport has limited direct service.
    """
    _FALLBACKS: dict[str, list[str]] = {
        "HBX": ["BLR", "HYD", "BOM"],  # Hubli → Bengaluru, Hyderabad, Mumbai
        "IXE": ["BLR", "BOM", "MAA"],  # Mangalore → Bengaluru, Mumbai, Chennai
        "VGA": ["HYD", "BLR", "MAA"],  # Vijayawada → Hyderabad, Bengaluru, Chennai
        "TRV": ["BOM", "DEL", "BLR"],  # Trivandrum → Mumbai, Delhi, Bengaluru
        "IXZ": ["MAA", "BLR", "BOM"],  # Port Blair → Chennai, Bengaluru, Mumbai
    }
    return _FALLBACKS.get(destination.upper(), [])


def _llm_suggest_fallbacks(origin: str, destination: str) -> list[str]:
    """
    Ask the LLM for alternate airports near the destination when the DB
    has no pre-seeded fallbacks. Returns up to 3 IATA codes.
    """
    from app.core.llm import llm

    prompt = (
        f"You are an aviation expert. The user wants to fly from {origin} to {destination}. "
        f"There are no direct flights available. "
        f"Suggest up to 3 major airports near {destination} that likely have direct flights from {origin}. "
        f"Respond with ONLY a JSON array of IATA codes. Example: [\"BLR\", \"HYD\", \"BOM\"]"
    )
    try:
        raw = llm.invoke(prompt).content.strip()
        import json, re
        match = re.search(r'\[.*?\]', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"[FLIGHT NODE] LLM fallback suggestion error: {e}")
    return []


def _search_with_fallback(params: dict) -> tuple[list[dict], str | None]:
    """Helper - previously used for sync API calls, now deprecated. Kept for signature compatibility if used elsewhere, but MCP handles it inside search_flights directly."""
    return [], None


# =============================================================================
# New Node: extract_params
# =============================================================================

def extract_params_node(state: FlightAgentState) -> dict:
    print("[FLIGHT_AGENT]  Entering Node: extract_params_node")
    
    import re

    # ── Step 0: Detect flight selection (NEW) ─────────────────────────
    user_msg = state["raw_messages"][-1].get("content", "") if state["raw_messages"] else ""

    match = re.search(r'\b(\d+)(st|nd|rd|th)?\b', user_msg.lower())

    if match and state.get("formatted_results"):
        index = int(match.group(1)) - 1
        print(f"[FLIGHT_AGENT] Detected selection: index={index}")

        return {
            "selected_flight_index": index,
            "booking_status": "awaiting_confirmation",
        }

    # ── Existing logic continues unchanged ─────────────────────────────
    history = "\n".join([f"{m.get('role', 'user')}: {m.get('content', '')}" for m in state["raw_messages"][-6:]])
    
    prompt = PARAM_EXTRACTION_PROMPT.format(
        today=date.today().isoformat(),
        year=str(date.today().year),
        existing_params=json.dumps(state.get("parameters", {}), indent=2),
        recent_history=history,
        user_message=user_msg,
    )

    raw = llm.invoke(prompt).content

    parsed = {}
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    print(f"[FLIGHT_AGENT] Raw LLM extraction:\n{raw}")
    if match:
        try:
            parsed = json.loads(match.group())
        except json.JSONDecodeError as e:
            print(f"[FLIGHT_AGENT] JSONDecodeError: {e}")

    extracted = {k: v for k, v in parsed.get("extracted", {}).items() if v is not None}

    new_params = state.get("parameters", {}).copy()
    new_params.update(extracted)

    # trip_type handling
    valid_trip_types = {"one_way", "round_trip", "multi_city"}
    trip_type = new_params.get("trip_type") or "one_way"
    if trip_type not in valid_trip_types:
        trip_type = "one_way"

    new_params["trip_type"] = trip_type

    # Calculate return_date if duration_days is provided
    if new_params.get("departure_date") and new_params.get("duration_days") and not new_params.get("return_date"):
        try:
            dep_date = datetime.strptime(new_params["departure_date"], "%Y-%m-%d")
            duration = int(new_params["duration_days"])
            ret_date = dep_date + timedelta(days=duration)
            new_params["return_date"] = ret_date.strftime("%Y-%m-%d")
            print(f"[FLIGHT_AGENT] Calculated return_date: {new_params['return_date']} based on duration_days={duration}")
        except (ValueError, TypeError):
            pass

    print(f"[FLIGHT_AGENT] Extracted params: origin={new_params.get('origin')}, dest={new_params.get('destination')}, date={new_params.get('departure_date')}, return={new_params.get('return_date')}, pax={new_params.get('passengers')}, trip_type={trip_type}")

    return {"parameters": new_params, "trip_type": trip_type}

# =============================================================================
# Node 1 — validate_input
# =============================================================================

def validate_input(state: FlightAgentState) -> dict:
    """
    Check that all fields required for the given trip_type are present.

    trip_type rules:
        one_way    → origin, destination, departure_date, passengers
        round_trip → origin, destination, departure_date, return_date, passengers
        multi_city → legs (non-empty list), each leg has origin, destination, date
                     passengers is still required at top level.

    Sets validation_errors (list of human-readable strings) and
    trip_type on the state so downstream nodes don't need to re-read parameters.

    Also validates that departure_date is not in the past.
    """
    print("[FLIGHT AGENT]  Entering Node: validate_input")
    params    = state["parameters"]
    errors    = []
    # Always default to one_way — never error on missing/unknown trip_type
    trip_type = params.get("trip_type") or "one_way"
    if trip_type not in ("one_way", "round_trip", "multi_city"):
        trip_type = "one_way"

    today = date.today()

    if trip_type == "one_way":
        for field in ("origin", "destination", "departure_date", "passengers"):
            if not params.get(field):
                errors.append(f"Missing required field: {field}")
        dep = params.get("departure_date")
        if dep:
            try:
                if date.fromisoformat(dep) < today:
                    errors.append(f"departure_date {dep!r} is in the past.")
            except ValueError:
                errors.append(f"departure_date {dep!r} is not a valid date (YYYY-MM-DD).")

    elif trip_type == "round_trip":
        for field in ("origin", "destination", "departure_date", "return_date", "passengers"):
            if not params.get(field):
                errors.append(f"Missing required field: {field}")
        dep = params.get("departure_date")
        ret = params.get("return_date")
        if dep:
            try:
                dep_dt = date.fromisoformat(dep)
                if dep_dt < today:
                    errors.append(f"departure_date {dep!r} is in the past.")
                if ret:
                    ret_dt = date.fromisoformat(ret)
                    if ret_dt <= dep_dt:
                        errors.append("return_date must be after departure_date.")
            except ValueError as e:
                errors.append(f"Invalid date format: {e}")

    elif trip_type == "multi_city":
        if not params.get("passengers"):
            errors.append("Missing required field: passengers")
        legs = params.get("legs", [])
        if not legs:
            errors.append("multi_city trip requires at least one leg in 'legs'.")
        for i, leg in enumerate(legs):
            for field in ("origin", "destination", "date"):
                if not leg.get(field):
                    errors.append(f"Leg {i + 1} missing required field: {field}")
            leg_date = leg.get("date")
            if leg_date:
                try:
                    if date.fromisoformat(leg_date) < today:
                        errors.append(f"Leg {i + 1} date {leg_date!r} is in the past.")
                except ValueError:
                    errors.append(f"Leg {i + 1} date {leg_date!r} is not valid (YYYY-MM-DD).")

    print(f"[FLIGHT AGENT] validate_input errors: {errors}")
    return {
        "validation_errors": errors,
        "trip_type":         trip_type,
        "fallback_notes":    [],
    }


# =============================================================================
# Node 2 — search_flights
# =============================================================================

async def search_flights(state: FlightAgentState) -> dict:
    print("--------------------------------------------------")
    print("[FLIGHT_AGENT Node]  Proceeding to call MCP Client...")

    # ✅ NEW: skip search if user selected a flight
    if state.get("selected_flight_index") is not None:
        print("[FLIGHT_AGENT] Skipping search — user already selected flight")
        return {}   # Nothing to do — format_response will handle the error

    import sys
    import json
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.services.mcp_server"]
    )

    params      = state["parameters"]
    trip_type   = state["trip_type"]
    all_results: list[dict] = []
    notes:       list[str]  = []

    # Spin up our standard FastMCP local server via stdio
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def _api_search(p: dict) -> list[dict]:
                print(f"[FLIGHT_AGENT Client]  Piping request to MCP Server over stdio for origin={p.get('origin')} dest={p.get('destination')}...")
                res = await session.call_tool("search_flights", arguments={"parameters_json": json.dumps(p)})
                print(f"[FLIGHT_AGENT Client]  Received data back from MCP Server!")
                return json.loads(res.content[0].text)

            async def _search_with_fb(p: dict) -> tuple[list[dict], str | None]:
                results = await _api_search(p)
                if results:
                    return results, None

                dest = p.get("destination", "").upper()
                # Only try alternate airports for small/regional airports that are
                # pre-seeded in the fallback dict. Do NOT suggest HYD/MUM for Bangalore.
                alternates = _get_fallback_airports(dest)

                for alt_dest in alternates:
                    alt_results = await _api_search({**p, "destination": alt_dest})
                    if alt_results:
                        note = f"No direct flights found to {dest}. Showing flights to {alt_dest} — the nearest served airport."
                        return alt_results, note

                # Live API returned nothing for this known major airport → use mock data
                from app.services.flight_service import _load_mock_flights
                mock = _load_mock_flights(p)
                note = "Showing estimated schedules — live flight data temporarily unavailable for this route."
                return mock, note

            # Logic based on trip type utilizing the new _search_with_fb logic:
            if trip_type == "one_way":
                results, note = await _search_with_fb(params)
                all_results.extend(results)
                if note: notes.append(note)

            elif trip_type == "round_trip":
                outbound, note = await _search_with_fb(params)
                for r in outbound: r["leg"] = "outbound"
                all_results.extend(outbound)
                if note: notes.append(f"Outbound: {note}")

                return_params = {**params, "origin": params["destination"], "destination": params["origin"], "departure_date": params["return_date"]}
                inbound, note = await _search_with_fb(return_params)
                for r in inbound: r["leg"] = "return"
                all_results.extend(inbound)
                if note: notes.append(f"Return: {note}")

            elif trip_type == "multi_city":
                for i, leg in enumerate(params.get("legs", [])):
                    leg_params = {**params, "origin": leg["origin"], "destination": leg["destination"], "departure_date": leg["date"]}
                    results, note = await _search_with_fb(leg_params)
                    label = f"{leg['origin']} → {leg['destination']}"
                    
                    if not results:
                        notes.append(f"Leg {i + 1} ({label}): No flights found, and all alternate routes failed.")
                    else:
                        for r in results:
                            r["leg"] = f"leg_{i + 1}"
                            r["leg_label"] = label
                        all_results.extend(results)
                        
                    if note: notes.append(f"Leg {i + 1} ({label}): {note}")

    print(f"[FLIGHT_AGENT Client] Finished MCP flow. Found {len(all_results)} results.")
    print("--------------------------------------------------")
    return {
        "raw_api_data":   all_results,
        "fallback_notes": notes,
    }


# =============================================================================
# Node 3 — format_response
# =============================================================================

def format_response(state: FlightAgentState) -> dict:
    """
    Convert raw API data into a normalised list of flight dicts,
    or surface validation/search errors as a failed/needs_clarification status.

    Output shape (each item in formatted_results):
        flight_id, airline, flight_number, origin, destination,
        departure_time, arrival_time, duration_minutes, stops,
        cabin_class, price {amount, currency, formatted, per_person},
        leg (optional), leg_label (optional)
    """
    print("[FLIGHT AGENT]  Entering Node: format_response")

    errors      = state.get("validation_errors", [])
    raw         = state.get("raw_api_data",      [])
    notes       = state.get("fallback_notes",     [])

    # ── Validation failure ────────────────────────────────────────────────────
    if errors:
        print(f"[FLIGHT AGENT] format_response: returning needs_clarification, errors={errors}")
        return {
            "formatted_results": [],
            "status":            "needs_clarification",
        }

    # ── No results after search ───────────────────────────────────────────────
    if not raw:
        print("[FLIGHT AGENT] format_response: no results found")
        return {
            "formatted_results": [],
            "status":            "partial" if notes else "failed",
        }

    # ── Normalise fields ──────────────────────────────────────────────────────
    formatted = []
    for f in raw:
        dep_raw = f.get("departure_time", "")
        arr_raw = f.get("arrival_time",   "")

        # Ensure time strings are clean ISO format
        dep_clean = dep_raw.replace(" ", "T") if dep_raw else ""
        arr_clean = arr_raw.replace(" ", "T") if arr_raw else ""

        entry = {
            "flight_id":        f.get("flight_id",        f.get("flight_number", "")),
            "airline":          f.get("airline",           "Unknown Airline"),
            "flight_number":    f.get("flight_number",     ""),
            "origin":           f.get("origin",            ""),
            "destination":      f.get("destination",       ""),
            "departure_time":   dep_clean,
            "arrival_time":     arr_clean,
            "duration_minutes": f.get("duration_minutes",  0),
            "stops":            f.get("stops",             0),
            "cabin_class":      f.get("cabin_class",       "economy"),
            "price":            f.get("price", {"amount": 0, "currency": "USD", "formatted": "$0", "per_person": 0}),
        }

        # Preserve leg labels for multi-city
        if "leg" in f:
            entry["leg"]       = f["leg"]
        if "leg_label" in f:
            entry["leg_label"] = f["leg_label"]

        # Surface any note from the service layer
        if "_note" in f:
            entry["_note"] = f["_note"]

        formatted.append(entry)

    # Attach fallback notes to first result so Orchestrator can surface them
    if notes and formatted:
        formatted[0]["_fallback_notes"] = notes

    print(f"[FLIGHT AGENT] format_response: returning {len(formatted)} formatted results")
    return {
        "formatted_results": formatted,
        "status":            "success",
    }

# =============================================================================
# New Node: generate_response
# =============================================================================

def generate_response_node(state: FlightAgentState) -> dict:
    print("[FLIGHT_AGENT]  Entering Node: generate_response_node")

    # ── NEW: Handle selection → confirmation ─────────────────────────
    if state.get("selected_flight_index") is not None:
        idx = state["selected_flight_index"]
        results = state.get("formatted_results", [])

        if 0 <= idx < len(results):
            f = results[idx]

            airline  = f.get("airline", "Unknown")
            fnum     = f.get("flight_number", "")
            dep_t    = f.get("departure_time", "").replace("T", " ")[:16]
            arr_t    = f.get("arrival_time", "").replace("T", " ")[:16]
            price    = f.get("price", {})
            amt      = price.get("amount", price) if isinstance(price, dict) else price
            cur      = price.get("currency", "USD") if isinstance(price, dict) else "USD"

            msg = f"""
Please confirm your booking:

✈️ {airline} {fnum}
🕒 {dep_t} → {arr_t}
💰 {cur} {amt}

Reply **yes** to confirm or **change** to modify.
"""

            return {
                "agent_message": msg,
                "booking_status": "awaiting_confirmation"
            }
  
    status  = state.get("status")
    params  = state.get("parameters", {})
    results = state.get("formatted_results", [])
    errors  = state.get("validation_errors", [])

    # ── CASE 1: SUCCESS — format flight list directly in Python ─────────────
    if status == "success" and results:
        trip_type   = params.get("trip_type", "one_way")
        origin      = params.get("origin", "")
        destination = params.get("destination", "")
        dep_date    = params.get("departure_date", "")
        ret_date    = params.get("return_date", "")
        fallback    = " | ".join(state.get("fallback_notes", []))

        # For round trips: only show outbound flights here.
        # The return flights will be presented by the orchestrator
        # AFTER the user confirms the outbound selection.
        if trip_type == "round_trip":
            display_results = [f for f in results if f.get("leg") == "outbound"]
            if not display_results:
                display_results = results  # safety fallback
            header = f"✈️ **Outbound flights** from **{origin}** to **{destination}** on {dep_date}:\n_(Return: {ret_date})_\n"
        else:
            display_results = results
            header = f"✈️ Here are available flights from **{origin}** to **{destination}** on {dep_date}:\n"

        lines = [header]
        if fallback:
            lines.append(f"_ℹ️ {fallback}_\n")

        for i, f in enumerate(display_results[:5], 1):
            airline  = f.get("airline", "Unknown")
            fnum     = f.get("flight_number", "")
            dep_t    = f.get("departure_time", "").replace("T", " ")[:16]
            arr_t    = f.get("arrival_time",   "").replace("T", " ")[:16]
            dur      = f.get("duration_minutes", 0)
            stops    = f.get("stops", 0)
            price    = f.get("price", {})
            amt      = price.get("amount", price) if isinstance(price, dict) else price
            cur      = price.get("currency", "USD") if isinstance(price, dict) else "USD"
            stop_str = "Non-stop" if stops == 0 else f"{stops} stop(s)"
            dur_str  = f"{dur // 60}h {dur % 60}m" if dur else ""
            lines.append(
                f"{i}. **{airline}** {fnum} | {dep_t} → {arr_t} | {dur_str} | {stop_str} | {cur} {amt}"
            )

        lines.append("\nWhich flight would you like to book?")
        msg = "\n".join(lines)
        print(f"[FLIGHT_AGENT] Generated success response with {len(display_results)} flights (trip_type={trip_type}).")
        return {"agent_message": msg}


    # ── CASE 2: NEEDS CLARIFICATION — LLM asks only for the missing fields ──
    if errors:
        missing_labels = []
        for e in errors:
            if "departure_date" in e or "departure" in e:
                missing_labels.append("departure date")
            elif "return_date" in e or "return" in e:
                missing_labels.append("return date")
            elif "passengers" in e:
                missing_labels.append("number of passengers")
            elif "origin" in e:
                missing_labels.append("departure city")
            elif "destination" in e:
                missing_labels.append("destination city")
            # Skip any technical/internal error strings

        # Deduplicate
        seen = set()
        unique_labels = [lbl for lbl in missing_labels if not (lbl in seen or seen.add(lbl))]

        if unique_labels:
            missing_str = ", ".join(unique_labels)
            prompt = RESPONSE_GENERATION_PROMPT.format(
                intent="flight_only",
                booking_status="needs_clarification",
                travel_params=json.dumps(params, indent=2),
                flight_results="[]",
                hotel_results="[]",
                missing_fields=missing_str,
                clarification_message=f"Please ask the user for these specific missing details: {missing_str}",
                fallback_note="",
                confirmed_booking="{}",
            )
            msg = llm.invoke(prompt).content.strip()
            return {"agent_message": msg}

    # ── CASE 3: FAILED / PARTIAL ─────────────────────────────────────────────
    origin      = params.get("origin", "your origin")
    destination = params.get("destination", "your destination")
    msg = (
        f"😔 Sorry, I couldn't find any flights from **{origin}** to **{destination}** "
        f"for the selected date. Would you like to try different dates?"
    )
    return {"agent_message": msg}
