from fastapi import APIRouter
from app.a2a.schemas import JsonRpcRequest, JsonRpcResponse, JsonRpcError
from app.a2a.server.executor import execute_task

router = APIRouter()


@router.post("/rpc", response_model=JsonRpcResponse)
async def rpc_endpoint(request: JsonRpcRequest) -> JsonRpcResponse:
    """
    JSON-RPC 2.0 endpoint mounted on every sub-agent service.

    All A2A communication from the Orchestrator lands here.
    The router validates the envelope, delegates to executor.py,
    and wraps the result back into a JSON-RPC response.

    On success:  { "jsonrpc": "2.0", "result": { A2ATaskResponse }, "id": "..." }
    On failure:  { "jsonrpc": "2.0", "error": { "code": ..., "message": ... }, "id": "..." }
    """
    try:
        result = await execute_task(request.params)
        return JsonRpcResponse(result=result, id=request.id)

    except Exception as e:
        return JsonRpcResponse(
            error=JsonRpcError(
                code=-32000,           # JSON-RPC spec: -32000 to -32099 = server errors
                message=str(e),
            ),
            id=request.id,
        )
