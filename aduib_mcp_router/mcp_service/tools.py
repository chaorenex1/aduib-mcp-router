import logging
from typing import Any

from aduib_mcp_router.app import app

logger=logging.getLogger(__name__)

mcp= app.mcp
router_manager= app.router_manager


@mcp.tool()
async def search_tool(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search available tools using the vector database."""
    logger.debug("search_tool called with query=%s limit=%s", query, limit)
    results = await router_manager.search_tools(query, limit)
    return results

@mcp.tool()
async def list_tools() -> list[dict[str, Any]]:
    """List all available tools."""
    logger.debug("list_tools called")
    results = await router_manager.list_tool_names()
    return results


@mcp.tool()
async def search_tool_prompts(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search stored prompt templates that describe how to use tools."""
    logger.debug("search_tool_prompts called with query=%s limit=%s", query, limit)
    results = await router_manager.search_prompts(query, limit)
    return results


@mcp.tool()
async def call_tool(tool_name: str, arguments: dict[str, Any]) -> list[Any]:
    """Call a routed tool by its name with the provided arguments."""
    logger.debug("call_tool called with tool_name=%s", tool_name)
    return await router_manager.call_tool(tool_name, arguments)


@mcp.tool()
async def search_resources(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search available resources using the vector database."""
    logger.debug("search_resources called with query=%s limit=%s", query, limit)
    results = await router_manager.search_resources(query, limit)
    return results


@mcp.tool()
async def read_remote_resource(server_id: str, uri: str):
    """Read a resource from a remote MCP server."""
    logger.debug("read_remote_resource called with server_id=%s uri=%s", server_id, uri)
    return await router_manager.read_resource(server_id, uri)


# ==================== Server Lifecycle Control Tools ====================

@mcp.tool()
async def list_mcp_servers() -> list[dict[str, Any]]:
    """List all configured MCP servers with their current status.

    Returns a list of server information including:
    - server_id: Unique identifier
    - server_name: Display name
    - server_type: Connection type (stdio, sse, streamableHttp)
    - is_running: Whether the server is currently running
    - health_status: Current health status (healthy, degraded, unhealthy, disconnected)
    """
    logger.debug("list_mcp_servers called")
    return router_manager.list_servers()


@mcp.tool()
async def start_mcp_server(server_id: str = None, server_name: str = None) -> dict[str, Any]:
    """Start a specific MCP server.

    Provide either server_id or server_name to identify the server.
    If the server is already running, returns current status.

    Args:
        server_id: The unique server ID (optional if server_name provided)
        server_name: The server name (optional if server_id provided)

    Returns:
        Dict with success status, server info, and message
    """
    logger.debug("start_mcp_server called with server_id=%s server_name=%s", server_id, server_name)

    # Resolve server_id from name if needed
    if not server_id and server_name:
        server_id = router_manager.get_server_id_by_name(server_name)
        if not server_id:
            return {
                "success": False,
                "server_id": None,
                "server_name": server_name,
                "status": "not_found",
                "message": f"Server with name '{server_name}' not found"
            }

    if not server_id:
        return {
            "success": False,
            "message": "Either server_id or server_name must be provided"
        }

    return await router_manager.start_server(server_id)


@mcp.tool()
async def stop_mcp_server(server_id: str = None, server_name: str = None) -> dict[str, Any]:
    """Stop a specific MCP server.

    Provide either server_id or server_name to identify the server.
    The server configuration is preserved and can be started again.

    Args:
        server_id: The unique server ID (optional if server_name provided)
        server_name: The server name (optional if server_id provided)

    Returns:
        Dict with success status, server info, and message
    """
    logger.debug("stop_mcp_server called with server_id=%s server_name=%s", server_id, server_name)

    # Resolve server_id from name if needed
    if not server_id and server_name:
        server_id = router_manager.get_server_id_by_name(server_name)
        if not server_id:
            return {
                "success": False,
                "server_id": None,
                "server_name": server_name,
                "status": "not_found",
                "message": f"Server with name '{server_name}' not found"
            }

    if not server_id:
        return {
            "success": False,
            "message": "Either server_id or server_name must be provided"
        }

    return await router_manager.stop_server(server_id)


@mcp.tool()
async def restart_mcp_server(server_id: str = None, server_name: str = None) -> dict[str, Any]:
    """Restart a specific MCP server.

    Provide either server_id or server_name to identify the server.
    This stops the server and starts it again.

    Args:
        server_id: The unique server ID (optional if server_name provided)
        server_name: The server name (optional if server_id provided)

    Returns:
        Dict with success status, server info, and message
    """
    logger.debug("restart_mcp_server called with server_id=%s server_name=%s", server_id, server_name)

    # Resolve server_id from name if needed
    if not server_id and server_name:
        server_id = router_manager.get_server_id_by_name(server_name)
        if not server_id:
            return {
                "success": False,
                "server_id": None,
                "server_name": server_name,
                "status": "not_found",
                "message": f"Server with name '{server_name}' not found"
            }

    if not server_id:
        return {
            "success": False,
            "message": "Either server_id or server_name must be provided"
        }

    return await router_manager.restart_server(server_id)


@mcp.tool()
async def get_mcp_server_info(server_id: str = None, server_name: str = None) -> dict[str, Any]:
    """Get detailed information about a specific MCP server.

    Provide either server_id or server_name to identify the server.

    Args:
        server_id: The unique server ID (optional if server_name provided)
        server_name: The server name (optional if server_id provided)

    Returns:
        Dict with server details including type, status, health info, etc.
    """
    logger.debug("get_mcp_server_info called with server_id=%s server_name=%s", server_id, server_name)

    # Resolve server_id from name if needed
    if not server_id and server_name:
        server_id = router_manager.get_server_id_by_name(server_name)
        if not server_id:
            return {"error": f"Server with name '{server_name}' not found"}

    if not server_id:
        return {"error": "Either server_id or server_name must be provided"}

    info = router_manager.get_server_info(server_id)
    if info is None:
        return {"error": f"Server with ID '{server_id}' not found"}

    return info
