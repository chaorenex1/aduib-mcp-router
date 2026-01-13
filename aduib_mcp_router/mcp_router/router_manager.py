import asyncio
import json
import logging
import os
import sys
import threading
import traceback
from asyncio import CancelledError
from pathlib import Path
from typing import Any, Callable, Awaitable

from httpx import HTTPError

from aduib_mcp_router.configs import config
from aduib_mcp_router.configs.remote.nacos.client import NacosClient
from aduib_mcp_router.mcp_router.chromadb import ChromaDB
from aduib_mcp_router.mcp_router.config_loader.config_loader import ConfigLoader
from aduib_mcp_router.mcp_router.config_loader.remote_config_loader import RemoteConfigLoader
from aduib_mcp_router.mcp_router.install_bun import install_bun
from aduib_mcp_router.mcp_router.install_uv import install_uv
from aduib_mcp_router.mcp_router.mcp_client import McpClient
from datetime import datetime, timezone, timedelta
from aduib_mcp_router.mcp_router.types import (
    McpServers, McpServerInfo, McpServerInfoArgs, ShellEnv, RouteMessage,
    ClientHealthStatus, ClientHealthInfo, HealthStatusCallback,
    CacheEntry, CacheStatus
)
from aduib_mcp_router.utils import random_uuid

logger = logging.getLogger(__name__)


def _format_exception_group(exc: BaseException) -> str:
    """Format ExceptionGroup to show all sub-exceptions."""
    if isinstance(exc, ExceptionGroup):
        parts = [f"{exc.__class__.__name__}: {exc}"]
        for i, sub_exc in enumerate(exc.exceptions, 1):
            parts.append(f"  [{i}] {sub_exc.__class__.__name__}: {sub_exc}")
        return "\n".join(parts)
    return str(exc)


class RouterManager:
    """Factory class for initializing router configurations and directories.

    Uses singleton pattern to ensure only one instance exists per process,
    preventing duplicate ChromaDB instances and resource waste.
    """

    _instance: "RouterManager | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        """Ensure only one RouterManager instance exists (singleton pattern)."""
        if cls._instance is None:
            with cls._instance_lock:
                # Double-check locking pattern
                if cls._instance is None:
                    instance = super().__new__(cls)
                    cls._instance = instance
        return cls._instance

    def __init__(self):
        # Prevent re-initialization if already initialized (singleton pattern)
        if hasattr(self, '_initialized') and self._initialized:
            return

        self.app = None
        self._mcp_vector_cache = {}
        self._mcp_server_cache: dict[str, McpServerInfo] = {}
        self._mcp_client_cache: dict[str, McpClient] = {}
        self._mcp_server_tools_cache: dict[str, list[Any]] = {}
        self._mcp_server_resources_cache: dict[str, list[Any]] = {}
        self._mcp_server_prompts_cache: dict[str, list[Any]] = {}
        self._clients_initialized = False
        # TTL-based cache metadata: {server_id: {feature_type: CacheEntry}}
        self._cache_metadata: dict[str, dict[str, CacheEntry]] = {}
        self._mcp_server_status: dict[str, dict[str, Any]] = {}
        self._stop_event = asyncio.Event()  # Graceful shutdown signal
        self._updater_task: asyncio.Task | None = None  # Reference to updater task

        # Lock for client creation to prevent race conditions
        self._client_creation_locks: dict[str, asyncio.Lock] = {}
        self._client_creation_global_lock = asyncio.Lock()

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
        if config_loader and isinstance(config_loader, RemoteConfigLoader):
            self.nacos_client: NacosClient = config_loader.client
        self.mcp_router_json = os.path.join(self.route_home, "mcp_router.json")
        self.resolve_mcp_configs(self.mcp_router_json, config_loader.load())

        self.ChromaDb = ChromaDB(self.route_home)
        self.tools_collection = self.ChromaDb.create_collection(collection_name="tools")
        self.prompts_collection = self.ChromaDb.create_collection(collection_name="prompts")
        self.resources_collection = self.ChromaDb.create_collection(collection_name="resources")

        # Mark as initialized to prevent re-initialization
        self._initialized = True
        logger.info("RouterManager singleton instance initialized")

    @classmethod
    def get_router_manager(cls):
        """Get the singleton RouterManager instance."""
        return cls()

    @classmethod
    def reset_instance(cls):
        """Reset the singleton instance (primarily for testing).

        WARNING: This should only be used in tests. In production,
        the singleton should persist for the lifetime of the process.
        """
        with cls._instance_lock:
            if cls._instance is not None:
                # Reset initialization flag before clearing instance
                if hasattr(cls._instance, '_initialized'):
                    cls._instance._initialized = False
                cls._instance = None
        logger.info("RouterManager singleton instance reset")

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

    def _get_cache_status(self, server_id: str, feature_type: str) -> CacheStatus:
        """Check cache status for a specific server and feature type."""
        server_meta = self._cache_metadata.get(server_id, {})
        entry = server_meta.get(feature_type)
        if not entry:
            return CacheStatus.MISSING

        now = datetime.now(timezone.utc)
        if now < entry.expires_at:
            return CacheStatus.VALID
        elif now < entry.stale_until:
            return CacheStatus.STALE
        else:
            return CacheStatus.EXPIRED

    def _update_cache_metadata(self, server_id: str, feature_type: str):
        """Update cache metadata after successful refresh."""
        now = datetime.now(timezone.utc)
        ttl = config.MCP_CACHE_TTL
        stale_ttl = config.MCP_CACHE_STALE_TTL

        if server_id not in self._cache_metadata:
            self._cache_metadata[server_id] = {}

        self._cache_metadata[server_id][feature_type] = CacheEntry(
            server_id=server_id,
            feature_type=feature_type,
            last_updated=now,
            expires_at=now + timedelta(seconds=ttl),
            stale_until=now + timedelta(seconds=ttl + stale_ttl),
            is_refreshing=False,
        )
        logger.debug(f"Cache metadata updated for server={server_id}, feature={feature_type}, TTL={ttl}s")

    def _extend_cache_ttl(self, server_id: str):
        """Extend cache TTL for a server when health check succeeds.

        This optimization allows health check success to extend cache validity,
        avoiding unnecessary refresh since the server is confirmed healthy.
        """
        if server_id not in self._cache_metadata:
            return

        now = datetime.now(timezone.utc)
        ttl = config.MCP_CACHE_TTL
        stale_ttl = config.MCP_CACHE_STALE_TTL
        health_interval = config.MCP_HEALTH_CHECK_INTERVAL

        for feature_type, entry in self._cache_metadata[server_id].items():
            # Only extend if cache is STALE (not expired or missing)
            if entry.expires_at <= now < entry.stale_until:
                # Extend by health check interval (typically 30s)
                entry.expires_at = now + timedelta(seconds=health_interval)
                entry.stale_until = now + timedelta(seconds=health_interval + stale_ttl)
                logger.debug(f"Extended cache TTL for {server_id}/{feature_type} by {health_interval}s")

    async def _refresh_server_cache(self, server_id: str, feature_type: str):
        """Refresh cache for a single server and feature type."""
        server = self._mcp_server_cache.get(server_id)
        if not server:
            return

        # Mark as refreshing to prevent concurrent refresh
        server_meta = self._cache_metadata.get(server_id, {})
        entry = server_meta.get(feature_type)
        if entry and entry.is_refreshing:
            logger.debug(f"Skip refresh for {server.name}/{feature_type}: already refreshing")
            return

        if entry:
            entry.is_refreshing = True

        client = await self.get_or_create_client(server_id)
        if client and client.get_initialize_state:
            try:
                await self.cache_mcp_features(feature_type, server_id)
                await self.refresh(feature_type, server_id)
                self._update_cache_metadata(server_id, feature_type)
                logger.debug(f"Cache refreshed for server={server.name}, feature={feature_type}")
            except Exception as e:
                logger.error(f"Failed to refresh cache for {server.name}/{feature_type}: {e}")
        else:
            logger.warning(f"Cannot refresh cache for {server.name}: client not ready")

        if entry:
            entry.is_refreshing = False

    async def ensure_feature_cache(self, feature_type: str):
        """Ensure the given feature cache has been hydrated with TTL support.

        Implements Stale-While-Revalidate pattern:
        - VALID: Use cache directly
        - STALE: Return cache immediately, refresh in background
        - EXPIRED/MISSING: Refresh synchronously before returning
        """
        servers_to_sync_refresh: list[str] = []
        servers_to_async_refresh: list[str] = []

        for server_id in self._mcp_server_cache.keys():
            cache_status = self._get_cache_status(server_id, feature_type)

            if cache_status == CacheStatus.VALID:
                continue  # Cache is fresh, no action needed
            elif cache_status == CacheStatus.STALE:
                # Return stale data but schedule background refresh
                servers_to_async_refresh.append(server_id)
            else:  # EXPIRED or MISSING
                servers_to_sync_refresh.append(server_id)

        # Synchronously refresh servers with expired/missing cache
        if servers_to_sync_refresh:
            logger.info(f"Synchronously refreshing {feature_type} cache for {len(servers_to_sync_refresh)} servers")
            await asyncio.gather(*[
                self._refresh_server_cache(sid, feature_type)
                for sid in servers_to_sync_refresh
            ])

        # Asynchronously refresh stale servers in background
        if servers_to_async_refresh:
            logger.debug(f"Background refreshing {feature_type} cache for {len(servers_to_async_refresh)} servers")
            for sid in servers_to_async_refresh:
                asyncio.create_task(self._refresh_server_cache(sid, feature_type))

    async def _run_client_initialization(self):
        """Parallel initialize MCP clients for all configured servers.

        Uses asyncio.gather for parallel initialization with configurable concurrency.
        Each server has its own lock to prevent duplicate creation while allowing
        true parallelism across different servers.
        """
        if not self._mcp_server_cache:
            logger.info("No MCP servers configured; skipping client initialization.")
            self._clients_initialized = True
            return

        server_count = len(self._mcp_server_cache)
        logger.info(f"Parallel initializing MCP clients for {server_count} servers...")

        async def init_single_server(server_id: str, server: McpServerInfo) -> tuple[str, bool, str | None]:
            """Initialize a single server and return (name, success, error_msg)."""
            try:
                client = await self.get_or_create_client(server_id)
                if client is not None:
                    return (server.name, True, None)
                else:
                    return (server.name, False, "client returned None")
            except (HTTPError, ExceptionGroup, Exception) as e:
                error_detail = _format_exception_group(e)
                logger.error(f"Error initializing client for server '{server.name}':\n{error_detail}")
                return (server.name, False, error_detail)

        # Create tasks for all servers
        tasks = [
            init_single_server(server_id, server)
            for server_id, server in self._mcp_server_cache.items()
        ]

        # Execute all tasks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect results
        success: list[str] = []
        failed: list[str] = []
        for result in results:
            if isinstance(result, Exception):
                failed.append(f"<exception: {result}>")
            elif isinstance(result, tuple):
                name, ok, _ = result
                if ok:
                    success.append(name)
                else:
                    failed.append(name)

        self._clients_initialized = True
        logger.info(f"Parallel initialization complete; active clients: {len(self._mcp_client_cache)}")
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

        status = self._mcp_server_status.setdefault(server_id, {
            "fail_count": 0,
            "last_error": None,
            "last_init_time": None,
            "circuit_until": None,
        })
        fail_count = status.get("fail_count", 0)
        circuit_until = status.get("circuit_until")
        now = asyncio.get_event_loop().time()
        if circuit_until and now < circuit_until:
            logger.warning(f"Skipping initialization for server {server.name} (circuit open)")
            return None

        client = McpClient(server)

        # Register global health callbacks on new client
        if hasattr(self, '_global_health_callbacks'):
            for callback in self._global_health_callbacks:
                client.register_health_callback(callback)

        try:
            await client.__aenter__()
            if client.get_initialize_state:
                status["fail_count"] = 0
                status["last_error"] = None
                status["last_init_time"] = now
                logger.info(f"Client '{server.name}' initialized successfully")
                return client
            status["fail_count"] += 1
            status["last_error"] = "unknown initialization failure"
            backoff_base = getattr(config, "MCP_INIT_BACKOFF_BASE", 10.0)
            status["circuit_until"] = now + backoff_base * max(1, status["fail_count"])
            logger.error(f"Client '{server.name}' failed to initialize for unknown reasons")
        except (HTTPError, ExceptionGroup, Exception) as e:
            error_detail = _format_exception_group(e)
            logger.error(f"Failed to initialize client for server '{server.name}':\n{error_detail}")
            traceback.print_exc()
            status["fail_count"] = fail_count + 1
            status["last_error"] = str(e)
            # Basic backoff: open circuit for some seconds when failures accumulate
            backoff_base = getattr(config, "MCP_INIT_BACKOFF_BASE", 10.0)
            status["circuit_until"] = now + backoff_base * max(1, status["fail_count"])
        return None

    async def get_or_create_client(self, server_id: str) -> McpClient | None:
        """Get or lazily initialize an MCP client for a given server id.

        Uses per-server locks to prevent race conditions while allowing
        parallel initialization of different servers.
        """
        # Fast path: check cache without lock
        client = self._mcp_client_cache.get(server_id)
        if client is not None:
            logger.debug(f"Client '{client.server.name}' fetched from cache for server ID '{server_id}'")
            return client

        # Get or create per-server lock
        async with self._client_creation_global_lock:
            if server_id not in self._client_creation_locks:
                self._client_creation_locks[server_id] = asyncio.Lock()
            lock = self._client_creation_locks[server_id]

        # Acquire per-server lock for creation
        async with lock:
            # Double-check after acquiring lock (another task may have created it)
            client = self._mcp_client_cache.get(server_id)
            if client is not None:
                logger.debug(f"Client '{client.server.name}' found after lock for server ID '{server_id}'")
                return client

            # Create new client
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

    async def _on_health_status_change(self, server_id: str, status: ClientHealthStatus, error: str | None):
        """Callback for health status changes - extends cache TTL on healthy status."""
        if status == ClientHealthStatus.HEALTHY:
            self._extend_cache_ttl(server_id)

    async def initialize_all_features(self):
        """Initialize clients and hydrate all feature caches sequentially."""
        await self.initialize_clients()

        # Register health callback to extend cache TTL on successful health checks
        self.register_health_callback(self._on_health_status_change)

        for feature in ("tool", "resource", "prompt"):
            # Check if any server needs initial cache load
            needs_init = any(
                self._get_cache_status(sid, feature) in (CacheStatus.MISSING, CacheStatus.EXPIRED)
                for sid in self._mcp_server_cache.keys()
            )
            if needs_init:
                await self._init_features(feature)

        # Start background auto-refresh if enabled
        if config.MCP_ENABLE_AUTO_REFRESH and self._updater_task is None:
            logger.info("Starting background auto-refresh task")
            self.async_updator()

    async def cleanup_clients(self):
        """Clean up all MCP client connections."""
        logger.info("Cleaning up MCP clients...")

        # Signal stop event to terminate async_updator gracefully
        self._stop_event.set()

        # Cancel and await the updater task if it exists
        if self._updater_task is not None:
            try:
                self._updater_task.cancel()
                try:
                    await self._updater_task
                except asyncio.CancelledError:
                    pass
                logger.info("Async updater task cancelled")
            except Exception as e:
                logger.error(f"Error cancelling updater task: {e}")
            finally:
                self._updater_task = None

        for server_id, client in list(self._mcp_client_cache.items()):
            if client and client.get_initialize_state:
                try:
                    logger.info(f"Cleaning up client for server ID: {server_id}")
                    await client.__aexit__(None, None, None)
                except Exception as e:
                    logger.error(f"Error cleaning up client {server_id}: {e}")

        self._mcp_client_cache.clear()
        self._clients_initialized = False
        self._cache_metadata.clear()
        logger.info("All MCP clients cleaned up")

    def get_client(self, server_id: str) -> McpClient | None:
        """Get an existing MCP client by server ID."""
        return self._mcp_client_cache.get(server_id)

    async def _init_features(self, feature_type: str):
        """Initialize/cached features for all servers with bounded concurrency.

        This pulls feature metadata from all available servers and updates local caches.
        """
        success: list[str] = []
        failed: list[str] = []

        for server_id in self._mcp_server_cache.keys():
            server = self._mcp_server_cache.get(server_id)
            client = await self.get_or_create_client(server_id)
            if client and client.get_initialize_state:
                try:
                    await self.cache_mcp_features(feature_type, server_id)
                    await self.refresh(feature_type, server_id)
                    self._update_cache_metadata(server_id, feature_type)
                    success.append(server.name)
                    logger.debug(f"Feature '{feature_type}' init success MCPs: {success}")
                except (HTTPError, ExceptionGroup, Exception) as e:
                    failed.append(server.name)
                    error_detail = _format_exception_group(e)
                    logger.error(f"Feature initialization failed for server '{server.name}', type '{feature_type}':\n{error_detail}")
            else:
                failed.append(server.name)
                logger.error(f"Skipping feature initialization for server '{server.name}' (client not initialized)")

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
        """Send a message to a specific MCP client with per-call timeout and lazy init.

        Uses the new parallel processing API (client.call) for better concurrency.
        Multiple requests to the same server can now be processed in parallel.
        """
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
            # Use new parallel processing API
            response = await client.call(message, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for response from client {client.server.name} for {message.function_name}")
            return None
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            logger.error(f"Error communicating with client {client.server.name}: {e}")
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
        """Asynchronous updater to periodically refresh cached features and vector caches.

        Uses TTL-based refresh: only refreshes servers with stale/expired cache.
        """
        async def _async_updater():
            _features = ['tool', 'resource', 'prompt']
            # Use shorter check interval (e.g., TTL / 2) to catch stale caches promptly
            check_interval = max(60, config.MCP_CACHE_TTL // 2)
            while not self._stop_event.is_set():
                try:
                    # Use wait_for with stop_event to allow graceful shutdown
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=check_interval
                        )
                        # If we get here, stop_event was set
                        break
                    except asyncio.TimeoutError:
                        # Normal timeout, continue with refresh
                        pass
                except Exception as e:  # noqa: BLE001
                    logger.warning("exception while sleeping: ", exc_info=e)
                    continue
                try:
                    for feature in _features:
                        if self._stop_event.is_set():
                            break
                        # Use ensure_feature_cache which handles TTL checks
                        await self.ensure_feature_cache(feature)
                except Exception as e:  # noqa: BLE001
                    logger.warning("exception while updating mcp servers: ", exc_info=e)
            logger.info("Async updater stopped gracefully")
        self._updater_task = asyncio.create_task(_async_updater())

    async def list_tool_names(self):
        """List tool names and descriptions from all MCP clients."""
        await self.ensure_feature_cache("tool")
        tools: list[dict[str, str | None]] = []
        for tool_list in self._mcp_server_tools_cache.values():
            for tool in tool_list:
                tools.append(
                    {
                        "tool_name": getattr(tool, "name", None),
                        "description": getattr(tool, "description", None),
                    }
                )
        return tools

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

    # ==================== Health Status API ====================

    def get_client_health_status(self, server_id: str) -> ClientHealthStatus | None:
        """Get the health status of a specific MCP client.

        Args:
            server_id: The server ID to query

        Returns:
            ClientHealthStatus enum or None if client not found
        """
        client = self._mcp_client_cache.get(server_id)
        if client:
            return client.get_health_status()
        return None

    def get_client_health_info(self, server_id: str) -> ClientHealthInfo | None:
        """Get detailed health information for a specific MCP client.

        Args:
            server_id: The server ID to query

        Returns:
            ClientHealthInfo object or None if client not found
        """
        client = self._mcp_client_cache.get(server_id)
        if client:
            return client.get_health_info()
        return None

    def get_all_clients_health_status(self) -> dict[str, ClientHealthStatus]:
        """Get health status for all configured MCP clients.

        Returns:
            Dictionary mapping server_id to ClientHealthStatus
        """
        status_map: dict[str, ClientHealthStatus] = {}

        for server_id in self._mcp_server_cache.keys():
            client = self._mcp_client_cache.get(server_id)
            if client:
                status_map[server_id] = client.get_health_status()
            else:
                status_map[server_id] = ClientHealthStatus.DISCONNECTED

        return status_map

    def get_all_clients_health_info(self) -> list[ClientHealthInfo]:
        """Get detailed health information for all configured MCP clients.

        Returns:
            List of ClientHealthInfo objects for all servers
        """
        health_info_list: list[ClientHealthInfo] = []

        for server_id, server in self._mcp_server_cache.items():
            client = self._mcp_client_cache.get(server_id)
            if client:
                health_info_list.append(client.get_health_info())
            else:
                # Return basic info for uninitialized clients
                health_info_list.append(ClientHealthInfo(
                    server_id=server_id,
                    server_name=server.name,
                    status=ClientHealthStatus.DISCONNECTED,
                    last_error="Client not initialized"
                ))

        return health_info_list

    def get_healthy_clients(self) -> list[str]:
        """Get list of server IDs for all healthy clients.

        Returns:
            List of server IDs with HEALTHY status
        """
        healthy: list[str] = []
        for server_id, client in self._mcp_client_cache.items():
            if client and client.get_health_status() == ClientHealthStatus.HEALTHY:
                healthy.append(server_id)
        return healthy

    def get_unhealthy_clients(self) -> list[str]:
        """Get list of server IDs for all unhealthy clients.

        Returns:
            List of server IDs with UNHEALTHY or DISCONNECTED status
        """
        unhealthy: list[str] = []
        for server_id in self._mcp_server_cache.keys():
            client = self._mcp_client_cache.get(server_id)
            if not client:
                unhealthy.append(server_id)
            elif client.get_health_status() in (
                ClientHealthStatus.UNHEALTHY,
                ClientHealthStatus.DISCONNECTED
            ):
                unhealthy.append(server_id)
        return unhealthy

    def register_health_callback(self, callback: HealthStatusCallback):
        """Register a callback to be notified of health status changes for all clients.

        The callback will be registered on all existing clients and any new clients
        created in the future.

        Args:
            callback: Async function(server_id, status, error) to be called on status change
        """
        # Store callback for future clients
        if not hasattr(self, '_global_health_callbacks'):
            self._global_health_callbacks: list[HealthStatusCallback] = []
        self._global_health_callbacks.append(callback)

        # Register on existing clients
        for client in self._mcp_client_cache.values():
            client.register_health_callback(callback)

        logger.info("Registered global health callback")

    def unregister_health_callback(self, callback: HealthStatusCallback):
        """Unregister a health status callback from all clients."""
        if hasattr(self, '_global_health_callbacks'):
            try:
                self._global_health_callbacks.remove(callback)
            except ValueError:
                pass

        for client in self._mcp_client_cache.values():
            client.unregister_health_callback(callback)

        logger.info("Unregistered global health callback")

    async def force_reconnect(self, server_id: str) -> bool:
        """Force an immediate reconnection attempt for a specific client.

        Args:
            server_id: The server ID to reconnect

        Returns:
            True if reconnection was initiated, False if client not found
        """
        client = self._mcp_client_cache.get(server_id)
        if client:
            await client.force_reconnect()
            return True
        return False

    async def force_reconnect_all_unhealthy(self) -> list[str]:
        """Force reconnection for all unhealthy clients.

        Returns:
            List of server IDs that had reconnection initiated
        """
        reconnected: list[str] = []
        for server_id in self.get_unhealthy_clients():
            client = self._mcp_client_cache.get(server_id)
            if client:
                await client.force_reconnect()
                reconnected.append(server_id)
        return reconnected

    # ==================== Server Lifecycle Control API ====================

    async def start_server(self, server_id: str) -> dict[str, Any]:
        """Start a specific MCP server by server ID.

        If the server is already running, returns current status.
        Only works for stdio-type servers (local process).

        Args:
            server_id: The server ID to start

        Returns:
            Dict with status information:
            - success: bool
            - server_id: str
            - server_name: str
            - status: str (health status)
            - message: str
        """
        server = self._mcp_server_cache.get(server_id)
        if not server:
            return {
                "success": False,
                "server_id": server_id,
                "server_name": None,
                "status": "not_found",
                "message": f"Server with ID '{server_id}' not found in configuration"
            }

        # Check if client already exists and is initialized
        existing_client = self._mcp_client_cache.get(server_id)
        if existing_client and existing_client.get_initialize_state():
            health_status = existing_client.get_health_status()
            return {
                "success": True,
                "server_id": server_id,
                "server_name": server.name,
                "status": health_status.value,
                "message": f"Server '{server.name}' is already running"
            }

        # Create and initialize the client
        try:
            client = await self.get_or_create_client(server_id)
            if client and client.get_initialize_state():
                # Initialize feature caches for this server
                for feature in ("tool", "resource", "prompt"):
                    try:
                        await self.cache_mcp_features(feature, server_id)
                        await self.refresh(feature, server_id)
                        self._update_cache_metadata(server_id, feature)
                    except Exception as e:
                        logger.warning(f"Failed to cache {feature} for {server.name}: {e}")

                health_status = client.get_health_status()
                logger.info(f"Server '{server.name}' started successfully")
                return {
                    "success": True,
                    "server_id": server_id,
                    "server_name": server.name,
                    "status": health_status.value,
                    "message": f"Server '{server.name}' started successfully"
                }
            else:
                return {
                    "success": False,
                    "server_id": server_id,
                    "server_name": server.name,
                    "status": "failed",
                    "message": f"Failed to initialize server '{server.name}'"
                }
        except Exception as e:
            logger.error(f"Error starting server '{server.name}': {e}")
            return {
                "success": False,
                "server_id": server_id,
                "server_name": server.name,
                "status": "error",
                "message": f"Error starting server: {str(e)}"
            }

    async def stop_server(self, server_id: str) -> dict[str, Any]:
        """Stop a specific MCP server by server ID.

        This will close the client connection and remove it from cache.
        The server configuration remains and can be started again.

        Args:
            server_id: The server ID to stop

        Returns:
            Dict with status information:
            - success: bool
            - server_id: str
            - server_name: str
            - status: str
            - message: str
        """
        server = self._mcp_server_cache.get(server_id)
        if not server:
            return {
                "success": False,
                "server_id": server_id,
                "server_name": None,
                "status": "not_found",
                "message": f"Server with ID '{server_id}' not found in configuration"
            }

        client = self._mcp_client_cache.get(server_id)
        if not client:
            return {
                "success": True,
                "server_id": server_id,
                "server_name": server.name,
                "status": "stopped",
                "message": f"Server '{server.name}' is already stopped"
            }

        try:
            # Gracefully stop the client
            if client.get_initialize_state():
                logger.info(f"Stopping server '{server.name}'...")
                # Mark client as not initialized (signals workers to stop)
                client._initialized = False
                # Update health status
                try:
                    await client._set_health_status(ClientHealthStatus.DISCONNECTED, "Server stopped by user")
                except Exception:
                    pass
                # Clean up underlying streams/session (safer than __aexit__)
                await client.cleanup()

            # Remove from client cache
            self._mcp_client_cache.pop(server_id, None)

            # Clear feature caches for this server
            self._mcp_server_tools_cache.pop(server_id, None)
            self._mcp_server_resources_cache.pop(server_id, None)
            self._mcp_server_prompts_cache.pop(server_id, None)
            self._cache_metadata.pop(server_id, None)

            # Clear vector cache entries for this server
            keys_to_remove = [k for k in self._mcp_vector_cache.keys() if f"-{server_id}-" in k]
            for key in keys_to_remove:
                self._mcp_vector_cache.pop(key, None)

            # Remove per-server lock if exists
            async with self._client_creation_global_lock:
                self._client_creation_locks.pop(server_id, None)

            # Reset circuit breaker status
            self._mcp_server_status.pop(server_id, None)

            logger.info(f"Server '{server.name}' stopped successfully")
            return {
                "success": True,
                "server_id": server_id,
                "server_name": server.name,
                "status": "stopped",
                "message": f"Server '{server.name}' stopped successfully"
            }
        except Exception as e:
            logger.error(f"Error stopping server '{server.name}': {e}")
            return {
                "success": False,
                "server_id": server_id,
                "server_name": server.name,
                "status": "error",
                "message": f"Error stopping server: {str(e)}"
            }

    async def restart_server(self, server_id: str) -> dict[str, Any]:
        """Restart a specific MCP server by server ID.

        This stops the server and starts it again.

        Args:
            server_id: The server ID to restart

        Returns:
            Dict with status information
        """
        server = self._mcp_server_cache.get(server_id)
        if not server:
            return {
                "success": False,
                "server_id": server_id,
                "server_name": None,
                "status": "not_found",
                "message": f"Server with ID '{server_id}' not found in configuration"
            }

        logger.info(f"Restarting server '{server.name}'...")

        # Stop first
        stop_result = await self.stop_server(server_id)
        if not stop_result.get("success") and stop_result.get("status") != "stopped":
            return stop_result

        # Start again
        start_result = await self.start_server(server_id)
        if start_result.get("success"):
            start_result["message"] = f"Server '{server.name}' restarted successfully"
        return start_result

    def get_server_info(self, server_id: str) -> dict[str, Any] | None:
        """Get detailed information about a specific server.

        Args:
            server_id: The server ID to query

        Returns:
            Dict with server information or None if not found
        """
        server = self._mcp_server_cache.get(server_id)
        if not server:
            return None

        client = self._mcp_client_cache.get(server_id)
        is_running = client is not None and client.get_initialize_state()

        health_status = ClientHealthStatus.DISCONNECTED
        health_info = None
        if client:
            health_status = client.get_health_status()
            health_info = client.get_health_info()

        return {
            "server_id": server_id,
            "server_name": server.name,
            "server_type": server.args.type if server.args else None,
            "is_running": is_running,
            "health_status": health_status.value,
            "health_info": health_info.model_dump() if health_info else None,
            "command": server.args.command if server.args else None,
            "url": server.args.url if server.args else None,
        }

    def list_servers(self) -> list[dict[str, Any]]:
        """List all configured servers with their current status.

        Returns:
            List of server information dicts
        """
        servers = []
        for server_id, server in self._mcp_server_cache.items():
            info = self.get_server_info(server_id)
            if info:
                servers.append(info)
        return servers

    def get_server_id_by_name(self, server_name: str) -> str | None:
        """Get server ID by server name.

        Args:
            server_name: The server name to search for

        Returns:
            Server ID or None if not found
        """
        for server_id, server in self._mcp_server_cache.items():
            if server.name == server_name:
                return server_id
        return None

