from langgraph.graph import StateGraph, START, END

from app.agents.flight.state import FlightAgentState
from app.agents.flight.nodes import (
    extract_params_node,
    validate_input, 
    search_flights, 
    format_response,
    generate_response_node
)
from app.agents.flight.constants import (
    NODE_EXTRACT_PARAMS,
    NODE_VALIDATE_INPUT,
    NODE_SEARCH_FLIGHTS,
    NODE_FORMAT_RESPONSE,
    NODE_GENERATE_RESPONSE,
    ROUTE_SEARCH,
    ROUTE_FORMAT
)


# =============================================================================
# Conditional Edge — route after validate_input
# =============================================================================

def _route_after_validation(state: FlightAgentState) -> str:
    """
    If validate_input found errors → skip API call, go straight to format_response.
    If all required fields are present → proceed to search_flights.
    """
    if state["validation_errors"]:
        return ROUTE_FORMAT
    return ROUTE_SEARCH


# =============================================================================
# Graph Definition
# =============================================================================

def build_flight_graph() -> StateGraph:
    """
    Build and compile the Flight Agent LangGraph StateGraph.

    Graph flow:
        START
          └─► extract_params
                └─► validate_input
                      ├─► (errors found)   ──► format_response ──► generate_response ──► END
                      └─► (all good)       ──► search_flights
                                                    └─► format_response ──► generate_response ──► END

    The graph is intentionally simple — all business logic lives in nodes.py.
    """
    builder = StateGraph(FlightAgentState)

    # ── Register nodes ────────────────────────────────────────────────────────
    builder.add_node(NODE_EXTRACT_PARAMS,    extract_params_node)
    builder.add_node(NODE_VALIDATE_INPUT,    validate_input)
    builder.add_node(NODE_SEARCH_FLIGHTS,    search_flights)
    builder.add_node(NODE_FORMAT_RESPONSE,   format_response)
    builder.add_node(NODE_GENERATE_RESPONSE, generate_response_node)

    # ── Entry point ───────────────────────────────────────────────────────────
    builder.add_edge(START, NODE_EXTRACT_PARAMS)
    builder.add_edge(NODE_EXTRACT_PARAMS, NODE_VALIDATE_INPUT)

    # ── Conditional routing after validation ──────────────────────────────────
    builder.add_conditional_edges(
        NODE_VALIDATE_INPUT,
        _route_after_validation,
        {
            ROUTE_SEARCH:  NODE_SEARCH_FLIGHTS,
            ROUTE_FORMAT: NODE_FORMAT_RESPONSE,
        },
    )

    # ── Linear tail ───────────────────────────────────────────────────────────
    builder.add_edge(NODE_SEARCH_FLIGHTS, NODE_FORMAT_RESPONSE)
    builder.add_edge(NODE_FORMAT_RESPONSE, NODE_GENERATE_RESPONSE)
    builder.add_edge(NODE_GENERATE_RESPONSE, END)

    return builder.compile()


# Compiled graph singleton — imported by main.py and registered with executor
flight_graph = build_flight_graph()
