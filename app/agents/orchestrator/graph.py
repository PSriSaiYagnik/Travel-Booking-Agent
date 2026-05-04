from langgraph.graph import StateGraph, START, END

from app.agents.orchestrator.state import OrchestratorState
from app.agents.orchestrator.nodes import (
    guardrail_node,
    reject_response_node,
    intent_classifier_node,
    dispatch_to_agent_node,
    confirm_booking_node,
    direct_answer_node,
)
from app.agents.orchestrator.constants import (
    NODE_GUARDRAIL,
    NODE_REJECT_RESPONSE,
    NODE_INTENT_CLASSIFIER,
    NODE_DISPATCH_TO_AGENT,
    NODE_CONFIRM_BOOKING,
    NODE_DIRECT_ANSWER,
    ROUTE_DISPATCH,
    ROUTE_CONFIRM,
    ROUTE_DIRECT,
    ROUTE_INTENT,
    ROUTE_REJECT
)


# =============================================================================
# Conditional Edge Functions
# =============================================================================

def _route_after_guardrail(state: OrchestratorState) -> str:
    decision = state.get("guardrail_decision", "SOFT_ALLOW")
    if decision == "BLOCK":
        return ROUTE_REJECT
    return ROUTE_INTENT

def _route_after_intent_classifier(state: OrchestratorState) -> str:
    """
    First routing decision — based on intent set by intent_classifier_node.

    off_topic / general  → direct_answer (no agents needed)
    confirmation         → confirm_booking (user said yes)
    hotel_only / mc_     → call_hotel_agent
    everything else      → call_flight_agent
    """
    intent = state["intent"]

    if intent in ["no_agents", "unsupported_service"]:
        return END

    if intent == "confirmation":
        if state.get("booking_status") == "awaiting_confirmation":
            return ROUTE_CONFIRM
        else:
            return ROUTE_DIRECT

    if intent in ["off_topic", "general"]:
        return ROUTE_DIRECT

    # If it's not a generic action, it's an agent_id to dispatch to
    return ROUTE_DISPATCH


# =============================================================================
# Graph Definition
# =============================================================================

def build_orchestrator_graph(checkpointer=None) -> StateGraph:
    """
    Build and compile the Orchestrator LangGraph StateGraph.

    Full flow:

    START
      └─► intent_classifier
            ├─► off_topic/general ──────────────► direct_answer ──► END
            ├─► confirmation ───────────────────► confirm_booking ──► END
            ├─► flight_only/both/clarification ─► call_flight_agent ──► END
            └─► hotel_only ─────────────────────► call_hotel_agent ──► END
    """
    builder = StateGraph(OrchestratorState)

    # ── Register all nodes ────────────────────────────────────────────────────
    builder.add_node(NODE_GUARDRAIL,          guardrail_node)
    builder.add_node(NODE_REJECT_RESPONSE,    reject_response_node)
    builder.add_node(NODE_INTENT_CLASSIFIER,  intent_classifier_node)
    builder.add_node(NODE_DISPATCH_TO_AGENT,  dispatch_to_agent_node)
    builder.add_node(NODE_CONFIRM_BOOKING,    confirm_booking_node)
    builder.add_node(NODE_DIRECT_ANSWER,      direct_answer_node)

    # ── Entry ─────────────────────────────────────────────────────────────────
    builder.add_edge(START, NODE_GUARDRAIL)

    # ── After guardrail ───────────────────────────────────────────────────────
    builder.add_conditional_edges(
        NODE_GUARDRAIL,
        _route_after_guardrail,
        {
            ROUTE_INTENT: NODE_INTENT_CLASSIFIER,
            ROUTE_REJECT: NODE_REJECT_RESPONSE,
        }
    )

    # ── After intent_classifier ───────────────────────────────────────────────
    builder.add_conditional_edges(
        NODE_INTENT_CLASSIFIER,
        _route_after_intent_classifier,
        {
            ROUTE_DIRECT:   NODE_DIRECT_ANSWER,
            ROUTE_CONFIRM:  NODE_CONFIRM_BOOKING,
            ROUTE_DISPATCH: NODE_DISPATCH_TO_AGENT,
            END:            END,
        },
    )

    # ── Linear tail edges ─────────────────────────────────────────────────────
    builder.add_edge(NODE_DISPATCH_TO_AGENT, END)
    builder.add_edge(NODE_CONFIRM_BOOKING,   END)
    builder.add_edge(NODE_DIRECT_ANSWER,     END)
    builder.add_edge(NODE_REJECT_RESPONSE,   END)

    return builder.compile(checkpointer=checkpointer)
