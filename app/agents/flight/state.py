from typing import Literal
from app.agents.base.state import BaseAgentState


class FlightAgentState(BaseAgentState):
    """
    State for the Flight Booking Agent's LangGraph StateGraph.

    Extends BaseAgentState with two flight-specific fields:

        trip_type:      Drives search logic in the search_flights node.
                        Inferred from parameters["trip_type"].
                            "one_way"    → single search: origin → destination
                            "round_trip" → outbound + return leg
                            "multi_city" → one search per leg in parameters["legs"]

        fallback_notes: Human-readable notes generated when the nearest-airport
                        fallback is triggered. e.g.:
                        "No direct flights to HYD. Showing flights to BOM."
                        Appended to the first result so the Orchestrator can
                        surface this information to the user.

    All other fields (task_id, parameters, validation_errors,
    raw_api_data, formatted_results, status) are inherited from
    BaseAgentState.
    """
    trip_type:      Literal["one_way", "round_trip", "multi_city"]
    fallback_notes: list[str]
