from typing import Literal

from pydantic import BaseModel, ConfigDict, AnyHttpUrl


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
    command_run: Literal['cmd.exe','/bin/bash'] = '/bin/bash'
    args: list[str]=[]
    env: dict[str, str] = None