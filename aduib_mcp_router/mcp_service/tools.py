import logging
from typing import Any

from aduib_mcp_router.app import app

logger=logging.getLogger(__name__)

mcp= app.mcp
router_manager= app.router_manager


@mcp.tool()
def search_tool(query: str) -> dict[str, Any]:
    """search Tools from VectorDB."""
    logger.debug(f"search_tool called with query: {query}")
    query_result = router_manager.ChromaDb.query(router_manager.tools_collection, query, 10)
    metadatas = query_result.get("metadatas")
    metadata_list = metadatas[0] if metadatas else []
    if not metadata_list:
        logger.debug("No metadata found in search_tool result.")
        return query_result

    metadata=metadata_list[0] # Just take the top result for simplicity
    server_id = metadata.get("server_id")
    mcp_server_info = router_manager.get_mcp_server(server_id)
    original_tool_name = metadata.get("original_name")
    tool_info = router_manager.get_tool(original_tool_name, server_id)

    return {"server_info": mcp_server_info, "tool_info": tool_info}


@mcp.tool()
async def call_tool(tool_name:str):
    """Call a tool by its name."""
    logger.debug(f"call_tool called with tool_name: {tool_name}")
    query_result = router_manager.ChromaDb.query(router_manager.tools_collection, tool_name, 10)
    metadatas = query_result.get("metadatas")
    metadata_list = metadatas[0] if metadatas else []
    if not metadata_list:
        logger.debug("No metadata found in search_tool result.")
        return query_result

    results=[]
    for metadata in metadatas if metadatas else []:
        server_id = metadata.get("server_id")
        original_tool_name = metadata.get("original_name")
        tool_info = router_manager.get_tool(original_tool_name, server_id)
        results.append(router_manager.call_tool(original_tool_name, tool_info.inputSchema))
    return results