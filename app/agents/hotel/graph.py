from langgraph.graph import StateGraph, START, END

from app.agents.hotel.state import HotelAgentState
from app.agents.hotel.nodes import (
    extract_params_node,
    validate_input, 
    search_hotels, 
    format_response,
    generate_response_node
)
from app.agents.hotel.constants import (
    NODE_EXTRACT_PARAMS,
    NODE_VALIDATE_INPUT,
    NODE_SEARCH_HOTELS,
    NODE_FORMAT_RESPONSE,
    NODE_GENERATE_RESPONSE,
    ROUTE_SEARCH,
    ROUTE_FORMAT
)


# =============================================================================
# Conditional Edge
# =============================================================================

def _route_after_validation(state: HotelAgentState) -> str:
    """Skip API call if validation found errors."""
    return ROUTE_FORMAT if state["validation_errors"] else ROUTE_SEARCH


# =============================================================================
# Graph Definition
# =============================================================================

def build_hotel_graph() -> StateGraph:
    """
    Build and compile the Hotel Agent LangGraph StateGraph.

    Graph flow:
        START
          └─► extract_params
                └─► validate_input
                      ├─► (errors)  ──► format_response ──► generate_response ──► END
                      └─► (ok)      ──► search_hotels
                                            └─► format_response ──► generate_response ──► END
    """
    builder = StateGraph(HotelAgentState)

    builder.add_node(NODE_EXTRACT_PARAMS,    extract_params_node)
    builder.add_node(NODE_VALIDATE_INPUT,    validate_input)
    builder.add_node(NODE_SEARCH_HOTELS,     search_hotels)
    builder.add_node(NODE_FORMAT_RESPONSE,   format_response)
    builder.add_node(NODE_GENERATE_RESPONSE, generate_response_node)

    builder.add_edge(START, NODE_EXTRACT_PARAMS)
    builder.add_edge(NODE_EXTRACT_PARAMS, NODE_VALIDATE_INPUT)

    builder.add_conditional_edges(
        NODE_VALIDATE_INPUT,
        _route_after_validation,
        {
            ROUTE_SEARCH: NODE_SEARCH_HOTELS,
            ROUTE_FORMAT: NODE_FORMAT_RESPONSE,
        },
    )

    builder.add_edge(NODE_SEARCH_HOTELS,   NODE_FORMAT_RESPONSE)
    builder.add_edge(NODE_FORMAT_RESPONSE, NODE_GENERATE_RESPONSE)
    builder.add_edge(NODE_GENERATE_RESPONSE, END)

    return builder.compile()


# Compiled graph singleton
hotel_graph = build_hotel_graph()
