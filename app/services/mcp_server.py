"""
MCP Travel Data Server
======================
This module is the MCP server that acts as a secure, isolated data-fetching
layer. It is spawned as a subprocess by the Flight/Hotel agent nodes via
stdio transport.
"""

import json
import sys
import logging
from mcp.server.fastmcp import FastMCP

from app.services.flight_service import search_flights as flight_api
from app.services.hotel_service import search_hotels as hotel_api

# Set up logging for the MCP server
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger("mcp_server")

# Create the MCP Server
mcp = FastMCP("Travel Data Server")

@mcp.tool()
def search_flights(parameters_json: str) -> str:
    """Search for flights via the external API."""
    print("==================================================", file=sys.stderr, flush=True)
    print(" [MCP SERVER] ️  MCP Server received flight search request!", file=sys.stderr, flush=True)
    print(f" [MCP SERVER]  Payload received: {parameters_json}", file=sys.stderr, flush=True)
    print(" [MCP SERVER]  Calling AeroDataBox RapidAPI...", file=sys.stderr, flush=True)
    try:
        params = json.loads(parameters_json)
        results = flight_api(params)
        print(f" [MCP SERVER]  Fetched {len(results)} flight(s) from API. Sending back over MCP pipe.", file=sys.stderr, flush=True)
        print("==================================================\n", file=sys.stderr, flush=True)
        return json.dumps(results)
    except Exception as e:
        logger.error(f"Error in search_flights: {e}")
        return json.dumps({"error": str(e)})

@mcp.tool()
def search_hotels(parameters_json: str) -> str:
    """Search for hotels via the external API."""
    print("==================================================", file=sys.stderr, flush=True)
    print(" [MCP SERVER] ️  MCP Server received hotel search request!", file=sys.stderr, flush=True)
    print(f" [MCP SERVER]  Payload received: {parameters_json}", file=sys.stderr, flush=True)
    print(" [MCP SERVER]  Calling Booking.com RapidAPI...", file=sys.stderr, flush=True)
    try:
        params = json.loads(parameters_json)
        results = hotel_api(params)
        print(f" [MCP SERVER]  Fetched {len(results)} hotel(s) from API. Sending back over MCP pipe.", file=sys.stderr, flush=True)
        print("==================================================\n", file=sys.stderr, flush=True)
        return json.dumps(results)
    except Exception as e:
        logger.error(f"Error in search_hotels: {e}")
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    mcp.run(transport="stdio")
