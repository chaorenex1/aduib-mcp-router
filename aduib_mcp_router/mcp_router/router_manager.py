import asyncio
import functools
import inspect
import json
import logging
import os
import secrets
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, cast

import requests

from aduib_mcp_router.configs import config
from aduib_mcp_router.mcp_router.chromadb import ChromaDB
from aduib_mcp_router.mcp_router.install_bun import install_bun
from aduib_mcp_router.mcp_router.install_uv import install_uv
from aduib_mcp_router.mcp_router.mcp_client import McpClient
from aduib_mcp_router.mcp_router.types import McpServers, McpServerInfo, McpServerInfoArgs, ShellEnv, RouteMessage, \
    RouteMessageResult
from aduib_mcp_router.aduib_app import AduibAIApp

logger = logging.getLogger(__name__)


class RouterManager:
    """Factory class for initializing router configurations and directories."""

    def __init__(self, app: AduibAIApp):

        self._mcp_server_cache: dict[str, McpServerInfo] = {}
        self._mcp_client_cache: dict[str, McpClient] = {}
        self._mcp_server_tools_cache: dict[str, list[Any]] = {}
        self._mcp_server_resources_cache: dict[str, list[Any]] = {}
        self._mcp_server_prompts_cache: dict[str, list[Any]] = {}


        self.app = app
        self.route_home = self.init_router_home(app)
        if not self.check_bin_exists('bun'):
            ret_code = install_bun()
            if ret_code != 0:
                raise EnvironmentError("Failed to install 'bun' binary.")
        if not self.check_bin_exists('uvx'):
            ret_code = install_uv()
            if ret_code != 0:
                raise EnvironmentError("Failed to install 'uvx' binary.")
        self.init_mcp_configs(router_home=self.route_home)

        self.ChromaDb = ChromaDB(app.router_home)
        self.tools_collection = self.ChromaDb.create_collection(collection_name="tools")
        self.prompts_collection = self.ChromaDb.create_collection(collection_name="prompts")
        self.resources_collection = self.ChromaDb.create_collection(collection_name="resources")

    @classmethod
    def get_router_manager(cls, app: AduibAIApp):
        """Get the RouterManager instance from the app context."""
        return cls(app)

    def init_router_home(self, app: AduibAIApp) -> str:
        """Initialize the router home directory."""
        router_home: str = ""
        if not config.ROUTER_HOME:
            user_home = os.environ.get('user.home', os.path.expanduser('~'))
            router_home = os.path.join(user_home, ".aduib_router")
            if not os.path.exists(router_home):
                os.makedirs(router_home, exist_ok=True)
        else:
            try:
                path = Path(config.ROUTER_HOME)
                if not path.exists():
                    path.mkdir(parents=True, exist_ok=True)
                router_home = str(path.resolve())
            except FileNotFoundError:
                logger.error("Router home directory not found.")
                raise FileNotFoundError(
                    f"Router home directory {config.ROUTER_HOME} does not exist and could not be created.")
            except Exception as e:
                logger.error(f"Error creating router home directory: {e}")
                raise Exception(f"Error creating router home directory {config.ROUTER_HOME}: {e}")
        logger.info(f"Router home directory set to: {router_home}")
        app.router_home = router_home
        config.ROUTER_HOME = router_home
        return router_home

    def init_mcp_configs(self, router_home: str):
        """Initialize MCP configurations."""
        # 1. check mcp config whether it is existing
        try:
            mcp_router_json = os.path.join(router_home, "mcp_router.json")
            # http url
            if config.MCP_CONFIG_URL.startswith("http://") or config.MCP_CONFIG_URL.startswith("https://"):
                response = requests.get(url=config.MCP_CONFIG_URL, headers={"User-Agent": config.DEFAULT_USER_AGENT})
                if response.status_code == 200:
                    self.resolve_mcp_configs(mcp_router_json, response.text)
            else:
                if not os.path.exists(config.MCP_CONFIG_URL):
                    logger.error("MCP configuration file not found.")
                    raise FileNotFoundError(f"MCP configuration file {config.MCP_CONFIG_URL} does not exist.")
                with open(config.MCP_CONFIG_URL, "rt", encoding="utf-8") as f:
                    self.resolve_mcp_configs(mcp_router_json, f.read())
        except Exception as e:
            logger.error(f"Error accessing MCP configuration file: {config.MCP_CONFIG_URL}: {e}")
            raise e

    def resolve_mcp_configs(self, mcp_router_json: str, source: str) -> McpServers:
        """Resolve MCP configurations from the given source."""
        mcp_servers_dict = json.loads(source)
        for name, args in mcp_servers_dict.items():
            logger.info(f"Resolving MCP configuration for {name}, args: {args}")
            mcp_server_args = McpServerInfoArgs.model_validate(args)
            if not mcp_server_args.type:
                mcp_server_args.type = 'stdio'

            mcp_server = McpServerInfo(id=secrets.token_urlsafe(16), name=name, args=mcp_server_args)
            self._mcp_server_cache[mcp_server.name] = mcp_server
        mcp_servers = McpServers(servers=list(self._mcp_server_cache.values()))
        # save to local file
        with open(mcp_router_json, "wt") as f:
            f.write(mcp_servers.model_dump_json(indent=2))
        logger.info(f"MCP config file set to: {mcp_router_json}")
        return mcp_servers

    def check_bin_exists(self, binary_name: str) -> bool:
        """Check if the specified binary exists."""
        binary_path = self.get_binary(binary_name)
        return os.path.exists(binary_path) and os.access(binary_path, os.X_OK)

    def get_shell_env(self, args: McpServerInfoArgs) -> ShellEnv:
        """Get shell environment variables."""
        shell_env = ShellEnv()
        args_list = []
        if sys.platform == 'win32':
            shell_env.command_get_env = 'set'
            shell_env.command_run = 'cmd.exe'
            args_list.append('/c')
        else:
            shell_env.command_get_env = 'env'
            shell_env.command_run = '/bin/bash'
            args_list.append('-ilc')
        if args.command and args.command == 'npx':
            shell_env.bin_path = self.get_binary('bun')
            args_list.append(shell_env.bin_path)
            for i, arg in enumerate(args.args):
                if arg == '-y' or arg == '--yes':
                    args_list.append('x')
                else:
                    args_list.append(arg)
        if args.command and (args.command == 'uvx' or args.command == 'uv'):
            shell_env.bin_path = self.get_binary('uvx')
            args_list.append(shell_env.bin_path)
            for i, arg in enumerate(args.args):
                args_list.append(arg)
        shell_env.args = args_list
        shell_env.env = args.env
        return shell_env

    def get_binary(self, binary_name: str) -> str:
        """Get the path to the specified binary."""
        if sys.platform == "win32":
            binary_name = f"{binary_name}.exe"

        return os.path.join(config.ROUTER_HOME, "bin", binary_name)

    async def init_mcp_clients(self, app: AduibAIApp):
        """Initialize MCP clients based on the loaded configurations."""
        for mcp_server in self._mcp_server_cache.values():
            client = McpClient(mcp_server)
            self._mcp_client_cache[mcp_server.id] = client
            logger.info(f"MCP client '{mcp_server.name}' type '{client.client_type}' initialized.")
        tasks = []
        i = 0
        for mcp_client in self._mcp_client_cache.values():
            tasks.append(self._run_client(mcp_client, i))
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_client(self, client: McpClient, index: int):
        """run MCP client."""
        try:
            async with client:
                await self._init_mcp_data(client)
                # maintain the client running
                index += 1
                last = index == len(self._mcp_server_cache)
                if last:
                    logger.info("All MCP clients have been processed.")
                    await self._register_to_discovery_service()
                await client.maintain_message_loop()
        except Exception as e:
            traceback.print_exc()
            logger.error(f"Client {client.server.name} failed: {e}")

    async def _init_mcp_data(self, client):
        await self.cache_mcp_features(client.server.id)
        await self.refresh(client.server.id)

    async def _register_to_discovery_service(self):
        """Register the router service to the discovery service."""
        if self.app.config.DISCOVERY_SERVICE_ENABLED:
            from aduib_mcp_router.nacos_mcp import NacosMCP
            await cast(NacosMCP, self.app.mcp).register_service(self.app.config.TRANSPORT_TYPE)

    async def _broadcast_message(self, message: RouteMessage):
        """Broadcast a message to all MCP clients."""
        tasks = []
        for mcp_client in self._mcp_client_cache.values():
            tasks.append(mcp_client.send_message(message))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_message_to_client(self, server_id: str, message: RouteMessage):
        """Send a message to a specific MCP client."""
        client = self._mcp_client_cache.get(server_id)
        if client:
            await client.send_message(message)

    async def _get_responses(self, timeout: float = 10.0) -> dict[str, RouteMessageResult]:
        """Get responses from all MCP clients within the specified timeout."""
        responses = {}
        tasks = []

        for server_id, client in self._mcp_client_cache.items():
            tasks.append(self._get_client_response(server_id, timeout))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for server_id, result in zip(self._mcp_client_cache.keys(), results):
            if not isinstance(result, Exception):
                responses[server_id] = result

        return responses

    async def _get_client_response(self, server_id: str,
                                   timeout: float = 10.0) -> Any | None:
        """Get response from a specific MCP client."""
        try:
            client = self._mcp_client_cache.get(server_id)
            if client:
                return await client.receive_message(timeout)
        except Exception as e:
            logger.error(f"Failed to get response from client {server_id}: {e}")
            return None

    async def cache_mcp_features(self, server_id: str = None):
        """List all tools from all MCP clients and cache them."""
        logger.debug("Listing and caching MCP features.")
        features = [self._mcp_server_tools_cache, self._mcp_server_resources_cache, self._mcp_server_prompts_cache]
        function_names = ['list_tools', 'list_resources', 'list_prompts']
        for feature, function_name in zip(features, function_names):
            await self._send_message_to_client(server_id, RouteMessage(function_name=function_name, args=(), kwargs={}))
            response = await self._get_client_response(server_id)
            if response.result:
                try:
                    feature_list = response.result
                    if server_id in feature:
                        feature[server_id] += feature_list
                    else:
                        feature[server_id] = feature_list
                except Exception as e:
                    logger.error(f"Failed to parse {function_name} from server {server_id}: {e}")

    async def refresh(self, server_id: str = None):
        """Refresh the cached features and update the vector caches."""
        logger.debug("Refreshing cached features and vector caches.")
        features = [self._mcp_server_tools_cache, self._mcp_server_resources_cache, self._mcp_server_prompts_cache]
        collections = [self.tools_collection, self.resources_collection, self.prompts_collection]

        docs = []
        ids = []
        metas = []
        for feature, collection in zip(features, collections):
            feature_list = feature.get(server_id, [])
            for item in feature_list:
                name = f"{server_id}_{item.name}"
                des = item.description
                metad = {"server_id": server_id, "original_name": item.name}
                ids.append(name)
                docs.append(des)
                metas.append(metad)
                if not ids:
                    return
                self.ChromaDb.update_data(documents=docs, ids=ids, metadata=metas, collection_id=collection)
