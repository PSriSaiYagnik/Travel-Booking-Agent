# =============================================================================
# Hotel Agent — Node Name Constants
#
# Use these constants everywhere instead of raw strings.
# Benefit: a typo here is a NameError at import time, not a silent runtime bug.
# =============================================================================

NODE_EXTRACT_PARAMS    = "extract_params"
NODE_VALIDATE_INPUT    = "validate_input"
NODE_SEARCH_HOTELS     = "search_hotels"
NODE_FORMAT_RESPONSE   = "format_response"
NODE_GENERATE_RESPONSE = "generate_response"

# Edge routing values (returned by conditional edge functions)
ROUTE_SEARCH           = "search_hotels"
ROUTE_FORMAT           = "format_response"
