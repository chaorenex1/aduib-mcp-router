from typing import Any



class AduibAIApp:
    from fast_mcp import FastMCP
    app_home: str = "."
    router_home: str = ""
    mcp: FastMCP= None
    config = None
    extensions: dict[str, Any] = {}
    pass