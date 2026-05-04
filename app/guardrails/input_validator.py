import json
from app.core.llm import llm
from app.guardrails.prompts import GUARDRAIL_PROMPT
from app.guardrails.types import GuardrailDecision

def evaluate_guardrail(user_message: str, booking_status: str) -> GuardrailDecision:
    prompt = GUARDRAIL_PROMPT.format(user_input=user_message)
    response = llm.invoke(prompt)
    raw = response.content.strip()
    
    # Strip markdown if any
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:-1]).strip()
        
    try:
        data = json.loads(raw)
        decision_str = data.get("decision", "SOFT_ALLOW").upper()
    except Exception:
        decision_str = "SOFT_ALLOW"
        
    # State-aware override: If we are midway through a booking, relax the blocking
    if booking_status != "idle" and decision_str == GuardrailDecision.BLOCK.value:
        decision_str = GuardrailDecision.SOFT_ALLOW.value
        
    try:
        return GuardrailDecision(decision_str)
    except ValueError:
        return GuardrailDecision.SOFT_ALLOW
