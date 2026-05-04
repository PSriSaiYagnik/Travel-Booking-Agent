from enum import Enum

class GuardrailDecision(str, Enum):
    ALLOW = "ALLOW"
    SOFT_ALLOW = "SOFT_ALLOW"
    BLOCK = "BLOCK"
