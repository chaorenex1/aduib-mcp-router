import asyncio
import logging
from asyncio import CancelledError
from contextlib import AsyncExitStack, AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import timedelta
from types import TracebackType
from typing import Any, Optional, Self, Callable, cast

import anyio
from httpx import HTTPError
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

from aduib_mcp_router.configs import config
from aduib_mcp_router.mcp_router.types import (
    McpServerInfo, ShellEnv, RouteMessage, RouteMessageResult,
    ClientHealthStatus, ClientHealthInfo, HealthStatusCallback
)

import sys  # needed for error handling in __aenter__
import time

logger = logging.getLogger(__name__)

# Default number of parallel workers per client
DEFAULT_WORKER_COUNT = 5


@dataclass
class PendingRequest:
    """Represents a pending request waiting for response."""
    message: RouteMessage
    event: asyncio.Event = field(default_factory=asyncio.Event)
    result: Optional[RouteMessageResult] = None
    error: Optional[str] = None


class McpClient:
    """A high-performance MCP client with parallel message processing.

    Key features:
    - Parallel message handling with configurable worker count
    - Request-response correlation via unique request IDs
    - Non-blocking send with async response retrieval
    """

    def __init__(self, server: McpServerInfo, worker_count: int = DEFAULT_WORKER_COUNT):
        self.oauth_auth: Any = None
        self.server_url: str = ""
        if server.args.url:
            self.server_url = server.args.url
            if self.server_url.endswith("/"):
                self.server_url = self.server_url[:-1]
        if server.args.type:
            logger.debug(f"MCP server name '{server.name}' using type '{server.args.type}'")
            self.client_type = server.args.type
        else:
            logger.debug(f"MCP server name '{server.name}' using type '{server.args.type}'")
            self.client_type = 'stdio'  # 'stdio', 'sse', 'streamable'
        self.server = server
        self.user_agent = config.DEFAULT_USER_AGENT
        self.worker_count = worker_count

        self._session: Optional[ClientSession] = None
        self._streams_context: Optional[AbstractAsyncContextManager[Any]] = None
        self._session_context: Optional[ClientSession] = None

        # Task group managing background tasks (e.g. message handler)
        self._task_group: anyio.abc.TaskGroup | None = None

        # AsyncExitStack to manage underlying stream/session contexts
        self.async_exit_stack = AsyncExitStack()

        # Whether the client has been initialized
        self._initialized = False

        # Message queue for incoming requests
        self._request_queue: asyncio.Queue[RouteMessage] = asyncio.Queue()

        # Pending requests map: request_id -> PendingRequest
        self._pending_requests: dict[str, PendingRequest] = {}
        self._pending_lock = asyncio.Lock()

        # Semaphore to limit concurrent MCP session calls
        self._session_semaphore = asyncio.Semaphore(worker_count)

        # Legacy queues for backward compatibility (deprecated)
        self.serverToClientQueue = asyncio.Queue()
        self.clientToServerQueue = asyncio.Queue()

        # ==================== Health Check State ====================
        self._health_status: ClientHealthStatus = ClientHealthStatus.DISCONNECTED
        self._consecutive_failures: int = 0
        self._total_requests: int = 0
        self._total_failures: int = 0
        self._last_ping_time: Optional[float] = None  # timestamp
        self._last_success_time: Optional[float] = None  # timestamp
        self._last_error: Optional[str] = None
        self._last_latency_ms: Optional[float] = None
        self._connection_start_time: Optional[float] = None  # for uptime calculation

        # Health check configuration from config
        self._health_check_interval: int = config.MCP_HEALTH_CHECK_INTERVAL
        self._health_check_timeout: int = config.MCP_HEALTH_CHECK_TIMEOUT
        self._max_consecutive_failures: int = config.MCP_MAX_CONSECUTIVE_FAILURES
        self._auto_reconnect: bool = config.MCP_AUTO_RECONNECT
        self._reconnect_delay: int = config.MCP_RECONNECT_DELAY

        # Health status change callbacks
        self._health_callbacks: list[HealthStatusCallback] = []
        self._health_callback_lock = asyncio.Lock()

        # Reconnection state
        self._reconnecting = False
        self._reconnect_attempts = 0

    def get_serverToClientQueue(self) -> asyncio.Queue:
        """Deprecated: Use send_request() and wait_response() instead."""
        return self.serverToClientQueue

    def get_clientToServerQueue(self) -> asyncio.Queue:
        """Deprecated: Use send_request() and wait_response() instead."""
        return self.clientToServerQueue

    def is_initialized(self) -> bool:
        return self._initialized

    async def __aenter__(self) -> Self:
        # Create and enter the anyio TaskGroup in this task
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()

        # Update health status to connecting
        await self._set_health_status(ClientHealthStatus.CONNECTING)

        try:
            # Initialize underlying MCP connection/session
            await self._initialize()

            # Start parallel message workers
            for i in range(self.worker_count):
                self._task_group.start_soon(self._worker, i)

            # Start legacy message handler for backward compatibility
            self._task_group.start_soon(self._legacy_message_handler)

            # Start health check task
            self._task_group.start_soon(self._health_checker)

            self._initialized = True
            self._connection_start_time = time.time()
            self._last_success_time = time.time()
            self._consecutive_failures = 0
            self._reconnect_attempts = 0

            # Update health status to healthy
            await self._set_health_status(ClientHealthStatus.HEALTHY)

            logger.debug(f"MCP client {self.server.name} initialized with {self.worker_count} workers")
            return self
        except (Exception, CancelledError):
            # If initialization fails, ensure proper cleanup in this task
            self._initialized = False
            await self._set_health_status(ClientHealthStatus.DISCONNECTED, "Initialization failed")
            try:
                await self.cleanup()
            finally:
                if self._task_group is not None:
                    # Use the current exception info to exit the task group cleanly
                    exc_type, exc_val, exc_tb = sys.exc_info()
                    await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
                    self._task_group = None
            logger.error(f"MCP client {self.server.name} failed to initialize")

    async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
    ) -> bool | None:
        # Signal message loop to stop
        self._initialized = False

        # Update health status to disconnected
        await self._set_health_status(ClientHealthStatus.DISCONNECTED, "Client shutting down")

        # Cancel all pending requests
        async with self._pending_lock:
            for request_id, pending in self._pending_requests.items():
                pending.error = "Client shutting down"
                pending.event.set()
            self._pending_requests.clear()

        # Request cancellation of all tasks in the task group
        if self._task_group is not None:
            try:
                self._task_group.cancel_scope.cancel()
            except Exception:
                logger.exception("Error cancelling task group cancel_scope")

        # First, let the task group finish its tasks and exit
        tg_result: bool | None = None
        if self._task_group is not None:
            try:
                tg_result = await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
            finally:
                self._task_group = None

        # Then cleanup underlying streams/session via AsyncExitStack
        await self.cleanup()

        logger.debug(f"MCP client {self.server.name} exited")
        return tg_result

    async def cleanup(self):
        """Clean up resources (streams/session) without managing task group."""
        try:
            # ExitStack will handle proper cleanup of all managed context managers
            await self.async_exit_stack.aclose()
        except (Exception, CancelledError, HTTPError):
            logger.exception("Error during cleanup")
        finally:
            self._session = None
            self._session_context = None
            self._streams_context = None

    def get_initialize_state(self) -> bool:
        """Get the client initialization state."""
        return self._initialized

    async def _initialize(self):
        """Initialize the client with fallback to SSE if streamable connection fails"""
        connection_methods: dict[str, Callable[..., AbstractAsyncContextManager[Any]]] = {
            "streamableHttp": streamablehttp_client,
            "sse": sse_client,
            "stdio": stdio_client,
        }

        method_name = self.client_type
        if method_name in connection_methods:
            client_factory = connection_methods[method_name]
            await self.connect_server(client_factory, method_name)
        else:
            logger.error(f"Unknown client type '{method_name}'")
            raise RuntimeError(f"Unknown client type '{method_name}'")

    async def connect_server(
            self, client_factory: Callable[..., AbstractAsyncContextManager[Any]], method_name: str
    ):
        connection_timeout = config.MCP_CONNECTION_TIMEOUT
        if self.client_type == 'sse':
            logger.debug(f"Connecting to MCP server '{self.server.name}' using SSE at {self.server_url}/sse")
            self._streams_context = client_factory(url=self.server_url + "/sse", headers=self.get_client_header(), timeout=connection_timeout)
        elif self.client_type == 'streamableHttp':
            logger.debug(f"Connecting to MCP server '{self.server.name}' using Streamable HTTP at {self.server_url}/mcp")
            self._streams_context = client_factory(url=self.server_url + "/mcp", headers=self.get_client_header(), timeout=timedelta(seconds=connection_timeout))
        else:
            from aduib_mcp_router.mcp_router.router_manager import RouterManager
            sell_env: ShellEnv = RouterManager.get_shell_env(args=self.server.args)
            server_params = StdioServerParameters(
                command=sell_env.command_run,
                args=sell_env.args,
                env=sell_env.env,
            )
            logger.debug(f"Connecting to MCP server '{self.server.name}' using stdio with command: {sell_env.command_run} {' '.join(sell_env.args)}")
            self._streams_context = client_factory(server_params)
        if not self._streams_context:
            raise RuntimeError("Failed to create streams context")

        if method_name == "streamableHttp":
            read_stream, write_stream, _ = await self.async_exit_stack.enter_async_context(self._streams_context)
            streams = (read_stream, write_stream)
        else:
            streams = await self.async_exit_stack.enter_async_context(self._streams_context)

        self._session_context = ClientSession(*streams)
        self._session = await self.async_exit_stack.enter_async_context(self._session_context)
        session = cast(ClientSession, self._session)
        await session.initialize()

    # ==================== New Parallel Processing API ====================

    async def send_request(self, message: RouteMessage) -> str:
        """Send a request and return the request_id for later retrieval.

        This is non-blocking - use wait_response() to get the result.

        Returns:
            request_id: The unique identifier to retrieve the response
        """
        request_id = message.request_id
        pending = PendingRequest(message=message)

        async with self._pending_lock:
            self._pending_requests[request_id] = pending

        await self._request_queue.put(message)
        return request_id

    async def wait_response(self, request_id: str, timeout: Optional[float] = None) -> Optional[RouteMessageResult]:
        """Wait for and retrieve the response for a given request_id.

        Args:
            request_id: The ID returned by send_request()
            timeout: Maximum time to wait in seconds (None = wait forever)

        Returns:
            RouteMessageResult or None if timeout/error
        """
        async with self._pending_lock:
            pending = self._pending_requests.get(request_id)

        if pending is None:
            logger.error(f"Request {request_id} not found in pending requests")
            return None

        try:
            if timeout is not None:
                await asyncio.wait_for(pending.event.wait(), timeout=timeout)
            else:
                await pending.event.wait()
        except asyncio.TimeoutError:
            logger.warning(f"Request {request_id} timed out after {timeout}s")
            async with self._pending_lock:
                self._pending_requests.pop(request_id, None)
            return None

        # Cleanup and return result
        async with self._pending_lock:
            self._pending_requests.pop(request_id, None)

        if pending.error:
            return RouteMessageResult(
                request_id=request_id,
                function_name=pending.message.function_name,
                result=None,
                error=pending.error
            )

        return pending.result

    async def call(self, message: RouteMessage, timeout: Optional[float] = None) -> Optional[RouteMessageResult]:
        """Convenience method: send request and wait for response in one call.

        This is the recommended way to make a synchronous-style call.

        Args:
            message: The RouteMessage to send
            timeout: Maximum time to wait in seconds

        Returns:
            RouteMessageResult or None if timeout/error
        """
        request_id = await self.send_request(message)
        return await self.wait_response(request_id, timeout)

    async def _worker(self, worker_id: int):
        """Worker coroutine that processes messages from the queue in parallel."""
        logger.debug(f"Worker {worker_id} started for server '{self.server.name}'")

        while self._initialized:
            try:
                # Wait for a message from the queue
                try:
                    message = await asyncio.wait_for(
                        self._request_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                # Process the message with semaphore to limit concurrent session calls
                async with self._session_semaphore:
                    await self._process_request(message)

                self._request_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                await asyncio.sleep(0.1)

        logger.debug(f"Worker {worker_id} stopped for server '{self.server.name}'")

    async def _process_request(self, message: RouteMessage):
        """Process a single request and signal completion."""
        request_id = message.request_id

        async with self._pending_lock:
            pending = self._pending_requests.get(request_id)

        if pending is None:
            logger.warning(f"Pending request {request_id} not found, may have been cancelled")
            return

        try:
            result = await self._handle_message(message)
            if result:
                result.request_id = request_id
            pending.result = result
        except Exception as e:
            logger.error(f"Error processing request {request_id}: {e}")
            pending.error = str(e)
        finally:
            pending.event.set()

    async def _handle_message(self, message: RouteMessage) -> Optional[RouteMessageResult]:
        """Handle a RouteMessage and return a RouteMessageResult."""
        result = None
        if not self._session:
            logger.error("MCP session is not initialized")
            return RouteMessageResult(
                request_id=message.request_id,
                function_name=message.function_name,
                result=None,
                error="MCP session is not initialized"
            )
        try:
            if message.function_name == 'list_tools':
                resp = await self._session.list_tools()
                result = resp.tools
            elif message.function_name == 'call_tool':
                resp = await self._session.call_tool(
                    name=message.args[0],
                    arguments=message.args[1]
                )
                result = resp.content
            elif message.function_name == 'list_prompts':
                resp = await self._session.list_prompts()
                result = resp.prompts
            elif message.function_name == 'get_prompt':
                resp = await self._session.get_prompt(name=message.args[0])
                result = resp.messages
            elif message.function_name == 'list_resources':
                resp = await self._session.list_resources()
                result = resp.resources
            elif message.function_name == 'list_resource_templates':
                resp = await self._session.list_resource_templates()
                result = resp.resourceTemplates
            elif message.function_name == 'read_resource':
                resp = await self._session.read_resource(uri=message.args[0])
                result = resp.contents
        except Exception as e:
            logger.error(f"Error handling message: {e}, function: {message.function_name}, args: {message.args}")
            return RouteMessageResult(
                request_id=message.request_id,
                function_name=message.function_name,
                result=None,
                error=str(e)
            )
        return RouteMessageResult(
            request_id=message.request_id,
            function_name=message.function_name,
            result=result
        )

    # ==================== Legacy API (Backward Compatibility) ====================

    async def _legacy_message_handler(self):
        """Legacy message handler for backward compatibility with queue-based API."""
        while self._initialized:
            try:
                try:
                    message: RouteMessage = await asyncio.wait_for(
                        self.clientToServerQueue.get(),
                        timeout=1.0
                    )
                    await self._legacy_send_to_receive(message)
                    self.clientToServerQueue.task_done()
                except asyncio.TimeoutError:
                    continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Legacy message handler error: {e}")
                await asyncio.sleep(1)

    async def _legacy_send_to_receive(self, message: RouteMessage):
        """Legacy: send message to the server and handle the response via queue."""
        if self._session:
            try:
                result = await self._handle_message(message)
                if result:
                    await self.serverToClientQueue.put(result)
            except Exception as e:
                logger.error(f"Failed to send message to server: {e}")

    async def send_message(self, message: RouteMessage):
        """Legacy: send a message to the server via queue.

        Deprecated: Use send_request() and wait_response() for better performance.
        """
        await self.clientToServerQueue.put(message)

    async def receive_message(self, timeout: Optional[float] = None) -> Any:
        """Legacy: receive a message with optional timeout.

        Deprecated: Use send_request() and wait_response() for better performance.
        """
        try:
            if not self._session:
                logger.error("MCP session is not initialized")
                return None

            msg = await asyncio.wait_for(self.serverToClientQueue.get(), timeout=timeout)
            self.serverToClientQueue.task_done()
            return msg
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"Error receiving message: {e}")
            return None

    async def maintain_message_loop(self):
        """Maintain the message processing loop (legacy, kept for compatibility)."""
        logger.debug(f"Starting message processing loop for server '{self.server.name}'")
        stop_event = asyncio.Event()
        while self._initialized:
            await stop_event.wait()

    def get_client_header(self) -> dict[str, str]:
        """Get the headers for the MCP client."""
        keep_alive_timeout = config.MCP_KEEP_ALIVE_TIMEOUT
        keep_alive_max = config.MCP_KEEP_ALIVE_MAX
        headers = {
            "User-Agent": self.user_agent,
            "Connection": "keep-alive",
            "Keep-Alive": f"timeout={keep_alive_timeout}, max={keep_alive_max}"
        }
        if self.server.args.env:
            headers.update(self.server.args.env)
        if self.server.args.headers:
            headers.update(self.server.args.headers)
        return headers

    @classmethod
    def build_client(cls, server: McpServerInfo, worker_count: int = DEFAULT_WORKER_COUNT) -> "McpClient":
        """Factory method to create an McpClient instance."""
        return cls(server, worker_count)

    # ==================== Health Check API ====================

    async def _set_health_status(self, status: ClientHealthStatus, error: Optional[str] = None):
        """Update health status and notify callbacks."""
        old_status = self._health_status
        self._health_status = status

        if error:
            self._last_error = error

        # Only trigger callbacks if status actually changed
        if old_status != status:
            logger.info(f"MCP client '{self.server.name}' health status: {old_status.value} -> {status.value}")
            await self._notify_health_callbacks(status, error)

    async def _notify_health_callbacks(self, status: ClientHealthStatus, error: Optional[str] = None):
        """Notify all registered health status callbacks."""
        async with self._health_callback_lock:
            callbacks = list(self._health_callbacks)

        server_id = self.server.id or self.server.name
        for callback in callbacks:
            try:
                await callback(server_id, status, error)
            except Exception as e:
                logger.error(f"Error in health callback for '{self.server.name}': {e}")

    def register_health_callback(self, callback: HealthStatusCallback):
        """Register a callback to be notified of health status changes.

        Args:
            callback: Async function(server_id, status, error) to be called on status change
        """
        self._health_callbacks.append(callback)
        logger.debug(f"Registered health callback for '{self.server.name}'")

    def unregister_health_callback(self, callback: HealthStatusCallback):
        """Unregister a health status callback."""
        try:
            self._health_callbacks.remove(callback)
            logger.debug(f"Unregistered health callback for '{self.server.name}'")
        except ValueError:
            pass

    def get_health_status(self) -> ClientHealthStatus:
        """Get current health status."""
        return self._health_status

    def get_health_info(self) -> ClientHealthInfo:
        """Get detailed health information."""
        from datetime import datetime

        uptime = None
        if self._connection_start_time and self._health_status in (
            ClientHealthStatus.HEALTHY, ClientHealthStatus.DEGRADED
        ):
            uptime = time.time() - self._connection_start_time

        return ClientHealthInfo(
            server_id=self.server.id or self.server.name,
            server_name=self.server.name,
            status=self._health_status,
            last_ping_time=datetime.fromtimestamp(self._last_ping_time) if self._last_ping_time else None,
            last_success_time=datetime.fromtimestamp(self._last_success_time) if self._last_success_time else None,
            last_error=self._last_error,
            consecutive_failures=self._consecutive_failures,
            total_requests=self._total_requests,
            total_failures=self._total_failures,
            latency_ms=self._last_latency_ms,
            uptime_seconds=uptime
        )

    async def _health_checker(self):
        """Background task that performs periodic health checks (heartbeat)."""
        logger.debug(f"Health checker started for '{self.server.name}' (interval: {self._health_check_interval}s)")

        while self._initialized:
            try:
                # Wait for the health check interval
                await asyncio.sleep(self._health_check_interval)

                if not self._initialized:
                    break

                # Skip health check if we're currently reconnecting
                if self._reconnecting:
                    continue

                # Perform ping/health check
                await self._perform_health_check()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health checker error for '{self.server.name}': {e}")
                await asyncio.sleep(5)  # Brief delay before continuing

        logger.debug(f"Health checker stopped for '{self.server.name}'")

    async def _perform_health_check(self):
        """Perform a single health check (ping) on the MCP session."""
        if not self._session:
            await self._record_failure("No active session")
            return

        self._last_ping_time = time.time()
        self._total_requests += 1
        start_time = time.time()

        try:
            # Use list_tools as a lightweight health check ping
            await asyncio.wait_for(
                self._session.list_tools(),
                timeout=self._health_check_timeout
            )

            # Success - record metrics
            latency_ms = (time.time() - start_time) * 1000
            self._last_latency_ms = latency_ms
            self._last_success_time = time.time()
            self._consecutive_failures = 0
            self._last_error = None

            # Update status if we were degraded
            if self._health_status == ClientHealthStatus.DEGRADED:
                await self._set_health_status(ClientHealthStatus.HEALTHY)

            logger.debug(f"Health check OK for '{self.server.name}' (latency: {latency_ms:.1f}ms)")

        except asyncio.TimeoutError:
            await self._record_failure(f"Health check timeout ({self._health_check_timeout}s)")
        except Exception as e:
            await self._record_failure(str(e))

    async def _record_failure(self, error: str):
        """Record a health check failure and update status accordingly."""
        self._consecutive_failures += 1
        self._total_failures += 1
        self._last_error = error

        logger.warning(
            f"Health check failed for '{self.server.name}': {error} "
            f"(consecutive: {self._consecutive_failures}/{self._max_consecutive_failures})"
        )

        # Determine new status based on failure count
        if self._consecutive_failures >= self._max_consecutive_failures:
            # Client is unhealthy - trigger reconnect if enabled
            await self._set_health_status(ClientHealthStatus.UNHEALTHY, error)

            if self._auto_reconnect and not self._reconnecting:
                # Schedule reconnection in the background
                if self._task_group:
                    self._task_group.start_soon(self._attempt_reconnect)
        elif self._consecutive_failures >= 1:
            # Client is degraded but still operational
            if self._health_status == ClientHealthStatus.HEALTHY:
                await self._set_health_status(ClientHealthStatus.DEGRADED, error)

    async def _attempt_reconnect(self):
        """Attempt to reconnect the MCP client."""
        if self._reconnecting:
            return

        self._reconnecting = True
        self._reconnect_attempts += 1

        logger.info(
            f"Attempting reconnection for '{self.server.name}' "
            f"(attempt #{self._reconnect_attempts})"
        )

        await self._set_health_status(ClientHealthStatus.CONNECTING)

        try:
            # Wait before reconnecting (with exponential backoff)
            delay = min(self._reconnect_delay * (2 ** (self._reconnect_attempts - 1)), 300)
            logger.debug(f"Waiting {delay}s before reconnection for '{self.server.name}'")
            await asyncio.sleep(delay)

            # Cleanup existing resources
            await self.cleanup()

            # Reset exit stack for new connection
            self.async_exit_stack = AsyncExitStack()

            # Attempt to re-initialize
            await self._initialize()

            # Success - update state
            self._connection_start_time = time.time()
            self._last_success_time = time.time()
            self._consecutive_failures = 0
            self._last_error = None

            await self._set_health_status(ClientHealthStatus.HEALTHY)
            logger.info(f"Reconnection successful for '{self.server.name}'")

            # Reset reconnect attempts on success
            self._reconnect_attempts = 0

        except Exception as e:
            error_msg = f"Reconnection failed: {e}"
            logger.error(f"Reconnection failed for '{self.server.name}': {e}")
            await self._set_health_status(ClientHealthStatus.UNHEALTHY, error_msg)

            # Schedule another reconnect attempt if still unhealthy
            if self._auto_reconnect and self._initialized:
                if self._task_group:
                    self._task_group.start_soon(self._attempt_reconnect)
        finally:
            self._reconnecting = False

    async def force_reconnect(self):
        """Force an immediate reconnection attempt.

        This can be called externally to trigger reconnection regardless of
        current health status.
        """
        logger.info(f"Forcing reconnection for '{self.server.name}'")
        self._consecutive_failures = self._max_consecutive_failures
        await self._record_failure("Forced reconnection requested")
