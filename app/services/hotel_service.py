import requests
from app.core.config import settings

# ── Request headers re-used for every Booking.com call ───────────────────────
_HEADERS = {
    "x-rapidapi-key":  settings.RAPIDAPI_KEY,
    "x-rapidapi-host": settings.HOTEL_API_HOST,
}
_BASE_URL = f"https://{settings.HOTEL_API_HOST}"


# =============================================================================
# Internal Helper
# =============================================================================

def _resolve_destination(city: str) -> dict | None:
    """
    Resolve a city name to the Booking.com 'dest_id' and 'search_type'
    required by the hotel search endpoint.

    Uses /api/v1/hotels/searchDestination (booking-com15 API).
    """
    try:
        resp = requests.get(
            f"{_BASE_URL}/api/v1/hotels/searchDestination",
            headers=_HEADERS,
            params={"query": city},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", [])
        if items:
            first = items[0]
            return {
                "dest_id":     str(first.get("dest_id", "")),
                "search_type": first.get("search_type", "city"),
                "label":       first.get("city_name", city),
            }
    except Exception as e:
        print(f"[HOTEL_SVC] _resolve_destination error for {city!r}: {e}")
    return None


# =============================================================================
# Public API
# =============================================================================

def search_hotels(parameters: dict) -> list[dict]:
    """
    Search for available hotels using the Booking.com RapidAPI (booking-com15).

    Expected keys in 'parameters':
        destination   (str) : City name — e.g. "Bengaluru"
        check_in_date (str) : ISO date  — e.g. "2026-05-15"
        check_out_date (str): ISO date  — e.g. "2026-05-17"
        guests        (int) : Number of adult guests (default 1)
        rooms         (int) : Number of rooms (default 1)
        currency      (str) : Currency code e.g. "INR", "USD" (default "USD")

    Returns:
        List of formatted hotel dicts (up to 10 results).
        Returns [] on API failure — caller handles fallback display.
    """
    try:
        city       = parameters.get("destination", "")
        loc_pref   = parameters.get("location_preference", "")
        search_q   = f"{loc_pref}, {city}" if loc_pref else city

        check_in   = parameters.get("check_in_date", "")
        check_out  = parameters.get("check_out_date", "")
        guests     = int(parameters.get("guests") or 1)
        rooms      = int(parameters.get("rooms") or 1)
        currency   = parameters.get("currency", "USD")

        # ── Step 1: Resolve city → dest_id ───────────────────────────────────
        dest_data = _resolve_destination(search_q)
        if not dest_data:
            print(f"[HOTEL_SVC] Could not resolve destination: {search_q!r}. Using mock data.")
            return _load_mock_hotels(parameters)

        print(f"[HOTEL_SVC] Searching hotels: dest_id={dest_data['dest_id']}, "
              f"check_in={check_in}, check_out={check_out}, guests={guests}")

        # ── Step 2: Search hotels ─────────────────────────────────────────────
        resp = requests.get(
            f"{_BASE_URL}/api/v1/hotels/searchHotels",
            headers=_HEADERS,
            params={
                "dest_id":       dest_data["dest_id"],
                "search_type":   dest_data["search_type"],
                "arrival_date":  check_in,
                "departure_date": check_out,
                "adults":        guests,
                "room_qty":      rooms,
                "page_number":   "1",
                "currency_code": currency,
                "languagecode":  "en-us",
            },
            timeout=20,
        )
        resp.raise_for_status()

        hotels = resp.json().get("data", {}).get("hotels", [])
        print(f"[HOTEL_SVC] Found {len(hotels)} hotels from API")
        
        if not hotels:
            print("[HOTEL_SVC] 0 hotels found, falling back to mock data.")
            return _load_mock_hotels(parameters)

        # ── Step 3: Parse results ─────────────────────────────────────────────
        results = []
        for hotel in hotels[:10]:
            prop        = hotel.get("property", {})
            price_info  = hotel.get("priceBreakdown", {})
            # Try multiple price fields — Booking.com API structure varies
            gross_price  = price_info.get("grossPrice", {})
            exc_price    = price_info.get("excludedPrice", {})
            disc_price   = price_info.get("discountedPrice", {})

            # Pick the first non-zero price value available
            price_amount = (
                gross_price.get("value")
                or disc_price.get("value")
                or exc_price.get("value")
                or 0
            )
            price_currency = (
                gross_price.get("currency")
                or disc_price.get("currency")
                or currency
            )

            # Some responses nest price differently — try strikethrough price too
            if not price_amount:
                strike = price_info.get("strikethroughPrice", {})
                price_amount = strike.get("value", 0)

            results.append({
                "hotel_id":     str(prop.get("id", "")),
                "name":         prop.get("name", "Unknown Hotel"),
                "star_rating":  prop.get("propertyClass", 0),
                "review_score": round(float(prop.get("reviewScore", 0)), 1),
                "review_word":  prop.get("reviewScoreWord", ""),
                "price_per_night": {
                    "amount":   round(float(price_amount), 0) if price_amount else "N/A",
                    "currency": price_currency,
                },
                "address":              prop.get("wishlistName", ""),
                "city":                 prop.get("countryCode", city),
                "distance_from_centre": str(prop.get("distanceToCenter", "")),
                "thumbnail":            prop.get("photoUrls", [""])[0] if prop.get("photoUrls") else "",
            })

        return results

    except Exception as e:
        print(f"[HOTEL_SVC] API Error: {e}")
        import traceback
        traceback.print_exc()
        return _load_mock_hotels(parameters)


# =============================================================================
# Fallback mock data (used if API is unavailable)
# =============================================================================

def _load_mock_hotels(parameters: dict | None = None) -> list[dict]:
    """Returns mock hotel data when real API is unavailable."""
    p    = parameters or {}
    city = p.get("destination", "your destination")
    curr = p.get("currency", "USD")

    mock = [
        ("Grand Hyatt", 5, 9.2, 12000),
        ("Marriott Executive", 5, 8.8, 9500),
        ("Holiday Inn Express", 3, 8.1, 4200),
        ("ibis Styles", 3, 7.9, 3100),
        ("Treebo Trend", 3, 7.5, 2800),
    ]

    results = []
    for name, stars, score, price in mock:
        results.append({
            "hotel_id":     f"mock-{name.lower().replace(' ', '-')}",
            "name":         f"{name} {city}",
            "star_rating":  stars,
            "review_score": score,
            "review_word":  "Very Good" if score >= 8 else "Good",
            "price_per_night": {"amount": price, "currency": curr},
            "address":      f"{city} city centre",
            "city":         city,
            "distance_from_centre": "1.2 km",
            "thumbnail":    "",
            "_note":        "Showing estimated options — live data temporarily unavailable.",
        })
    return results
