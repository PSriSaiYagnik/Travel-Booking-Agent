from typing import TypedDict


class BaseAgentState(TypedDict):
    """
    Shared state for all sub-agents (Flight and Hotel).

    Sub-agent StateGraphs are short-lived — they exist only for the duration
    of a single A2A task. They do NOT hold conversation history; that lives
    in the OrchestratorState.

    Fields:
        task_id:           Unique ID from the A2A TaskRequest (UUID).
        parameters:        Raw parameters dict from the A2A request.
                           e.g. {"origin": "SIN", "destination": "BLR", ...}
        validation_errors: List of missing or invalid fields found by the
                           validate_input node. Empty means all good.
        raw_api_data:      Raw list returned by the service layer
                           (flight_service / hotel_service). Stored before
                           formatting so formatting node doesn't re-call API.
        formatted_results: Final cleaned list ready to be placed in the
                           A2ATaskResponse 'results' field.
        status:            Final task outcome, matches A2ATaskResponse status.
                           One of: "success" | "partial" | "failed" |
                                   "needs_clarification"
        raw_messages:      The raw conversation history passed from the Orchestrator.
        agent_message:     The generated text response to display to the user.
    """
    task_id:           str
    parameters:        dict
    validation_errors: list[str]
    raw_api_data:      list[dict]
    formatted_results: list[dict]
    status:            str
    raw_messages:      list[dict]
    agent_message:     str | None
