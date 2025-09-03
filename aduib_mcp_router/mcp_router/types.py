from typing import Literal

from pydantic import BaseModel, ConfigDict, AnyHttpUrl


class McpServerInfoArgs(BaseModel):
    """Information about the MCP server."""

    model_config = ConfigDict(extra="allow")
    command: Literal['npx','uvx'] = 'npx'
    args: list[str]=[]
    env: dict[str,str]={}
    headers: dict[str,str]={}
    type: Literal['streamableHttp','sse']='streamableHttp'
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
    uvx_path: str = None
    npx_path: str = None
    command_get_env: Literal['set','env'] = 'env'
    command_run: Literal['cmd.exe /c','/bin/bash -ilc'] = '/bin/bash -ilc'