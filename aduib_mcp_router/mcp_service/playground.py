from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from starlette.responses import FileResponse, JSONResponse

from aduib_mcp_router.app import app
from aduib_mcp_router.mcp_router.types import ClientHealthStatus

mcp = app.mcp
router_manager = app.router_manager

# Static files directory
STATIC_DIR = Path(__file__).parent / "static" / "playground"


def _to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]

    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _to_jsonable(dump())

    as_dict = getattr(value, "dict", None)
    if callable(as_dict):
        try:
            return _to_jsonable(as_dict())
        except TypeError:
            pass

    if hasattr(value, "__dict__"):
        return _to_jsonable({k: v for k, v in value.__dict__.items() if not k.startswith("_")})

    return str(value)


def _get_server_health(server_id: str) -> dict[str, Any]:
    """Get health information for a server."""
    health_info = router_manager.get_client_health_info(server_id)
    if health_info:
        return {
            "server_id": health_info.server_id,
            "server_name": health_info.server_name,
            "status": health_info.status.value if health_info.status else "disconnected",
            "last_ping_time": health_info.last_ping_time.isoformat() if health_info.last_ping_time else None,
            "last_success_time": health_info.last_success_time.isoformat() if health_info.last_success_time else None,
            "last_error": health_info.last_error,
            "consecutive_failures": health_info.consecutive_failures,
            "total_requests": health_info.total_requests,
            "total_failures": health_info.total_failures,
            "latency_ms": health_info.latency_ms,
            "uptime_seconds": health_info.uptime_seconds,
        }

    # Fallback for clients not initialized
    client = router_manager._mcp_client_cache.get(server_id)
    if client:
        initialized = client.is_initialized()
        return {
            "server_id": server_id,
            "status": "healthy" if initialized else "disconnected",
            "initialized": initialized,
        }

    return {
        "server_id": server_id,
        "status": "disconnected",
        "initialized": False,
    }


async def _ensure_all_loaded() -> None:
    await router_manager.list_tools()
    await router_manager.list_resources()
    await router_manager.list_prompts()


# Static file routes
@mcp.custom_route("/playground", methods=["GET"])
async def playground_page(request):
    """Return the HTML page."""
    html_path = STATIC_DIR / "playground.html"
    if html_path.exists():
        return FileResponse(html_path, media_type="text/html", headers={"Cache-Control": "no-store, max-age=0"})
    return JSONResponse({"error": "playground.html not found"}, status_code=404)


@mcp.custom_route("/playground/playground.css", methods=["GET"])
async def playground_css(request):
    """Return the CSS file."""
    css_path = STATIC_DIR / "playground.css"
    if css_path.exists():
        return FileResponse(css_path, media_type="text/css", headers={"Cache-Control": "public, max-age=3600"})
    return JSONResponse({"error": "playground.css not found"}, status_code=404)


@mcp.custom_route("/playground/playground.js", methods=["GET"])
async def playground_js(request):
    """Return the JavaScript file."""
    js_path = STATIC_DIR / "playground.js"
    if js_path.exists():
        return FileResponse(js_path, media_type="application/javascript", headers={"Cache-Control": "public, max-age=3600"})
    return JSONResponse({"error": "playground.js not found"}, status_code=404)


# API endpoints
@mcp.custom_route("/playground/data", methods=["GET"])
async def playground_data(request):
    """Return JSON data with server status and health information."""
    await _ensure_all_loaded()

    servers_payload: list[dict[str, Any]] = []
    for server in router_manager._mcp_server_cache.values():
        args_dump = _to_jsonable(server.args) or {}
        servers_payload.append({
            "id": server.id,
            "name": server.name,
            "type": args_dump.get("type"),
            "details": (args_dump.get("command") or args_dump.get("url") or ""),
            "tool_count": len(router_manager._mcp_server_tools_cache.get(server.id, [])),
            "resource_count": len(router_manager._mcp_server_resources_cache.get(server.id, [])),
            "prompt_count": len(router_manager._mcp_server_prompts_cache.get(server.id, [])),
            "status": _get_server_health(server.id),
        })

    tools_payload: list[dict[str, Any]] = []
    for server_id, tool_list in router_manager._mcp_server_tools_cache.items():
        server = router_manager.get_mcp_server(server_id)
        for tool in tool_list or []:
            tools_payload.append({
                "name": getattr(tool, "name", None),
                "description": getattr(tool, "description", None),
                "inputSchema": _to_jsonable(getattr(tool, "inputSchema", None)),
                "annotations": _to_jsonable(getattr(tool, "annotations", None)),
                "server": {"id": server_id, "name": getattr(server, "name", None)},
            })

    resources_payload: list[dict[str, Any]] = []
    for server_id, resource_list in router_manager._mcp_server_resources_cache.items():
        server = router_manager.get_mcp_server(server_id)
        for resource in resource_list or []:
            resources_payload.append({
                "name": getattr(resource, "name", None),
                "uri": getattr(resource, "uri", None),
                "description": getattr(resource, "description", None),
                "mime_type": getattr(resource, "mimeType", None),
                "server": {"id": server_id, "name": getattr(server, "name", None)},
            })

    prompts_payload: list[dict[str, Any]] = []
    for server_id, prompt_list in router_manager._mcp_server_prompts_cache.items():
        server = router_manager.get_mcp_server(server_id)
        for prompt in prompt_list or []:
            prompts_payload.append({
                "name": getattr(prompt, "name", None),
                "description": getattr(prompt, "description", None),
                "arguments": _to_jsonable(getattr(prompt, "arguments", None)) or [],
                "server": {"id": server_id, "name": getattr(server, "name", None)},
            })

    return JSONResponse({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "servers": servers_payload,
        "tools": tools_payload,
        "resources": resources_payload,
        "prompts": prompts_payload,
    })


@mcp.custom_route("/playground/call-tool", methods=["POST"])
async def call_tool(request):
    """Execute a tool.

    Request body: {"tool_name": str, "arguments": dict}
    Response: {"success": bool, "result": any, "error": str|None}
    """
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse({"success": False, "result": None, "error": f"Invalid JSON body: {e}"}, status_code=400)

    tool_name = payload.get("tool_name")
    arguments = payload.get("arguments", {})

    if not isinstance(tool_name, str) or not tool_name.strip():
        return JSONResponse({"success": False, "result": None, "error": "tool_name must be a non-empty string"}, status_code=400)
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return JSONResponse({"success": False, "result": None, "error": "arguments must be an object"}, status_code=400)

    try:
        result = await router_manager.call_tool(tool_name, arguments)
        return JSONResponse({"success": True, "result": _to_jsonable(result), "error": None})
    except Exception as e:
        return JSONResponse({"success": False, "result": None, "error": str(e)}, status_code=500)


@mcp.custom_route("/playground/search", methods=["GET"])
async def search(request):
    """Unified search endpoint.

    Query params: q=query, type=tool|resource|prompt|all, limit=number
    Response: {"tools": [], "resources": [], "prompts": []}
    """
    q = (request.query_params.get("q") or "").strip()
    search_type = (request.query_params.get("type") or "all").strip().lower()
    limit_raw = request.query_params.get("limit") or "20"

    try:
        limit = max(1, min(100, int(limit_raw)))
    except ValueError:
        limit = 20

    if not q:
        return JSONResponse({"tools": [], "resources": [], "prompts": []})
    if search_type not in {"tool", "resource", "prompt", "all"}:
        return JSONResponse({"tools": [], "resources": [], "prompts": [], "error": "type must be tool|resource|prompt|all"}, status_code=400)

    tools_res: list[dict[str, Any]] = []
    resources_res: list[dict[str, Any]] = []
    prompts_res: list[dict[str, Any]] = []

    if search_type in {"tool", "all"}:
        results = await router_manager.search_tools(q, limit=limit)
        for r in results or []:
            tools_res.append({
                "name": r.get("tool_name"),
                "description": r.get("description"),
                "inputSchema": _to_jsonable(r.get("input_schema")),
                "annotations": _to_jsonable(r.get("annotations")),
                "score": r.get("score"),
                "server": {"id": r.get("server_id"), "name": r.get("server_name")},
            })

    if search_type in {"resource", "all"}:
        results = await router_manager.search_resources(q, limit=limit)
        for r in results or []:
            resources_res.append({
                "name": r.get("resource_name"),
                "description": r.get("description"),
                "uri": r.get("uri"),
                "mime_type": r.get("mime_type"),
                "score": r.get("score"),
                "server": {"id": r.get("server_id"), "name": r.get("server_name")},
            })

    if search_type in {"prompt", "all"}:
        results = await router_manager.search_prompts(q, limit=limit)
        for r in results or []:
            prompts_res.append({
                "name": r.get("prompt_name"),
                "description": r.get("description"),
                "arguments": _to_jsonable(r.get("arguments")) or [],
                "score": r.get("score"),
                "server": {"id": r.get("server_id"), "name": r.get("server_name")},
            })

    return JSONResponse({"tools": tools_res, "resources": resources_res, "prompts": prompts_res})


@mcp.custom_route("/playground/server-status", methods=["GET"])
async def server_status(request):
    """Server status endpoint (legacy).

    Response: {"servers": [{"id": str, "name": str, "initialized": bool, "error": str|None}]}
    """
    servers: list[dict[str, Any]] = []
    for server in router_manager._mcp_server_cache.values():
        health = _get_server_health(server.id)
        servers.append({
            "id": server.id,
            "name": server.name,
            "initialized": health.get("status") in ("healthy", "degraded"),
            "error": health.get("last_error"),
        })
    return JSONResponse({"servers": servers})


@mcp.custom_route("/playground/health-info", methods=["GET"])
async def health_info(request):
    """Get detailed health information for all servers.

    Response: {"servers": [ClientHealthInfo...]}
    """
    health_list = router_manager.get_all_clients_health_info()
    servers = []
    for info in health_list:
        servers.append({
            "server_id": info.server_id,
            "server_name": info.server_name,
            "status": info.status.value if info.status else "disconnected",
            "last_ping_time": info.last_ping_time.isoformat() if info.last_ping_time else None,
            "last_success_time": info.last_success_time.isoformat() if info.last_success_time else None,
            "last_error": info.last_error,
            "consecutive_failures": info.consecutive_failures,
            "total_requests": info.total_requests,
            "total_failures": info.total_failures,
            "latency_ms": info.latency_ms,
            "uptime_seconds": info.uptime_seconds,
        })
    return JSONResponse({"servers": servers})


@mcp.custom_route("/playground/force-reconnect", methods=["POST"])
async def force_reconnect(request):
    """Force reconnection for a specific server.

    Request body: {"server_id": str}
    Response: {"success": bool, "message": str}
    """
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse({"success": False, "message": f"Invalid JSON body: {e}"}, status_code=400)

    server_id = payload.get("server_id")
    if not isinstance(server_id, str) or not server_id.strip():
        return JSONResponse({"success": False, "message": "server_id must be a non-empty string"}, status_code=400)

    try:
        result = await router_manager.force_reconnect(server_id)
        if result:
            return JSONResponse({"success": True, "message": "Reconnection initiated"})
        else:
            return JSONResponse({"success": False, "message": "Server not found or client not initialized"}, status_code=404)
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


# ==================== Server Lifecycle Control API ====================

@mcp.custom_route("/playground/start-server", methods=["POST"])
async def start_server(request):
    """Start a specific MCP server.

    Request body: {"server_id": str} or {"server_name": str}
    Response: {"success": bool, "server_id": str, "server_name": str, "status": str, "message": str}
    """
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse({"success": False, "message": f"Invalid JSON body: {e}"}, status_code=400)

    server_id = payload.get("server_id")
    server_name = payload.get("server_name")

    # Support lookup by name if server_id not provided
    if not server_id and server_name:
        server_id = router_manager.get_server_id_by_name(server_name)
        if not server_id:
            return JSONResponse({
                "success": False,
                "server_id": None,
                "server_name": server_name,
                "status": "not_found",
                "message": f"Server with name '{server_name}' not found"
            }, status_code=404)

    if not isinstance(server_id, str) or not server_id.strip():
        return JSONResponse({
            "success": False,
            "message": "server_id or server_name must be provided"
        }, status_code=400)

    try:
        result = await router_manager.start_server(server_id)
        status_code = 200 if result.get("success") else 500
        if result.get("status") == "not_found":
            status_code = 404
        return JSONResponse(result, status_code=status_code)
    except Exception as e:
        return JSONResponse({
            "success": False,
            "server_id": server_id,
            "status": "error",
            "message": str(e)
        }, status_code=500)


@mcp.custom_route("/playground/stop-server", methods=["POST"])
async def stop_server(request):
    """Stop a specific MCP server.

    Request body: {"server_id": str} or {"server_name": str}
    Response: {"success": bool, "server_id": str, "server_name": str, "status": str, "message": str}
    """
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse({"success": False, "message": f"Invalid JSON body: {e}"}, status_code=400)

    server_id = payload.get("server_id")
    server_name = payload.get("server_name")

    # Support lookup by name if server_id not provided
    if not server_id and server_name:
        server_id = router_manager.get_server_id_by_name(server_name)
        if not server_id:
            return JSONResponse({
                "success": False,
                "server_id": None,
                "server_name": server_name,
                "status": "not_found",
                "message": f"Server with name '{server_name}' not found"
            }, status_code=404)

    if not isinstance(server_id, str) or not server_id.strip():
        return JSONResponse({
            "success": False,
            "message": "server_id or server_name must be provided"
        }, status_code=400)

    try:
        result = await router_manager.stop_server(server_id)
        status_code = 200 if result.get("success") else 500
        if result.get("status") == "not_found":
            status_code = 404
        return JSONResponse(result, status_code=status_code)
    except Exception as e:
        return JSONResponse({
            "success": False,
            "server_id": server_id,
            "status": "error",
            "message": str(e)
        }, status_code=500)


@mcp.custom_route("/playground/restart-server", methods=["POST"])
async def restart_server(request):
    """Restart a specific MCP server.

    Request body: {"server_id": str} or {"server_name": str}
    Response: {"success": bool, "server_id": str, "server_name": str, "status": str, "message": str}
    """
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse({"success": False, "message": f"Invalid JSON body: {e}"}, status_code=400)

    server_id = payload.get("server_id")
    server_name = payload.get("server_name")

    # Support lookup by name if server_id not provided
    if not server_id and server_name:
        server_id = router_manager.get_server_id_by_name(server_name)
        if not server_id:
            return JSONResponse({
                "success": False,
                "server_id": None,
                "server_name": server_name,
                "status": "not_found",
                "message": f"Server with name '{server_name}' not found"
            }, status_code=404)

    if not isinstance(server_id, str) or not server_id.strip():
        return JSONResponse({
            "success": False,
            "message": "server_id or server_name must be provided"
        }, status_code=400)

    try:
        result = await router_manager.restart_server(server_id)
        status_code = 200 if result.get("success") else 500
        if result.get("status") == "not_found":
            status_code = 404
        return JSONResponse(result, status_code=status_code)
    except Exception as e:
        return JSONResponse({
            "success": False,
            "server_id": server_id,
            "status": "error",
            "message": str(e)
        }, status_code=500)


@mcp.custom_route("/playground/server-info", methods=["GET"])
async def server_info(request):
    """Get detailed information about a specific server.

    Query params: server_id=str or server_name=str
    Response: Server information dict
    """
    server_id = request.query_params.get("server_id")
    server_name = request.query_params.get("server_name")

    # Support lookup by name if server_id not provided
    if not server_id and server_name:
        server_id = router_manager.get_server_id_by_name(server_name)
        if not server_id:
            return JSONResponse({
                "error": f"Server with name '{server_name}' not found"
            }, status_code=404)

    if not server_id:
        return JSONResponse({
            "error": "server_id or server_name query parameter is required"
        }, status_code=400)

    info = router_manager.get_server_info(server_id)
    if info is None:
        return JSONResponse({
            "error": f"Server with ID '{server_id}' not found"
        }, status_code=404)

    return JSONResponse(info)


@mcp.custom_route("/playground/list-servers", methods=["GET"])
async def list_servers(request):
    """List all configured servers with their current status.

    Response: {"servers": [server info...]}
    """
    servers = router_manager.list_servers()
    return JSONResponse({"servers": servers})
