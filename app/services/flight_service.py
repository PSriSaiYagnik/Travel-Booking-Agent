import random
import time
import requests

from app.core.config import settings

# ... (rest of module)

# =============================================================================
# AeroDataBox API client
# Host: aerodatabox.p.rapidapi.com
#
# Endpoints used:
#   1. GET /airports/search/term?q={query}&limit=1
#      → resolves city name / IATA code → iata, name, city
#
#   2. GET /flights/airports/iata/{iata}/{fromLocal}/{toLocal}
#      → FIDS departures for the day; filtered to the destination IATA
#
# AeroDataBox does NOT provide pricing data.
# We add realistic mock prices seeded by flight number so they stay consistent.
# =============================================================================

_HEADERS = {
    "x-rapidapi-key":  settings.RAPIDAPI_KEY,
    "x-rapidapi-host": "aerodatabox.p.rapidapi.com",
}
_BASE_URL = "https://aerodatabox.p.rapidapi.com"

# Mock price ranges (USD) by cabin class
_PRICE_RANGES: dict[str, tuple[int, int]] = {
    "economy": (80,  450),
    "business": (400, 1800),
    "first":   (1500, 5000),
}

# Pre-seeded cache for very common city/airport queries.
# Avoids hitting the API for well-known cities → saves quota and avoids 429.
_AIRPORT_CACHE: dict[str, dict | None] = {
    # Singapore
    "singapore": {"iata": "SIN", "icao": "WSSS", "name": "Singapore Changi",  "city": "Singapore"},
    "sin":       {"iata": "SIN", "icao": "WSSS", "name": "Singapore Changi",  "city": "Singapore"},
    # India
    "bangalore":  {"iata": "BLR", "icao": "VOBL", "name": "Kempegowda Intl",   "city": "Bengaluru"},
    "bengaluru":  {"iata": "BLR", "icao": "VOBL", "name": "Kempegowda Intl",   "city": "Bengaluru"},
    "banglore":   {"iata": "BLR", "icao": "VOBL", "name": "Kempegowda Intl",   "city": "Bengaluru"},
    "bangaluru":  {"iata": "BLR", "icao": "VOBL", "name": "Kempegowda Intl",   "city": "Bengaluru"},
    "blore":      {"iata": "BLR", "icao": "VOBL", "name": "Kempegowda Intl",   "city": "Bengaluru"},
    "blr":        {"iata": "BLR", "icao": "VOBL", "name": "Kempegowda Intl",   "city": "Bengaluru"},
    "delhi":      {"iata": "DEL", "icao": "VIDP", "name": "Indira Gandhi Intl","city": "New Delhi"},
    "new delhi":  {"iata": "DEL", "icao": "VIDP", "name": "Indira Gandhi Intl","city": "New Delhi"},
    "del":        {"iata": "DEL", "icao": "VIDP", "name": "Indira Gandhi Intl","city": "New Delhi"},
    "mumbai":     {"iata": "BOM", "icao": "VABB", "name": "Chhatrapati Shivaji","city": "Mumbai"},
    "bombay":     {"iata": "BOM", "icao": "VABB", "name": "Chhatrapati Shivaji","city": "Mumbai"},
    "bom":        {"iata": "BOM", "icao": "VABB", "name": "Chhatrapati Shivaji","city": "Mumbai"},
    "hyderabad":  {"iata": "HYD", "icao": "VOHS", "name": "Rajiv Gandhi Intl",  "city": "Hyderabad"},
    "hyd":        {"iata": "HYD", "icao": "VOHS", "name": "Rajiv Gandhi Intl",  "city": "Hyderabad"},
    "chennai":    {"iata": "MAA", "icao": "VOMM", "name": "Chennai Intl",        "city": "Chennai"},
    "madras":     {"iata": "MAA", "icao": "VOMM", "name": "Chennai Intl",        "city": "Chennai"},
    "maa":        {"iata": "MAA", "icao": "VOMM", "name": "Chennai Intl",        "city": "Chennai"},
    "kolkata":    {"iata": "CCU", "icao": "VECC", "name": "Netaji Subhas Intl",  "city": "Kolkata"},
    "calcutta":   {"iata": "CCU", "icao": "VECC", "name": "Netaji Subhas Intl",  "city": "Kolkata"},
    "ccu":        {"iata": "CCU", "icao": "VECC", "name": "Netaji Subhas Intl",  "city": "Kolkata"},
    "kochi":      {"iata": "COK", "icao": "VOCI", "name": "Cochin Intl",         "city": "Kochi"},
    "cochin":     {"iata": "COK", "icao": "VOCI", "name": "Cochin Intl",         "city": "Kochi"},
    "cok":        {"iata": "COK", "icao": "VOCI", "name": "Cochin Intl",         "city": "Kochi"},
    "pune":       {"iata": "PNQ", "icao": "VAPO", "name": "Pune Airport",         "city": "Pune"},
    "pnq":        {"iata": "PNQ", "icao": "VAPO", "name": "Pune Airport",         "city": "Pune"},
    "ahmedabad":  {"iata": "AMD", "icao": "VAAH", "name": "Sardar Vallabhbhai Patel Intl", "city": "Ahmedabad"},
    "amd":        {"iata": "AMD", "icao": "VAAH", "name": "Sardar Vallabhbhai Patel Intl", "city": "Ahmedabad"},
    "nellore":    {"iata": "VGA", "icao": "VOVZ", "name": "Vijayawada Airport (nearest)",   "city": "Nellore"},
    # SE Asia
    "kuala lumpur": {"iata": "KUL", "icao": "WMKK", "name": "KLIA",          "city": "Kuala Lumpur"},
    "kul":          {"iata": "KUL", "icao": "WMKK", "name": "KLIA",          "city": "Kuala Lumpur"},
    "bangkok":      {"iata": "BKK", "icao": "VTBS", "name": "Suvarnabhumi",  "city": "Bangkok"},
    "bkk":          {"iata": "BKK", "icao": "VTBS", "name": "Suvarnabhumi",  "city": "Bangkok"},
    "hong kong":    {"iata": "HKG", "icao": "VHHH", "name": "Hong Kong Intl","city": "Hong Kong"},
    "hkg":          {"iata": "HKG", "icao": "VHHH", "name": "Hong Kong Intl","city": "Hong Kong"},
    "tokyo":        {"iata": "NRT", "icao": "RJAA", "name": "Narita Intl",   "city": "Tokyo"},
    "nrt":          {"iata": "NRT", "icao": "RJAA", "name": "Narita Intl",   "city": "Tokyo"},
    "dubai":        {"iata": "DXB", "icao": "OMDB", "name": "Dubai Intl",    "city": "Dubai"},
    "dxb":          {"iata": "DXB", "icao": "OMDB", "name": "Dubai Intl",    "city": "Dubai"},
    "london":       {"iata": "LHR", "icao": "EGLL", "name": "Heathrow",      "city": "London"},
    "lhr":          {"iata": "LHR", "icao": "EGLL", "name": "Heathrow",      "city": "London"},
    "sydney":       {"iata": "SYD", "icao": "YSSY", "name": "Kingsford Smith","city": "Sydney"},
    "syd":          {"iata": "SYD", "icao": "YSSY", "name": "Kingsford Smith","city": "Sydney"},
    "new york":     {"iata": "JFK", "icao": "KJFK", "name": "JFK",           "city": "New York"},
    "jfk":          {"iata": "JFK", "icao": "KJFK", "name": "JFK",           "city": "New York"},
    "paris":        {"iata": "CDG", "icao": "LFPG", "name": "Charles de Gaulle","city": "Paris"},
    "cdg":          {"iata": "CDG", "icao": "LFPG", "name": "Charles de Gaulle","city": "Paris"},
    "goa":          {"iata": "GOI", "icao": "VOGO", "name": "Dabolim", "city": "Goa"},
}
_DURATION_MAP: dict[frozenset, int] = {
    frozenset({"SIN", "BLR"}): 330,
    frozenset({"SIN", "DEL"}): 340,
    frozenset({"SIN", "BOM"}): 300,
    frozenset({"SIN", "HYD"}): 330,
    frozenset({"SIN", "MAA"}): 210,
    frozenset({"SIN", "CCU"}): 290,
    frozenset({"SIN", "KUL"}):  60,
    frozenset({"SIN", "BKK"}): 140,
    frozenset({"SIN", "HKG"}): 230,
    frozenset({"SIN", "NRT"}): 420,
    frozenset({"SIN", "SYD"}): 500,
    frozenset({"SIN", "LHR"}): 790,
    frozenset({"SIN", "JFK"}): 900,
}


# =============================================================================
# Internal helpers
# =============================================================================

def _resolve_airport(query: str) -> dict | None:
    """
    Resolve a city name or IATA code -> {"iata", "icao", "name", "city"}.

    Checks _AIRPORT_CACHE first (pre-seeded for common cities) before
    hitting the API, so quota is only used for unknown destinations.
    """
    key = query.strip().lower()

    # 1. Check pre-seeded / previously resolved cache
    if key in _AIRPORT_CACHE:
        result = _AIRPORT_CACHE[key]
        print(f"[FLIGHT SVC] airport cache hit: {query!r} -> {result['iata'] if result else 'None'}")
        return result

    import time
    # 2. API lookup for unknown cities
    for attempt in range(3):
        try:
            resp = requests.get(
                f"{_BASE_URL}/airports/search/term",
                headers=_HEADERS,
                params={"q": query.strip(), "limit": "1"},
                timeout=10,
            )
            if resp.status_code == 429:
                print(f"[FLIGHT SVC] Rate limited resolving {query!r}. Retrying in 1s...")
                time.sleep(1)
                continue
                
            resp.raise_for_status()
            items = resp.json().get("items", [])
            if items:
                airport = items[0]
                result = {
                    "iata": airport.get("iata", ""),
                    "icao": airport.get("icao", ""),
                    "name": airport.get("name", query),
                    "city": airport.get("municipalityName", query),
                }
                _AIRPORT_CACHE[key] = result   # cache for future calls
                return result
            return None # 200 OK but empty list
        except Exception as exc:
            print(f"[FLIGHT SVC] _resolve_airport API error for {query!r}: {exc}")
            if attempt < 2:
                time.sleep(1)
            else:
                return None
    return None



def _mock_price(flight_number: str, cabin_class: str, passengers: int) -> dict:
    """Deterministic mock price seeded by flight number so it stays stable."""
    lo, hi = _PRICE_RANGES.get(cabin_class, (80, 450))
    rng = random.Random(hash(flight_number + cabin_class))
    per_person = rng.randint(lo, hi)
    total = per_person * passengers
    return {
        "amount":    total,
        "formatted": f"${total:,}",
        "currency":  "USD",
        "per_person": per_person,
    }


def _estimate_duration(origin_iata: str, dest_iata: str) -> int:
    """Return estimated flight duration in minutes."""
    key = frozenset({origin_iata.upper(), dest_iata.upper()})
    return _DURATION_MAP.get(key, 240)


def _parse_local_time(raw: str) -> str:
    """Strip timezone offset from AeroDataBox local time string."""
    # AeroDataBox format: "2025-05-15 10:30+08:00"  →  "2025-05-15T10:30"
    if not raw:
        return raw
    raw = raw.strip()
    for sep in ["+", "-"]:
        idx = raw.rfind(sep)
        if idx > 10:          # don't strip leading '-' in the date
            raw = raw[:idx]
    return raw.replace(" ", "T")


# =============================================================================
# Public API
# =============================================================================

def search_flights(parameters: dict) -> list[dict]:
    """
    Search for flights. Supports multi-city and round-trip by wrapping _search_single_route.
    """
    trip_type = parameters.get("trip_type", "one_way")
    legs = parameters.get("legs", [])
    
    all_results = []
    
    if trip_type == "multi_city" and legs:
        for leg in legs:
            all_results.extend(_search_single_route(leg.get("origin"), leg.get("destination"), leg.get("date"), parameters))
    elif trip_type == "round_trip":
        outbound = _search_single_route(parameters.get("origin"), parameters.get("destination"), parameters.get("departure_date"), parameters)
        inbound = _search_single_route(parameters.get("destination"), parameters.get("origin"), parameters.get("return_date"), parameters)
        all_results.extend(outbound)
        all_results.extend(inbound)
    else:
        all_results = _search_single_route(parameters.get("origin"), parameters.get("destination"), parameters.get("departure_date"), parameters)
        
    return all_results

def _search_single_route(origin_q: str, dest_q: str, depart_date: str, parameters: dict) -> list[dict]:
    cabin_class = parameters.get("cabin_class", "economy")
    passengers  = int(parameters.get("passengers") or 1)

    if not origin_q or not dest_q or not depart_date:
        return []

    try:
        # ── Step 1: Resolve airports ─────────────────────────────────────────
        origin_data = _resolve_airport(origin_q)
        dest_data   = _resolve_airport(dest_q)

        if not origin_data or not dest_data:
            print(f"[FLIGHT SVC] Airport resolution failed: {origin_q!r} or {dest_q!r}")
            return []

        origin_iata = origin_data["iata"]
        dest_iata   = dest_data["iata"]
        print(f"[FLIGHT SVC] Searching {origin_iata} -> {dest_iata} on {depart_date}")

        # ── Step 2: Fetch FIDS departures (max 12h window per call) ─────────
        # AeroDataBox requires each time window to be ≤ 12 hours.
        # Split the day into AM (00:00-12:00) and PM (12:00-23:59) windows.
        departures: list[dict] = []
        windows = [
            (f"{depart_date}T00:00", f"{depart_date}T12:00"),
            (f"{depart_date}T12:00", f"{depart_date}T23:59"),
        ]
        for from_dt, to_dt in windows:
            for attempt in range(3):
                try:
                    resp = requests.get(
                        f"{_BASE_URL}/flights/airports/iata/{origin_iata}/{from_dt}/{to_dt}",
                        headers=_HEADERS,
                        params={
                            "direction":      "Departure",
                            "withCancelled":  "false",
                            "withCodeshared": "false",
                            "withCargo":      "false",
                            "withPrivate":    "false",
                        },
                        timeout=20,
                    )
                    if resp.status_code == 429:
                        print(f"[FLIGHT SVC] FIDS {from_dt}-{to_dt} => 429 Rate limit. Retrying in 1.5s...")
                        time.sleep(1.5)
                        continue
                        
                    if resp.status_code == 200:
                        departures.extend(resp.json().get("departures", []))
                    else:
                        print(f"[FLIGHT SVC] FIDS {from_dt}-{to_dt} => {resp.status_code}: {resp.text[:100]}")
                    break # success or non-429 error, break retry loop
                except Exception as exc:
                    print(f"[FLIGHT SVC] FIDS Request Error {from_dt}-{to_dt}: {exc}")
                    if attempt < 2:
                        time.sleep(1.5)
                    else:
                        break

        print(f"[FLIGHT SVC] Total departures from {origin_iata}: {len(departures)}")

        # ── Step 3: Filter to destination ────────────────────────────────────
        to_dest = [
            f for f in departures
            if f.get("movement", {})
                .get("airport", {})
                .get("iata", "").upper() == dest_iata.upper()
        ]
        print(f"[FLIGHT SVC] Flights to {dest_iata}: {len(to_dest)}")

        if not to_dest:
            print(f"[FLIGHT SVC] ️  No AeroDataBox flights found for {origin_iata} → {dest_iata} on {depart_date}. Returning empty — no mock fallback.")
            return []

        # ── Step 4: Format results ───────────────────────────────────────────
        results = []
        duration = _estimate_duration(origin_iata, dest_iata)

        for flight in to_dest[:10]:
            number   = flight.get("number", "").replace(" ", "")
            airline  = flight.get("airline", {})
            movement = flight.get("movement", {})

            dep_time_raw = movement.get("scheduledTime", {}).get("local", "")
            dep_clean    = _parse_local_time(dep_time_raw)

            arr_clean = ""
            if dep_clean:
                try:
                    from datetime import datetime, timedelta
                    dep_dt  = datetime.fromisoformat(dep_clean)
                    arr_dt  = dep_dt + timedelta(minutes=duration)
                    arr_clean = arr_dt.strftime("%Y-%m-%dT%H:%M:00")
                except Exception:
                    pass

            results.append({
                "flight_id":        number,
                "airline":          airline.get("name", "Unknown Airline"),
                "flight_number":    number,
                "departure_time":   dep_clean,
                "arrival_time":     arr_clean,
                "duration_minutes": duration,
                "stops":            0,
                "cabin_class":      cabin_class,
                "price":            _mock_price(number, cabin_class, passengers),
                "origin":           origin_data["city"],
                "destination":      dest_data["city"],
                "origin_iata":      origin_iata,
                "destination_iata": dest_iata,
            })

        print(f"[FLIGHT SVC]  Returning {len(results)} real flights from AeroDataBox.")
        return results

    except Exception as exc:
        print(f"[FLIGHT SVC]  API error: {exc}")
        return []


# =============================================================================
# Mock fallback (used when API is unavailable or returns no results)
# =============================================================================

def _load_mock_flights(parameters: dict | None = None) -> list[dict]:
    """
    Context-aware mock flights used when the real API fails or returns nothing.
    Mock times and prices are seeded by route so they stay stable per route.
    """
    p           = parameters or {}
    origin      = p.get("origin", "Origin City")
    destination = p.get("destination", "Destination City")
    depart      = p.get("departure_date", "2026-06-01")
    cabin       = p.get("cabin_class", "economy")
    passengers  = int(p.get("passengers") or 1)

    print(f"[FLIGHT SVC] Using mock data for {origin} -> {destination} on {depart}")

    mock_airlines = [
        ("Singapore Airlines", "SQ", "501"),
        ("Air India",          "AI", "342"),
        ("IndiGo",             "6E", "1234"),
    ]

    results = []
    dep_hours = [8, 11, 15]

    for i, (airline_name, iata, num) in enumerate(mock_airlines):
        fn     = f"{iata}{num}"
        dep_h  = dep_hours[i]
        arr_h  = dep_h + 4           # rough 4-hour flight
        price  = _mock_price(fn, cabin, passengers)
        results.append({
            "flight_id":        f"mock-{fn}",
            "airline":          airline_name,
            "flight_number":    fn,
            "departure_time":   f"{depart}T{dep_h:02d}:30:00",
            "arrival_time":     f"{depart}T{arr_h:02d}:00:00",
            "duration_minutes": 210,
            "stops":            0,
            "cabin_class":      cabin,
            "price":            price,
            "origin":           origin,
            "destination":      destination,
            "origin_iata":      "",
            "destination_iata": "",
            "_note":            "Showing estimated schedules — live data temporarily unavailable.",
        })

    return results
