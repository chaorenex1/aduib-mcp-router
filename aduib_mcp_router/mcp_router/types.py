from typing import Literal, Tuple, Any, Optional, Callable, Awaitable
from uuid import uuid4
from enum import Enum
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ClientHealthStatus(str, Enum):
    """Health status of an MCP client."""
    HEALTHY = "healthy"           # Client is responding normally
    DEGRADED = "degraded"         # Client has some failures but still operational
    UNHEALTHY = "unhealthy"       # Client is not responding, needs reconnection
    CONNECTING = "connecting"     # Client is in the process of connecting/reconnecting
    DISCONNECTED = "disconnected" # Client has been disconnected


class ClientHealthInfo(BaseModel):
    """Detailed health information for an MCP client."""
    model_config = ConfigDict(extra="allow")

    server_id: str
    server_name: str
    status: ClientHealthStatus = ClientHealthStatus.DISCONNECTED
    last_ping_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    total_requests: int = 0
    total_failures: int = 0
    latency_ms: Optional[float] = None  # Last ping latency in milliseconds
    uptime_seconds: Optional[float] = None  # Time since last healthy connection


# Type alias for health status change callback
HealthStatusCallback = Callable[[str, ClientHealthStatus, Optional[str]], Awaitable[None]]


class McpServerInfoArgs(BaseModel):
    """Information about the MCP server."""

    model_config = ConfigDict(extra="allow")
    command: str = None
    args: list[str]=[]
    env: dict[str,str]={}
    headers: dict[str,str]={}
    type: str=None
    url: str=None

class McpServerInfo(BaseModel):
    """Information about the MCP server."""

    model_config = ConfigDict(extra="allow")
    id: str=None
    name: str=None
    args: McpServerInfoArgs=None

class McpServers(BaseModel):
    """Information about the MCP servers."""

    model_config = ConfigDict(extra="allow")
    servers: list[McpServerInfo]=[]

class ShellEnv(BaseModel):
    """Environment variable for shell command."""

    model_config = ConfigDict(extra="allow")
    bin_path: str = None
    command_get_env: Literal['set','env'] = 'env'
    # command_run: Literal['cmd.exe','/bin/bash'] = '/bin/bash'
    command_run: str = '/bin/bash'
    args: list[str]=[]
    env: dict[str, str] = None



def _generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid4())


class RouteMessage(BaseModel):
    """Class representing a routed message with unique request ID for parallel processing."""
    request_id: str = Field(default_factory=_generate_request_id)
    function_name: str
    args: Tuple[Any, ...] = ()
    kwargs: dict[str, Any] = {}


class RouteMessageResult(BaseModel):
    """Class representing the result of a routed message."""
    request_id: str = ""
    function_name: str
    result: Any = None
    error: str | None = None