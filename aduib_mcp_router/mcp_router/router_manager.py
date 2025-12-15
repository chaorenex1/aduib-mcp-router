import asyncio
import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Awaitable

from aduib_mcp_router.configs import config
from aduib_mcp_router.configs.remote.nacos.client import NacosClient
from aduib_mcp_router.mcp_router.chromadb import ChromaDB
from aduib_mcp_router.mcp_router.config_loader.config_loader import ConfigLoader
from aduib_mcp_router.mcp_router.config_loader.remote_config_loader import RemoteConfigLoader
from aduib_mcp_router.mcp_router.install_bun import install_bun
from aduib_mcp_router.mcp_router.install_uv import install_uv
from aduib_mcp_router.mcp_router.mcp_client import McpClient
from aduib_mcp_router.mcp_router.types import McpServers, McpServerInfo, McpServerInfoArgs, ShellEnv, RouteMessage
from aduib_mcp_router.utils import random_uuid

logger = logging.getLogger(__name__)


class RouterManager:
    """Factory class for initializing router configurations and directories."""

    def __init__(self):

        self.app = None
        self._mcp_vector_cache = {}
        self._mcp_server_cache: dict[str, McpServerInfo] = {}
        self._mcp_client_cache: dict[str, McpClient] = {}
        self._mcp_server_tools_cache: dict[str, list[Any]] = {}
        self._mcp_server_resources_cache: dict[str, list[Any]] = {}
        self._mcp_server_prompts_cache: dict[str, list[Any]] = {}
        self._clients_initialized = False

        self.route_home = self.init_router_home()
        if not self.check_bin_exists('bun'):
            ret_code = install_bun()
            if ret_code != 0:
                raise EnvironmentError("Failed to install 'bun' binary.")
        if not self.check_bin_exists('uvx'):
            ret_code = install_uv()
            if ret_code != 0:
                raise EnvironmentError("Failed to install 'uvx' binary.")
        config_loader = ConfigLoader.get_config_loader(config.MCP_CONFIG_PATH, self.route_home)
        if config_loader and  isinstance(config_loader, RemoteConfigLoader):
            self.nacos_client:NacosClient = config_loader.client
        self.mcp_router_json = os.path.join(self.route_home, "mcp_router.json")
        self.resolve_mcp_configs(self.mcp_router_json, config_loader.load())

        self.ChromaDb = ChromaDB(self.route_home)
        self.tools_collection = self.ChromaDb.create_collection(collection_name="tools")
        self.prompts_collection = self.ChromaDb.create_collection(collection_name="prompts")
        self.resources_collection = self.ChromaDb.create_collection(collection_name="resources")
        self.async_updator()

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
            router_home = os.path.join(user_home, ".aduib_mcp_router")
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

    async def initialize_clients(self):
        """Initialize all MCP clients and keep them connected."""
        if self._clients_initialized:
            logger.info("Clients already initialized, skipping...")
            return

        logger.info(f"Initializing {len(self._mcp_server_cache)} MCP clients...")
        for server_id, server in self._mcp_server_cache.items():
            try:
                logger.info(f"Initializing client for server '{server.name}' (ID: {server_id})")
                client = McpClient(server)
                await client.__aenter__()
                self._mcp_client_cache[server_id] = client
                logger.info(f"Client '{server.name}' initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize client for server '{server.name}': {e}")
                traceback.print_exc()

        self._clients_initialized = True
        logger.info(f"Successfully initialized {len(self._mcp_client_cache)} MCP clients")

    async def cleanup_clients(self):
        """Clean up all MCP client connections."""
        logger.info("Cleaning up MCP clients...")
        for server_id, client in list(self._mcp_client_cache.items()):
            try:
                logger.info(f"Cleaning up client for server ID: {server_id}")
                await client.__aexit__(None, None, None)
            except Exception as e:
                logger.error(f"Error cleaning up client {server_id}: {e}")

        self._mcp_client_cache.clear()
        self._clients_initialized = False
        logger.info("All MCP clients cleaned up")

    def get_client(self, server_id: str) -> McpClient | None:
        """Get an existing MCP client by server ID."""
        return self._mcp_client_cache.get(server_id)

    async def _init_features(self, feature_type: str):
        """Initialize MCP clients and cache their features."""
        # callbacks = [self.async_updator]
        callbacks = []
        tasks=[]
        for i, mcp_server in enumerate(self._mcp_server_cache.values()):
            tasks.append(self.cache_mcp_features(feature_type,mcp_server.id))
            tasks.append(self.refresh(feature_type,mcp_server.id))
        try:
            await asyncio.gather(*tasks,return_exceptions=True)
        except Exception as e:
            logger.error(f"Client failed: {e}")

    async def _int_client_features(self, mcp_server, index: int,callbacks:list[Callable[..., Awaitable[Any]]]):
        """Initialize a single MCP client and cache its features."""
        try:
                await self.cache_mcp_features(mcp_server.id)
                await self.refresh(mcp_server.id)
                last = (index+1) == len(self._mcp_server_cache)
                if last:
                    if callbacks:
                        for callback in callbacks:
                            await callback()
                # await client.maintain_message_loop()
        except Exception as e:
            logger.error(f"Client {mcp_server.name} failed: {e}")

    async def _send_message_wait_response(self, server_id: str, message: RouteMessage,timeout: float = 600.0):
        """Send a message to a specific MCP client."""
        # Ensure clients are initialized
        if not self._clients_initialized:
            await self.initialize_clients()

        client = self._mcp_client_cache.get(server_id)
        if not client:
            logger.error(f"No client found for server ID {server_id}")
            return None

        try:
            await client.send_message(message)
            response = await asyncio.wait_for(client.receive_message(), timeout=timeout)
            return response
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for response from client {server_id}")
            return None
        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error communicating with client {server_id}: {e}")
            return None

    async def cache_mcp_features(self,feature_type: str, server_id: str = None):
        """List all tools from all MCP clients and config_cache them."""
        logger.debug("Listing and caching MCP features.")
        feature_cache = []
        function_names = []
        if feature_type == 'tool':
            feature_cache = [self._mcp_server_tools_cache]
            function_names = ['list_tools']
        elif feature_type == 'resource':
            feature_cache = [self._mcp_server_resources_cache]
            function_names = ['list_resources']
        elif feature_type == 'prompt':
            feature_cache = [self._mcp_server_prompts_cache]
            function_names = ['list_prompts']
        for feature, function_name in zip(feature_cache, function_names):
            response = await self._send_message_wait_response(server_id, RouteMessage(function_name=function_name, args=(), kwargs={}))
            # 检查响应是否为空
            if response is None:
                logger.warning(f"No response received for {function_name} from server {server_id}")
                continue
            if response.result:
                try:
                    feature_list = response.result
                    if server_id in feature:
                        feature[server_id].clear()
                        feature[server_id].extend(feature_list)
                    else:
                        feature[server_id] = feature_list
                except Exception as e:
                    logger.error(f"Failed to parse {function_name} from server {server_id}: {e}")

    async def refresh(self,feature_type: str, server_id: str = None):
        """Refresh the cached features and update the vector caches."""
        logger.debug("Refreshing cached features and vector caches.")
        features_cache = []
        collections = []
        feature_names = []
        if feature_type == 'tool':
            features_cache = [self._mcp_server_tools_cache]
            collections = [self.tools_collection]
            feature_names = ['tool']
        elif feature_type == 'resource':
            features_cache = [self._mcp_server_resources_cache]
            collections = [self.resources_collection]
            feature_names = ['resource']
        elif feature_type == 'prompt':
            features_cache = [self._mcp_server_prompts_cache]
            collections = [self.prompts_collection]
            feature_names = ['prompt']

        try:
            cache=self._mcp_vector_cache
            for feature, collection,feature_name in zip(features_cache, collections,feature_names):
                feature_list = feature.get(server_id, [])
                if not feature_list:
                    continue
                for item in feature_list:
                    docs = []
                    ids = []
                    metas = []
                    name = f"{feature_name}-{server_id}-{item.name}"
                    if name in cache:
                        continue
                    des=item.description if item.description else item.name
                    ids.append(name)
                    docs.append(des)
                    metad = {"server_id": server_id, "original_name": item.name}
                    metas.append(metad)
                    if not ids:
                        return
                    self._mcp_vector_cache[name] = docs
                    logger.debug(f"Updating collection '{collection}' with {len(ids)} items from server '{server_id}'.")
                    self.ChromaDb.update_data(documents=docs, ids=ids, metadata=metas, collection_id=collection)
                    deleted_id = self.ChromaDb.get_deleted_ids(collection_id=collection,_cache=cache)
                    if len(deleted_id) > 0:
                        logger.debug(f"Deleting {len(deleted_id)} items from collection '{collection}' not present in server '{server_id}'.")
                        self.ChromaDb.delete(ids=deleted_id, collection_id=collection)
        except Exception as e:
            logger.error(f"Error during refresh: {e}")


    def async_updator(self):
        """Asynchronous updater to refresh all cached features and vector caches."""
        async def _async_updater():
            _features=['tool','resource','prompt']
            while True:
                try:
                    await asyncio.sleep(config.MCP_REFRESH_INTERVAL)
                except Exception as e:
                    logger.warning("exception while sleeping: ", exc_info=e)
                try:
                    for feature in _features:
                        for mcp_server in self._mcp_server_cache.values():
                            await self.cache_mcp_features(feature,mcp_server.id)
                            await self.refresh(feature,mcp_server.id)
                except Exception as e:
                    logger.warning("exception while updating mcp servers: ", exc_info=e)
        asyncio.create_task(_async_updater())



    async def list_tools(self):
        """List all cached tools from all MCP clients."""
        if len(self._mcp_server_tools_cache.values())<=0:
            await self._init_features("tool")
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

    async def list_resources(self):
        """List all cached resources from all MCP clients."""
        if len(self._mcp_server_resources_cache.values())<=0:
            await self._init_features("resource")
        resources = []
        for resource_list in self._mcp_server_resources_cache.values():
            resources += resource_list
        return resources

    async def list_prompts(self):
        """List all cached prompts from all MCP clients."""
        if len(self._mcp_server_prompts_cache.values())<=0:
            await self._init_features("prompt")
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

        actual_list = [md for md in metadata_list if md.get("original_name") == name]
        if not actual_list:
            logger.debug(f"No exact match found for tool name '{name}' in metadata.")
            raise ValueError(f"Tool {name} not found.")

        result_list = []
        for metadata in actual_list:
            server_id = metadata.get("server_id")
            original_tool_name = metadata.get("original_name")
            response = await self._send_message_wait_response(server_id, RouteMessage(function_name='call_tool', args=(original_tool_name, arguments), kwargs={}))
            if response and response.result:
                result_list.append(response.result)
        return result_list

