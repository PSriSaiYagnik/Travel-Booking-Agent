from app.agents.hotel.state import HotelAgentState
import json
from datetime import date
from app.core.llm import llm
from app.agents.orchestrator.prompts import (
    HOTEL_PARAM_EXTRACTION_PROMPT,
    RESPONSE_GENERATION_PROMPT,
)


# =============================================================================
# New Node: extract_params
# =============================================================================

import json
import re
from datetime import date

def extract_params_node(state: HotelAgentState) -> dict:
    print("[HOTEL_AGENT]  Entering Node: extract_params_node")

    # ── Prepare inputs ────────────────────────────────────────────────────────
    history = "\n".join(
        [f"{m.get('role', 'user')}: {m.get('content', '')}" for m in state["raw_messages"][-6:]]
    )
    user_msg = state["raw_messages"][-1].get("content", "") if state["raw_messages"] else ""

    today_str = date.today().isoformat()
    year = date.today().year

    existing_params = state.get("parameters", {}).copy()

    # ── Step 0: Inject flight context (if exists) ─────────────────────────────
    flight_params = state.get("flight_params", {}) or {}

    if flight_params:
        # destination from flight
        if not existing_params.get("destination") and flight_params.get("destination"):
            existing_params["destination"] = flight_params["destination"]

        # check-in = flight departure
        if not existing_params.get("check_in_date") and flight_params.get("departure_date"):
            existing_params["check_in_date"] = flight_params["departure_date"]

    # ── Step 1: LLM Extraction ────────────────────────────────────────────────
    prompt = HOTEL_PARAM_EXTRACTION_PROMPT.format(
        today=today_str,
        year=str(year),
        existing_params=json.dumps(existing_params, indent=2),
        recent_history=history,
        user_message=user_msg,
    )

    raw = llm.invoke(prompt).content.strip()

    parsed = {}
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
        except json.JSONDecodeError:
            print("[HOTEL_AGENT] JSON parse failed from LLM")

    extracted = {
        k: v for k, v in parsed.get("extracted", {}).items() if v is not None
    }

    # ── Step 2: Merge safely (DO NOT overwrite check-in if already set) ───────
    new_params = existing_params.copy()

    for k, v in extracted.items():
        if k == "check_in_date" and new_params.get("check_in_date"):
            continue
        new_params[k] = v

    # ── Step 3: Remove flight-related garbage fields ─────────────────────────
    for garbage_key in [
        "trip_type", "legs", "duration_days", "passengers",
        "origin", "duration", "departure_date", "return_date", "cabin_class"
    ]:
        new_params.pop(garbage_key, None)

    # ── Step 4: Regex date extraction (SOURCE OF TRUTH) ───────────────────────
    _MONTHS = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        "january": 1, "february": 2, "march": 3, "april": 4,
        "june": 6, "july": 7, "august": 8, "september": 9,
        "october": 10, "november": 11, "december": 12,
    }

    msg_lower = user_msg.lower().strip()
    all_dates = []

    pattern_day_month = re.compile(
        r'(\d{1,2})(?:st|nd|rd|th)?\s+'
        r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?'
        r'|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
    )

    pattern_month_day = re.compile(
        r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?'
        r'|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
        r'\s+(\d{1,2})(?:st|nd|rd|th)?'
    )

    pattern_iso = re.compile(r'(\d{4}-\d{2}-\d{2})')

    for m in pattern_day_month.finditer(msg_lower):
        day = int(m.group(1))
        month = _MONTHS.get(m.group(2)[:3])
        if month:
            all_dates.append((m.start(), f"{year}-{month:02d}-{day:02d}"))

    for m in pattern_month_day.finditer(msg_lower):
        day = int(m.group(2))
        month = _MONTHS.get(m.group(1)[:3])
        if month:
            all_dates.append((m.start(), f"{year}-{month:02d}-{day:02d}"))

    for m in pattern_iso.finditer(user_msg):
        all_dates.append((m.start(), m.group(1)))

    # Sort + dedupe
    seen = set()
    unique_dates = []
    for pos, d in sorted(all_dates, key=lambda x: x[0]):
        if d not in seen:
            seen.add(d)
            unique_dates.append(d)

    print(f"[HOTEL_AGENT] Python regex found dates in message: {unique_dates}")

    # ── Step 5: Context-aware date assignment ────────────────────────────────
    if unique_dates:
        existing_checkin = new_params.get("check_in_date")

        if existing_checkin:
            # 👉 flight-first OR already set → interpret as checkout
            new_params["check_out_date"] = unique_dates[-1]
            print(f"[HOTEL_AGENT] Interpreting as check_out_date={unique_dates[-1]}")

        else:
            # 👉 hotel-first flow
            if len(unique_dates) == 1:
                new_params["check_in_date"] = unique_dates[0]
                new_params["check_out_date"] = None
            else:
                new_params["check_in_date"] = unique_dates[0]
                new_params["check_out_date"] = unique_dates[-1]

    # ── Step 6: Final validation (no same-day or reverse stays) ───────────────
    check_in = new_params.get("check_in_date")
    check_out = new_params.get("check_out_date")

    if check_in and check_out and check_out <= check_in:
        print("[HOTEL_AGENT] Invalid date range detected, clearing check_out_date")
        new_params["check_out_date"] = None

    # ── Step 7: Clean empty values ───────────────────────────────────────────
    new_params = {k: v for k, v in new_params.items() if v is not None}

    print(f"[HOTEL_AGENT] Final extracted params: {new_params}")

    return {"parameters": new_params}

# =============================================================================
# Node 1 — validate_input
# =============================================================================

def validate_input(state: HotelAgentState) -> dict:
    """
    Validate that all required hotel search parameters are present.

    Required fields:
        destination    — city name
        check_in_date  — ISO date string
        check_out_date — ISO date string

    Optional (have defaults in hotel_service):
        guests, rooms, currency, location_preference

    Sets:
        validation_errors: list of missing-field messages
        status:            "needs_clarification" if errors, else unchanged
    """
    print("[HOTEL_AGENT]  Entering Node: validate_input")
    params = state["parameters"]
    errors: list[str] = []

    for field in ["destination", "check_in_date", "check_out_date"]:
        if not params.get(field):
            errors.append(f"Missing required field: '{field}'")

    # Logical check: check_out must be after check_in
    if not errors:
        from datetime import date as _date
        today_str = _date.today().isoformat()

        if params["check_in_date"] < today_str:
            errors.append(
                f"Check-in date cannot be in the past. "
                f"Today is {today_str}, but you requested {params['check_in_date']}."
            )
        elif params["check_in_date"] >= params["check_out_date"]:
            errors.append(
                "check_out_date must be after check_in_date. "
                f"Got check_in={params['check_in_date']}, "
                f"check_out={params['check_out_date']}"
            )

    return {
        "validation_errors": errors,
        "status": "needs_clarification" if errors else state["status"],
    }


# =============================================================================
# Node 2 — search_hotels
# =============================================================================

async def search_hotels(state: HotelAgentState) -> dict:
    """Call hotel_service via MCP with the validated parameters."""
    print("--------------------------------------------------")
    print("[HOTEL_AGENT Node]  Proceeding to call MCP Client...")
    if state["validation_errors"]:
        return {}

    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.services.mcp_server"]
    )

    params = state["parameters"]
    results = []

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print(f"[HOTEL_AGENT Client]  Piping request to MCP Server over stdio for destination={params.get('destination')}...")
            res = await session.call_tool("search_hotels", arguments={"parameters_json": json.dumps(params)})
            print(f"[HOTEL_AGENT Client]  Received data back from MCP Server!")

            results = json.loads(res.content[0].text)

    print(f"[HOTEL_AGENT Client] Finished MCP flow. Found {len(results)} results.")
    print("--------------------------------------------------")

    return {"raw_api_data": results}


# =============================================================================
# Node 3 — format_response
# =============================================================================

def format_response(state: HotelAgentState) -> dict:
    """
    Finalise formatted_results and set the definitive status.

    Status rules:
        validation_errors non-empty  → "needs_clarification"
        raw_api_data empty           → "failed"
        results found                → "success"
    """
    print("[HOTEL_AGENT]  Entering Node: format_response")
    if state["validation_errors"]:
        return {
            "formatted_results": [],
            "status":            "needs_clarification",
        }

    raw = state.get("raw_api_data", [])

    if not raw:
        return {
            "formatted_results": [],
            "status":            "failed",
        }

    return {
        "formatted_results": list(raw),
        "status":            "success",
    }


# =============================================================================
# Node 4 — generate_response
# =============================================================================

def generate_response_node(state: HotelAgentState) -> dict:
    """
    Generates the chat response.
    
    - SUCCESS: Pure Python formatting (deterministic, no LLM hallucination risk).
    - NEEDS_CLARIFICATION: LLM asks only for the specific missing fields.
    - FAILED: Simple Python fallback message.
    """
    print("[HOTEL_AGENT]  Entering Node: generate_response_node")
    status  = state.get("status")
    params  = state.get("parameters", {})
    results = state.get("formatted_results", [])
    errors  = state.get("validation_errors", [])

    # ── CASE 1: SUCCESS — format hotel list directly in Python ───────────────
    if status == "success" and results:
        destination = params.get("destination", "your destination")
        check_in    = params.get("check_in_date", "")
        check_out   = params.get("check_out_date", "")

        lines = [
            f"🏨 Here are the top hotels in **{destination}** "
            f"({check_in} → {check_out}):\n"
        ]
        for i, h in enumerate(results[:5], 1):
            name    = h.get("name", "Hotel")
            stars   = "⭐" * int(h.get("star_rating", h.get("stars", 0)))
            review  = h.get("review_score", h.get("rating", "N/A"))
            price   = h.get("price_per_night", {})
            amt     = price.get("amount", price) if isinstance(price, dict) else price
            cur     = price.get("currency", "USD") if isinstance(price, dict) else "USD"
            lines.append(f"{i}. **{name}** {stars} | Review: {review}/10 | {cur} {amt}/night")

        lines.append("\nWhich number would you like to book?")
        msg = "\n".join(lines)
        print(f"[HOTEL_AGENT] Generated success response with {len(results)} hotels.")
        return {"agent_message": msg}

    # ── CASE 2: NEEDS CLARIFICATION — LLM asks only for the missing fields ──
    if status == "needs_clarification" and errors:
        missing_labels = []
        for e in errors:
            if "check_out_date" in e or "check_out" in e:
                missing_labels.append("check-out date")
            elif "check_in_date" in e or "check_in" in e:
                missing_labels.append("check-in date")
            elif "destination" in e:
                missing_labels.append("destination city")
            else:
                missing_labels.append(e)

        # Use the LLM only to phrase the question naturally
        missing_str = ", ".join(missing_labels)
        from app.agents.orchestrator.prompts import RESPONSE_GENERATION_PROMPT
        prompt = RESPONSE_GENERATION_PROMPT.format(
            intent="hotel_only",
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

    # ── CASE 3: FAILED — no results found ───────────────────────────────────
    destination = params.get("destination", "your destination")
    msg = (
        f"😔 Sorry, I couldn't find any available hotels in **{destination}** "
        f"for your selected dates. Would you like to try different dates or a nearby city?"
    )
    return {"agent_message": msg}

