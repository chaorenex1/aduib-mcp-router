from typing import Any



class AduibAIApp:
    from aduib_mcp_router.mcp_router.router_manager import RouterManager
    from fast_mcp import FastMCP
    app_home: str = "."
    router_home: str = ""
    mcp: FastMCP= None
    router_manager: RouterManager = None
    config = None
    extensions: dict[str, Any] = {}
    pass