import asyncio
import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any, cast

import requests

from aduib_mcp_router.configs import config
from aduib_mcp_router.mcp_router.chromadb import ChromaDB
from aduib_mcp_router.mcp_router.install_bun import install_bun
from aduib_mcp_router.mcp_router.install_uv import install_uv
from aduib_mcp_router.mcp_router.mcp_client import McpClient
from aduib_mcp_router.mcp_router.types import McpServers, McpServerInfo, McpServerInfoArgs, ShellEnv, RouteMessage, \
    RouteMessageResult
from aduib_mcp_router.utils import random_uuid

logger = logging.getLogger(__name__)


class RouterManager:
    """Factory class for initializing router configurations and directories."""

    def __init__(self):

        self.app = None
        self._mcp_server_cache: dict[str, McpServerInfo] = {}
        self._mcp_client_cache: dict[str, McpClient] = {}
        self._mcp_server_tools_cache: dict[str, list[Any]] = {}
        self._mcp_server_resources_cache: dict[str, list[Any]] = {}
        self._mcp_server_prompts_cache: dict[str, list[Any]] = {}


        self.route_home = self.init_router_home()
        if not self.check_bin_exists('bun'):
            ret_code = install_bun()
            if ret_code != 0:
                raise EnvironmentError("Failed to install 'bun' binary.")
        if not self.check_bin_exists('uvx'):
            ret_code = install_uv()
            if ret_code != 0:
                raise EnvironmentError("Failed to install 'uvx' binary.")
        self.init_mcp_configs(router_home=self.route_home)

        self.ChromaDb = ChromaDB(self.route_home)
        self.tools_collection = self.ChromaDb.create_collection(collection_name="tools")
        self.prompts_collection = self.ChromaDb.create_collection(collection_name="prompts")
        self.resources_collection = self.ChromaDb.create_collection(collection_name="resources")

    @classmethod
    def get_router_manager(cls):
        """Get the RouterManager instance from the app context."""
        return cls()

    def get_mcp_server(self, server_id: str) -> McpServerInfo | None:
        """Get MCP server information by server ID."""
        return self._mcp_server_cache.get(server_id)

    def init_router_home(self) -> str:
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
                    logger.warning(f"MCP configuration file {config.MCP_CONFIG_URL} does not exist.")
                    config.MCP_CONFIG_URL =os.getenv("MCP_CONFIG_URL")
                    if not config.MCP_CONFIG_URL or not os.path.exists(config.MCP_CONFIG_URL):
                        if os.path.exists(os.path.join(router_home, "mcp_config.json")):
                            config.MCP_CONFIG_URL = os.path.join(router_home, "mcp_config.json")
                        else:
                            logger.warning(f"MCP configuration file {config.MCP_CONFIG_URL} does not exist, using default empty config.")
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

            mcp_server = McpServerInfo(id=random_uuid(), name=name, args=mcp_server_args)
            self._mcp_server_cache[mcp_server.id] = mcp_server
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

    @classmethod
    def get_shell_env(cls, args: McpServerInfoArgs) -> ShellEnv:
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
            shell_env.bin_path = cls.get_binary('bun')
            # shell_env.command_run=shell_env.bin_path
            args_list.append(shell_env.bin_path)
            for i, arg in enumerate(args.args):
                if arg == '-y' or arg == '--yes':
                    args_list.append('x')
                else:
                    args_list.append(arg)
        if args.command and (args.command == 'uvx' or args.command == 'uv'):
            shell_env.bin_path = cls.get_binary('uvx')
            # shell_env.command_run = shell_env.bin_path
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

    async def init_mcp_clients(self):
        """Initialize MCP clients based on the loaded configurations."""
        for mcp_server in self._mcp_server_cache.values():
            client = McpClient(mcp_server)
            self._mcp_client_cache[mcp_server.id] = client
            logger.info(f"MCP client '{mcp_server.name}' type '{client.client_type}' initialized.")
        tasks = []
        for i, mcp_client in enumerate(self._mcp_client_cache.values()):
            tasks.append(self._run_client(mcp_client, i))
        # tasks.append(self._run_mcp_server())
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_client(self, client: McpClient, index: int):
        """run MCP client."""
        try:
            async with client:
                await self._init_mcp_data(client)
                # maintain the client running
                last = (index+1) == len(self._mcp_server_cache)
                logger.debug(f"index: {index}, last: {last}")
                if last:
                    logger.info("All MCP clients have been processed.")
                    # await self._register_to_discovery_service()
                    logger.debug(f"Starting message processing loop for server '{client.server.name}'")
                    await self._run_mcp_server()
                await client.maintain_message_loop()
        except Exception as e:
            traceback.print_exc()
            logger.error(f"Client {client.server.name} failed: {e}")

    async def _init_mcp_data(self, client):
        await self.cache_mcp_features(client.server.id)
        await self.refresh(client.server.id)

    async def _run_mcp_server(self):
        """Run the MCP server."""
        from aduib_mcp_router.libs import app_context
        from aduib_mcp_router.mcp_factory import MCPFactory
        mcp_factory = MCPFactory.get_mcp_factory()
        if not self.app:
            self.app=app_context.get()
        self.app.mcp=mcp_factory.get_mcp()
        if self.app.config.DISCOVERY_SERVICE_ENABLED:
            from aduib_mcp_router.nacos_mcp import NacosMCP
            nacos_mcp = cast(NacosMCP, self.app.mcp)
            await nacos_mcp.register_service(self.app.config.TRANSPORT_TYPE)

        await mcp_factory.run_mcp_server()

    async def _register_to_discovery_service(self):
        """Register the router service to the discovery service."""
        from aduib_mcp_router.libs import app_context
        if not self.app:
            self.app=app_context.get()
        if self.app.config.DISCOVERY_SERVICE_ENABLED:
            from aduib_mcp_router.nacos_mcp import NacosMCP
            nacos_mcp = cast(NacosMCP, self.app.mcp)
            await nacos_mcp.register_service(self.app.config.TRANSPORT_TYPE)

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
                des = f"{item.name}_{item.description}"
                metad = {"server_id": server_id, "original_name": item.name}
                ids.append(name)
                docs.append(des)
                metas.append(metad)
                if not ids:
                    return
                self.ChromaDb.update_data(documents=docs, ids=ids, metadata=metas, collection_id=collection)



    def list_tools(self):
        """List all cached tools from all MCP clients."""
        tools = []
        for tool_list in self._mcp_server_tools_cache.values():
            tools += tool_list
        return tools

    def get_tool(self, name: str,server_id: str = None):
        """Get a cached tool by name."""
        tools = self._mcp_server_tools_cache.get(server_id)
        if tools:
            for tool in tools:
                if tool.name == name:
                    return tool
        return None

    def list_resources(self):
        """List all cached resources from all MCP clients."""
        resources = []
        for resource_list in self._mcp_server_resources_cache.values():
            resources += resource_list
        return resources

    def list_prompts(self):
        """List all cached prompts from all MCP clients."""
        prompts = []
        for prompt_list in self._mcp_server_prompts_cache.values():
            prompts += prompt_list
        return prompts

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        """Call a tool by name with arguments."""
        logger.debug(f"Calling tool {name} with arguments {arguments}")
        query_result = self.ChromaDb.query(self.tools_collection, name, 10)
        metadatas = query_result.get("metadatas")
        metadata_list = metadatas[0] if metadatas else []
        if not metadata_list:
            logger.debug("No metadata found in search_tool result.")
            return query_result

        metadata = metadata_list[0]  # Just take the top result for simplicity
        server_id = metadata.get("server_id")
        original_tool_name = metadata.get("original_name")
        await self._send_message_to_client(server_id, RouteMessage(function_name='call_tool', args=(original_tool_name, arguments), kwargs={}))
        response = await self._get_client_response(server_id)
        return response.result
        raise ValueError(f"Tool {name} not found.")
