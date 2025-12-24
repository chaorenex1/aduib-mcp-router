import logging
from typing import Any

from aduib_mcp_router.app import app

logger=logging.getLogger(__name__)

mcp= app.mcp
router_manager= app.router_manager


@mcp.tool()
async def search_tool(query: str, limit: int = 5) -> dict[str, Any]:
    """Search available tools using the vector database."""
    logger.debug("search_tool called with query=%s limit=%s", query, limit)
    results = await router_manager.search_tools(query, limit)
    return {"query": query, "results": results}


@mcp.tool()
async def search_tool_prompts(query: str, limit: int = 5) -> dict[str, Any]:
    """Search stored prompt templates that describe how to use tools."""
    logger.debug("search_tool_prompts called with query=%s limit=%s", query, limit)
    results = await router_manager.search_prompts(query, limit)
    return {"query": query, "results": results}


@mcp.tool()
async def call_tool(tool_name: str, arguments: dict[str, Any]) -> list[Any]:
    """Call a routed tool by its name with the provided arguments."""
    logger.debug("call_tool called with tool_name=%s", tool_name)
    return await router_manager.call_tool(tool_name, arguments)


@mcp.tool()
async def search_resources(query: str, limit: int = 5) -> dict[str, Any]:
    """Search available resources using the vector database."""
    logger.debug("search_resources called with query=%s limit=%s", query, limit)
    results = await router_manager.search_resources(query, limit)
    return {"query": query, "results": results}


@mcp.tool()
async def read_remote_resource(server_id: str, uri: str):
    """Read a resource from a remote MCP server."""
    logger.debug("read_remote_resource called with server_id=%s uri=%s", server_id, uri)
    return await router_manager.read_resource(server_id, uri)
