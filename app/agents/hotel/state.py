from app.agents.base.state import BaseAgentState


class HotelAgentState(BaseAgentState):
    """
    State for the Hotel Booking Agent's LangGraph StateGraph.

    Hotels don't need multi-leg or trip_type logic — a hotel search is
    always a single destination with check-in and check-out dates.

    All required fields are inherited from BaseAgentState:
        task_id, parameters, validation_errors,
        raw_api_data, formatted_results, status

    Expected keys in parameters:
        destination          (str) : City name — e.g. "Bangalore"
        check_in_date        (str) : ISO date  — e.g. "2025-05-11"
        check_out_date       (str) : ISO date  — e.g. "2025-05-15"
        guests               (int) : Adults (default 1)
        rooms                (int) : Number of rooms (default 1)
        currency             (str) : e.g. "USD", "INR" (default "USD")
        location_preference  (str) : Optional — e.g. "near Whitefield"
    """
    pass
