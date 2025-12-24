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
        self._feature_initialized: dict[str, bool] = {"tool": False, "resource": False, "prompt": False}
        # Track per-server status for init failures / circuit breaking
        self._mcp_server_status: dict[str, dict[str, Any]] = {}

        # Optional semaphores for controlling concurrency of inits and feature syncs
        init_limit = getattr(config, "MCP_MAX_INIT_CONCURRENCY", 5)
        feature_limit = getattr(config, "MCP_MAX_FEATURE_CONCURRENCY", 5)
        self._init_semaphore = asyncio.Semaphore(init_limit) if init_limit > 0 else None
        self._feature_semaphore = asyncio.Semaphore(feature_limit) if feature_limit > 0 else None

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
        # self.async_updator()

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
        """Get shell environment variables.

        For stdio MCP servers we prefer to execute the actual binary (uvx/bunx/python/etc.)
        directly, instead of always going through an interactive shell like cmd/bash.
        This helps avoid zombie-like child shells and makes process lifetime clearer.
        """
        shell_env = ShellEnv()
        args_list: list[str] = []

        # Pass-through environment from config
        shell_env.env = args.env

        # If server is not stdio-based, we don't construct a shell command here.
        # HTTP/SSE/etc. are handled by their respective clients and don't need a
        # local process command.
        if args.type and args.type != "stdio":
            shell_env.command_run = None
            shell_env.args = []
            return shell_env

        # stdio servers below
        # uvx / uv: prefer system uvx if available, otherwise fall back to bundled one
        if args.command and (args.command == "uvx" or args.command == "uv"):
            shell_env.command_run = args.command
            for arg in args.args:
                args_list.append(arg)
        # npx / bunx style commands
        elif args.command and args.command == "npx":
            # Use bun as the underlying runner when available
            shell_env.command_run = cls.get_binary("bun")
            # Map "npx" semantics onto "bun x" / "bunx": insert the subcommand marker
            for arg in args.args:
                if arg in ("-y", "--yes"):
                    # bun x does not need -y/--yes, translate to x
                    continue
                args_list.append(arg)
            # Prepend the "x" subcommand for bun
            args_list.insert(0, "x")
        else:
            # Fallback: run the given command directly (python, node, etc.)
            shell_env.command_run = args.command
            for arg in args.args:
                args_list.append(arg)

        shell_env.args = args_list
        return shell_env

    @classmethod
    def get_binary(cls, binary_name: str) -> str:
        """Get the path to the specified binary."""
        if sys.platform == "win32":
            binary_name = f"{binary_name}.exe"

        return os.path.join(config.ROUTER_HOME, "bin", binary_name)

    async def ensure_feature_cache(self, feature_type: str):
        """Ensure the given feature cache has been hydrated at least once."""
        if self._feature_initialized.get(feature_type):
            return
        await self._init_features(feature_type)

    async def _run_client_initialization(self):
        """Sequentially initialize MCP clients for all configured servers."""
        if not self._mcp_server_cache:
            logger.info("No MCP servers configured; skipping client initialization.")
            self._clients_initialized = True
            return

        logger.info(f"Sequentially initializing MCP clients for {len(self._mcp_server_cache)} servers...")
        success: list[str] = []
        failed: list[str] = []

        for server_id, server in self._mcp_server_cache.items():
            logger.debug(f"Initializing client for server '{server.name}' (ID: {server_id})...")
            try:
                client = await self.get_or_create_client(server_id)
                if client is not None:
                    success.append(server.name)
                else:
                    failed.append(server.name)
            except Exception as e:  # noqa: BLE001
                failed.append(server.name)
                logger.error(f"Error initializing client for server '{server.name}': {e}")

        self._clients_initialized = True
        logger.info(f"Sequential initialization complete; active clients: {len(self._mcp_client_cache)}")
        logger.info(f"MCP initialization success list: {success}")
        if failed:
            logger.warning(f"MCP initialization failed list: {failed}")

    async def _create_client(self, server_id: str) -> McpClient | None:
        """Lazily create and initialize a client for a single server.

        This version initializes one MCP at a time (no concurrency semaphore)
        to avoid overwhelming the host with many simultaneous stdio processes.
        """
        server = self._mcp_server_cache.get(server_id)
        if not server:
            logger.error(f"No MCP server config found for id={server_id}")
            return None

        status = self._mcp_server_status.setdefault(server_id, {})
        fail_count = status.get("fail_count", 0)
        circuit_until = status.get("circuit_until")
        now = asyncio.get_event_loop().time()
        if circuit_until and now < circuit_until:
            logger.warning(f"Skipping initialization for server {server.name} (circuit open)")
            return None

        init_timeout = getattr(config, "MCP_INIT_TIMEOUT", 30.0)

        async def _do_init() -> McpClient | None:
            client = McpClient(server)
            try:
                await client.__aenter__()
                status["fail_count"] = 0
                status["last_error"] = None
                status["last_init_time"] = now
                logger.info(f"Client '{server.name}' initialized successfully")
                return client
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to initialize client for server '{server.name}': {e}")
                traceback.print_exc()
                status["fail_count"] = fail_count + 1
                status["last_error"] = str(e)
                # Basic backoff: open circuit for some seconds when failures accumulate
                backoff_base = getattr(config, "MCP_INIT_BACKOFF_BASE", 10.0)
                status["circuit_until"] = now + backoff_base * max(1, status["fail_count"])
                return None

        try:
            # One-by-one init: no concurrency semaphore here
            return await asyncio.wait_for(_do_init(), timeout=init_timeout)
        except asyncio.TimeoutError:
            logger.error(f"Timeout while initializing client for server '{server.name}'")
            status["fail_count"] = fail_count + 1
            status["last_error"] = "init timeout"
            backoff_base = getattr(config, "MCP_INIT_BACKOFF_BASE", 10.0)
            status["circuit_until"] = now + backoff_base * max(1, status["fail_count"])
            return None

    async def get_or_create_client(self, server_id: str) -> McpClient | None:
        """Get or lazily initialize an MCP client for a given server id."""
        client = self._mcp_client_cache.get(server_id)
        logger.info(f"Client '{client}' fetched from cache for server ID '{server_id}'")
        if client is not None:
            return client

        client = await self._create_client(server_id)
        if client is not None:
            self._mcp_client_cache[server_id] = client
        return client

    async def initialize_clients(self):
        """Ensure MCP clients are initialized, awaiting any in-progress warmups."""
        if self._clients_initialized:
            logger.info("Clients already initialized, skipping pre-warm...")
            return

        await self._run_client_initialization()

    async def initialize_all_features(self):
        """Initialize clients and hydrate all feature caches sequentially."""
        await self.initialize_clients()
        for feature in ("tool", "resource", "prompt"):
            if not self._feature_initialized.get(feature):
                await self._init_features(feature)

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
        for feature in self._feature_initialized.keys():
            self._feature_initialized[feature] = False
        logger.info("All MCP clients cleaned up")

    def get_client(self, server_id: str) -> McpClient | None:
        """Get an existing MCP client by server ID."""
        return self._mcp_client_cache.get(server_id)

    async def _init_features(self, feature_type: str):
        """Initialize/cached features for all servers with bounded concurrency.

        This pulls feature metadata from all available servers and updates local caches.
        """
        try:
            await self.initialize_clients()
        except asyncio.CancelledError:
            logger.debug("Feature initialization for %s cancelled while waiting for clients.", feature_type)
            raise
        tasks = []
        success: list[str] = []
        failed: list[str] = []

        async def _sync_server(server_id: str):
            server = self._mcp_server_cache.get(server_id)
            if not server:
                return
            try:
                # Ensure client exists (lazy) but ignore failures here
                await self.get_or_create_client(server_id)
                if self._feature_semaphore is not None:
                    async with self._feature_semaphore:
                        await self.cache_mcp_features(feature_type, server_id)
                        await self.refresh(feature_type, server_id)
                else:
                    await self.cache_mcp_features(feature_type, server_id)
                    await self.refresh(feature_type, server_id)
                success.append(server.name)
            except Exception as e:  # noqa: BLE001
                failed.append(server.name)
                logger.error(f"Feature initialization failed for server '{server.name}', type '{feature_type}': {e}")

        for server_id in self._mcp_server_cache.keys():
            tasks.append(_sync_server(server_id))

        if not tasks:
            return

        await asyncio.gather(*tasks, return_exceptions=True)

        logger.debug(f"Feature '{feature_type}' init success MCPs: {success}")
        self._feature_initialized[feature_type] = True
        if failed:
            logger.warning(f"Feature '{feature_type}' init failed MCPs: {failed}")

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

    async def _send_message_wait_response(self, server_id: str, message: RouteMessage, timeout: float = 600.0):
        """Send a message to a specific MCP client with per-call timeout and lazy init."""
        await self.initialize_clients()
        # Determine effective timeout based on function_name if caller didn't override
        if timeout == 600.0 and message.function_name:
            # Default timeouts configurable per category
            if message.function_name.startswith("list_"):
                timeout = float(getattr(config, "MCP_LIST_TIMEOUT", 30.0))
            elif message.function_name == "call_tool":
                timeout = float(getattr(config, "MCP_CALL_TOOL_TIMEOUT", 120.0))
            else:
                timeout = float(getattr(config, "MCP_DEFAULT_TIMEOUT", 60.0))

        # Lazy init per server instead of initializing all at once
        client = await self.get_or_create_client(server_id)
        if not client:
            logger.error(f"No available client for server ID {server_id}")
            return None

        try:
            await client.send_message(message)
            response = await asyncio.wait_for(client.receive_message(), timeout=timeout)
            return response
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for response from client {server_id} for {message.function_name}")
            return None
        except Exception as e:  # noqa: BLE001
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
                    metad = {"server_id": server_id, "original_name": getattr(item, "name", None)}
                    if feature_name == 'resource':
                        metad["uri"] = getattr(item, "uri", None)
                        metad["mime_type"] = getattr(item, "mimeType", None)
                        metad["description"] = getattr(item, "description", None)
                    elif feature_name == 'tool':
                        metad["description"] = getattr(item, "description", None)
                    elif feature_name == 'prompt':
                        metad["description"] = getattr(item, "description", None)
                    metas.append(metad)
                    if not ids:
                        return
                    self._mcp_vector_cache[name] = docs
                    # logger.debug(f"Updating collection '{collection}' with {len(ids)} items from server '{server_id}'.")
                    self.ChromaDb.update_data(documents=docs, ids=ids, metadata=metas, collection_id=collection)
                    deleted_id = self.ChromaDb.get_deleted_ids(collection_id=collection,_cache=cache)
                    if len(deleted_id) > 0:
                        # logger.debug(f"Deleting {len(deleted_id)} items from collection '{collection}' not present in server '{server_id}'.")
                        self.ChromaDb.delete(ids=deleted_id, collection_id=collection)
        except Exception as e:
            logger.error(f"Error during refresh: {e}")

    def _extract_vector_results(self, query_result: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize chroma query results into a single list of dicts."""
        results: list[dict[str, Any]] = []
        metadata_rows = query_result.get("metadatas") or []
        document_rows = query_result.get("documents") or []
        distance_rows = query_result.get("distances") or []
        id_rows = query_result.get("ids") or []
        if not metadata_rows:
            return results
        metadata_list = metadata_rows[0]
        document_list = document_rows[0] if document_rows else [None] * len(metadata_list)
        distance_list = distance_rows[0] if distance_rows else [None] * len(metadata_list)
        id_list = id_rows[0] if id_rows else [None] * len(metadata_list)
        for metadata, document, distance, item_id in zip(metadata_list, document_list, distance_list, id_list):
            results.append(
                {
                    "metadata": metadata or {},
                    "document": document,
                    "distance": distance,
                    "id": item_id,
                }
            )
        return results

    def _safe_model_dump(self, value: Any) -> Any:
        """Convert pydantic models to plain dicts when possible."""
        if value is None:
            return None
        dump = getattr(value, "model_dump", None)
        if callable(dump):
            return dump()
        return value

    async def search_tools(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search tool metadata using the vector index."""
        await self.ensure_feature_cache("tool")
        query_result = self.ChromaDb.query(self.tools_collection, query, limit)
        entries = self._extract_vector_results(query_result)
        matches: list[dict[str, Any]] = []
        for entry in entries:
            metadata = entry["metadata"] or {}
            server_id = metadata.get("server_id")
            original_name = metadata.get("original_name")
            if not server_id or not original_name:
                continue
            tool = self.get_tool(original_name, server_id)
            if not tool:
                continue
            server = self.get_mcp_server(server_id)
            match = {
                "tool_name": tool.name,
                "description": tool.description,
                "server_id": server_id,
                "server_name": server.name if server else None,
                "input_schema": tool.inputSchema,
                "annotations": self._safe_model_dump(getattr(tool, "annotations", None)),
                "score": float(entry["distance"]) if entry["distance"] is not None else None,
            }
            matches.append(match)
        return matches

    async def search_prompts(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search prompt metadata using the vector index."""
        await self.ensure_feature_cache("prompt")
        query_result = self.ChromaDb.query(self.prompts_collection, query, limit)
        entries = self._extract_vector_results(query_result)
        matches: list[dict[str, Any]] = []
        for entry in entries:
            metadata = entry["metadata"] or {}
            server_id = metadata.get("server_id")
            original_name = metadata.get("original_name")
            if not server_id or not original_name:
                continue
            prompt = self.get_prompt(original_name, server_id)
            if not prompt:
                continue
            server = self.get_mcp_server(server_id)
            match = {
                "prompt_name": prompt.name,
                "description": prompt.description,
                "arguments": [arg.model_dump() for arg in (prompt.arguments or [])],
                "server_id": server_id,
                "server_name": server.name if server else None,
                "score": float(entry["distance"]) if entry["distance"] is not None else None,
            }
            matches.append(match)
        return matches

    async def search_resources(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search resource metadata using the vector index."""
        await self.ensure_feature_cache("resource")
        query_result = self.ChromaDb.query(self.resources_collection, query, limit)
        entries = self._extract_vector_results(query_result)
        matches: list[dict[str, Any]] = []
        for entry in entries:
            metadata = entry["metadata"] or {}
            server_id = metadata.get("server_id")
            if not server_id:
                continue
            server = self.get_mcp_server(server_id)
            match = {
                "resource_name": metadata.get("original_name"),
                "description": metadata.get("description"),
                "uri": metadata.get("uri"),
                "mime_type": metadata.get("mime_type"),
                "server_id": server_id,
                "server_name": server.name if server else None,
                "score": float(entry["distance"]) if entry["distance"] is not None else None,
            }
            matches.append(match)
        return matches


    def async_updator(self):
        """Asynchronous updater to periodically refresh cached features and vector caches."""
        async def _async_updater():
            _features = ['tool', 'resource', 'prompt']
            while True:
                try:
                    await asyncio.sleep(config.MCP_REFRESH_INTERVAL)
                except Exception as e:  # noqa: BLE001
                    logger.warning("exception while sleeping: ", exc_info=e)
                    continue
                try:
                    for feature in _features:
                        await self._init_features(feature)
                except Exception as e:  # noqa: BLE001
                    logger.warning("exception while updating mcp servers: ", exc_info=e)
        asyncio.create_task(_async_updater())

    async def list_tools(self):
        """List all cached tools from all MCP clients, initializing on-demand."""
        await self.ensure_feature_cache("tool")
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

    def get_prompt(self, name: str, server_id: str = None):
        """Get a cached prompt by name."""
        prompts = self._mcp_server_prompts_cache.get(server_id)
        if prompts:
            for prompt in prompts:
                if prompt.name == name:
                    return prompt
        return None

    async def list_resources(self):
        """List all cached resources from all MCP clients, initializing on-demand."""
        await self.ensure_feature_cache("resource")
        resources = []
        for resource_list in self._mcp_server_resources_cache.values():
            resources += resource_list
        return resources

    async def list_prompts(self):
        """List all cached prompts from all MCP clients, initializing on-demand."""
        await self.ensure_feature_cache("prompt")
        prompts = []
        for prompt_list in self._mcp_server_prompts_cache.values():
            prompts += prompt_list
        return prompts

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        """Call a tool by name with arguments across all matching servers with per-call timeouts."""
        logger.debug(f"Calling tool {name} with arguments {arguments}")
        await self.ensure_feature_cache("tool")
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

        # Use a configurable timeout for tool calls
        timeout = float(getattr(config, "MCP_CALL_TOOL_TIMEOUT", 120.0))

        async def _call_single(md: dict[str, Any]):
            server_id = md.get("server_id")
            original_tool_name = md.get("original_name")
            if not server_id or not original_tool_name:
                return None
            try:
                response = await self._send_message_wait_response(
                    server_id,
                    RouteMessage(function_name='call_tool', args=(original_tool_name, arguments), kwargs={}),
                    timeout=timeout,
                )
                if response and getattr(response, "result", None) is not None:
                    return response.result
            except Exception as e:  # noqa: BLE001
                logger.error(f"Error calling tool {original_tool_name} on server {server_id}: {e}")
            return None

        tasks = [_call_single(md) for md in actual_list]
        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        result_list = [r for r in results if not isinstance(r, Exception) and r is not None]
        return result_list

    async def read_resource(self, server_id: str, uri: str, timeout: float | None = None):
        """Read a remote resource via the routed MCP client."""
        await self.ensure_feature_cache("resource")
        effective_timeout = timeout or float(getattr(config, "MCP_READ_RESOURCE_TIMEOUT", 60.0))
        response = await self._send_message_wait_response(
            server_id,
            RouteMessage(function_name='read_resource', args=(uri,), kwargs={}),
            timeout=effective_timeout,
        )
        return getattr(response, "result", None) if response else None

