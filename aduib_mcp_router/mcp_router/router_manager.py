import asyncio
import json
import logging
import os
import secrets
import sys
import traceback
from pathlib import Path

import requests

from aduib_mcp_router.aduib_app import AduibAIApp
from aduib_mcp_router.configs import config
from aduib_mcp_router.mcp_router.install_bun import install_bun
from aduib_mcp_router.mcp_router.install_uv import install_uv
from aduib_mcp_router.mcp_router.mcp_client import McpClient
from aduib_mcp_router.mcp_router.types import McpServers, McpServerInfo, McpServerInfoArgs, ShellEnv

logger=logging.getLogger(__name__)

_mcp_server_store:dict[str, McpServerInfo] = {}
_mcp_client_store:dict[str, McpClient] = {}

class RouterManager:
    """Factory class for initializing router configurations and directories."""
    @classmethod
    def init_router_home(cls,app:AduibAIApp):
        """Initialize the router home directory."""
        if not config.ROUTER_HOME:
            user_home = os.environ.get('user.home', os.path.expanduser('~'))
            app.router_home = os.path.join(user_home, ".aduib_router")
            if not os.path.exists(app.router_home):
                os.makedirs(app.router_home, exist_ok=True)
        else:
            try:
                path= Path(config.ROUTER_HOME)
                if not path.exists():
                    path.mkdir(parents=True, exist_ok=True)
                app.router_home = str(path.resolve())
            except FileNotFoundError:
                logger.error("Router home directory not found.")
                raise FileNotFoundError(f"Router home directory {config.ROUTER_HOME} does not exist and could not be created.")
            except Exception as e:
                logger.error(f"Error creating router home directory: {e}")
                raise Exception(f"Error creating router home directory {config.ROUTER_HOME}: {e}")
        config.ROUTER_HOME=app.router_home
        logger.info(f"Router home directory set to: {app.router_home}")


    @classmethod
    def init_mcp_configs(cls,app:AduibAIApp):
        """Initialize MCP configurations."""
        #1. check mcp config whether it is existing
        try:
            mcp_router_json = os.path.join(app.router_home, "mcp_router.json")
            # http url
            if config.MCP_CONFIG_URL.startswith("http://") or config.MCP_CONFIG_URL.startswith("https://"):
                response = requests.get(url=config.MCP_CONFIG_URL, headers={"User-Agent": config.DEFAULT_USER_AGENT})
                if response.status_code == 200:
                    cls.resolve_mcp_configs(mcp_router_json, response.text)
            else:
                if not os.path.exists(config.MCP_CONFIG_URL):
                    logger.error("MCP configuration file not found.")
                    raise FileNotFoundError(f"MCP configuration file {config.MCP_CONFIG_URL} does not exist.")
                with open(config.MCP_CONFIG_URL, "rt",encoding="utf-8") as f:
                    cls.resolve_mcp_configs(mcp_router_json, f.read())
        except Exception as e:
            logger.error(f"Error accessing MCP configuration file: {config.MCP_CONFIG_URL}: {e}")
            raise e

    @classmethod
    def resolve_mcp_configs(cls, mcp_router_json: str, source: str)-> McpServers:
        """Resolve MCP configurations from the given source."""
        mcp_servers_dict = json.loads(source)
        for name, args in mcp_servers_dict.items():
            logger.info(f"Resolving MCP configuration for {name}, args: {args}")
            mcp_server_args = McpServerInfoArgs.model_validate(args)
            if not mcp_server_args.type:
                mcp_server_args.type='stdio'

            mcp_server = McpServerInfo(id=secrets.token_urlsafe(16), name=name, args=mcp_server_args)
            _mcp_server_store[mcp_server.name] = mcp_server
        mcp_servers = McpServers(servers=list(_mcp_server_store.values()))
        # save to local file
        with open(mcp_router_json, "wt") as f:
            f.write(mcp_servers.model_dump_json(indent=2))
        logger.info(f"MCP config file set to: {mcp_router_json}")
        return mcp_servers

    @classmethod
    def check_bin_exists(cls, binary_name: str) -> bool:
        """Check if the specified binary exists."""
        binary_path = cls.get_binary(binary_name)
        return os.path.exists(binary_path) and os.access(binary_path, os.X_OK)

    @classmethod
    def get_shell_env(cls,args:McpServerInfoArgs)-> ShellEnv:
        """Get shell environment variables."""
        shell_env = ShellEnv()
        args_list = []
        if sys.platform == 'win32':
            shell_env.command_get_env='set'
            shell_env.command_run='cmd.exe'
            args_list.append('/c')
        else:
            shell_env.command_get_env='env'
            shell_env.command_run='/bin/bash'
            args_list.append('-ilc')
        if args.command and args.command=='npx':
            shell_env.bin_path=cls.get_binary('bun')
            args_list.append(shell_env.bin_path)
            for i, arg in enumerate(args.args):
                if arg == '-y' or arg == '--yes':
                    args_list.append('x')
                else:
                    args_list.append(arg)
        if args.command and (args.command=='uvx' or args.command=='uv'):
            shell_env.bin_path=cls.get_binary('uvx')
            args_list.append(shell_env.bin_path)
            for i, arg in enumerate(args.args):
                args_list.append(arg)
        shell_env.args = args_list
        shell_env.env = args.env
        return shell_env

    @classmethod
    def get_binary(cls, binary_name: str) -> str:
        """Get the path to the specified binary."""
        if sys.platform == "win32":
            binary_name = f"{binary_name}.exe"

        return os.path.join(config.ROUTER_HOME, "bin", binary_name)

    @classmethod
    async def init_mcp_clients(cls, app: AduibAIApp):
        """Initialize MCP clients based on the loaded configurations."""
        tasks = []
        for mcp_server in _mcp_server_store.values():
            client = McpClient(mcp_server)
            _mcp_client_store[mcp_server.id] = client
            task = asyncio.create_task(cls._run_client(client))
            tasks.append(task)
            logger.info(f"MCP client '{mcp_server.name}' type '{client.client_type}' initialized.")

        await asyncio.gather(*tasks, return_exceptions=True)

    @classmethod
    async def _run_client(cls, client: McpClient):
        """run MCP client."""
        try:
           async with client:
                # maintain the client running
                logger.info(f"Client {client.server.name} started successfully")
                await client.process_messages()
        except Exception as e:
            traceback.print_exc()
            logger.error(f"Client {client.server.name} failed: {e}")


    @classmethod
    def init_router_env(cls,app:AduibAIApp):
        """Initialize the router environment."""
        cls.init_router_home(app)
        if not cls.check_bin_exists('bun'):
            ret_code = install_bun()
            if ret_code != 0:
                raise EnvironmentError("Failed to install 'bun' binary.")
        if not cls.check_bin_exists('uvx'):
            ret_code = install_uv()
            if ret_code != 0:
                raise EnvironmentError("Failed to install 'uvx' binary.")
        cls.init_mcp_configs(app)
