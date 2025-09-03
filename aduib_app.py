from typing import Any

from fastapi import FastAPI

from fast_mcp import FastMCP


class AduibAIApp(FastAPI):
    app_home: str = "."
    mcp: FastMCP= None
    config = None
    extensions: dict[str, Any] = {}
    pass