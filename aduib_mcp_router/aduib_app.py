from typing import Any

from fast_mcp import FastMCP


class AduibAIApp:
    app_home: str = "."
    router_home: str = ""
    mcp: FastMCP= None
    config = None
    extensions: dict[str, Any] = {}
    pass