import asyncio
import logging
from contextlib import AsyncExitStack, AbstractAsyncContextManager
from types import TracebackType
from typing import Any, Optional, Self, Callable, cast

import anyio
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

from aduib_mcp_router.configs import config
from aduib_mcp_router.mcp_router.types import McpServerInfo, ShellEnv, RouteMessage, RouteMessageResult

logger = logging.getLogger(__name__)


class McpClient:
    """A implementation of an MCP client."""

    def __init__(self, server: McpServerInfo):
        self.oauth_auth: Any = None
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

        self._session: Optional[ClientSession] = None
        self._streams_context: Optional[AbstractAsyncContextManager[Any]] = None
        self._session_context: Optional[ClientSession] = None

        # self.exit_stack = ExitStack()
        self.async_exit_stack = AsyncExitStack()

        # Whether the client has been initialized
        self._initialized = False

        self.serverToClientQueue = asyncio.Queue()
        self.clientToServerQueue = asyncio.Queue()

    def get_serverToClientQueue(self) -> asyncio.Queue:
        return self.serverToClientQueue

    def get_clientToServerQueue(self) -> asyncio.Queue:
        return self.clientToServerQueue

    async def __aenter__(self) -> Self:
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        await self._initialize()
        self._message_task = self._task_group.start_soon(self._message_handler)
        self._initialized = True
        logger.debug(f"MCP client {self.server.name} initialized")
        return self

    async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
    ) -> bool | None:
        await self.cleanup()
        # Using BaseSession as a context manager should not block on exit (this
        # would be very surprising behavior), so make sure to cancel the tasks
        # in the task group.
        self._task_group.cancel_scope.cancel()
        logger.debug(f"MCP client {self.server.name} exited")
        return await self._task_group.__aexit__(exc_type, exc_val, exc_tb)

    # def __enter__(self):
    #     self._initialize()
    #     self._initialized = True
    #     return self
    #
    # def __exit__(
    #     self, exc_type: Optional[type], exc_value: Optional[BaseException], traceback: Optional[TracebackType]
    # ):
    #     self.cleanup()

    async def cleanup(self):
        """Clean up resources"""
        self._initialized = False
        try:
            if self._message_task:
                self._message_task.cancel()
                await self._message_task
            # ExitStack will handle proper cleanup of all managed context managers
            await self.async_exit_stack.aclose()
        except Exception as e:
            logging.exception("Error during cleanup")
            raise ValueError(f"Error during cleanup: {e}")
        finally:
            self._session = None
            self._session_context = None
            self._streams_context = None

    async def _initialize(
            self,
    ):
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
        if self.client_type == 'sse':
            logger.debug(f"Connecting to MCP server '{self.server.name}' using SSE at {self.server_url}/sse")
            self._streams_context = client_factory(url=self.server_url + "/sse", headers=self.get_client_header())
        elif self.client_type == 'streamableHttp':
            logger.debug(f"Connecting to MCP server '{self.server.name}' using Streamable HTTP at {self.server_url}/mcp")
            self._streams_context = client_factory(url=self.server_url + "/mcp", headers=self.get_client_header())
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
        return

    async def _message_handler(self):
        """handle messages between client and server"""
        while self._initialized:
            try:
                # from client to server
                if not self.clientToServerQueue.empty():
                    message: RouteMessage = await self.clientToServerQueue.get()
                    await self._send_to_receive(message)
                    self.clientToServerQueue.task_done()

                # from server to client
                # server_message = await self._receive_from_server()
                # if server_message:
                #     await self.serverToClientQueue.put(server_message)

                # avoid busy loop
                await asyncio.sleep(0.01)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Message handler error: {e}")
                await asyncio.sleep(1)  # 错误时等待更长时间

    async def _send_to_receive(self, message: RouteMessage):
        """send message to the server and handle the response"""
        if self._session:
            try:
                result = await self._handle_message(message)
                if result:
                    await self.serverToClientQueue.put(result)
            except Exception as e:
                logger.error(f"Failed to send message to server: {e}")

    async def send_message(self, message: RouteMessage):
        """send a message to the server"""
        await self.clientToServerQueue.put(message)

    async def receive_message(self, timeout: Optional[float] = None) -> Any:
        """receive a message with optional timeout"""
        try:
            if not self._session:
                logger.error("MCP session is not initialized")
                return None

            async def get_message():
                wait_result = True
                while wait_result:
                    try:
                        if not self.serverToClientQueue.empty():
                            msg = await self.serverToClientQueue.get()
                            self.serverToClientQueue.task_done()
                            wait_result = False
                            logger.debug(f"Received message from server: {msg}, wait_result={wait_result}")
                            return msg
                    except Exception as e:
                        logger.error(f"Error receiving message: {e}")
                        wait_result = False
                    await asyncio.sleep(0.01)
                return None

            return await asyncio.wait_for(get_message(), timeout)
        except asyncio.TimeoutError:
            return None

    async def _handle_message(self, message: RouteMessage) -> Optional[RouteMessageResult]:
        """Handle a RouteMessage and return a RouteMessageResult."""
        result = None
        if not self._session:
            logger.error("MCP session is not initialized")
            return result
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
            logger.error(f"Error handling message: {e}")
        return RouteMessageResult(function_name=message.function_name, result=result)

    async def maintain_message_loop(self):
        """maintain the message processing loop"""
        logger.debug(f"Starting message processing loop for server '{self.server.name}'")
        while self._initialized:
            await asyncio.sleep(100)  # 保持运行状态

    def get_client_header(self) -> dict[str, str]:
        """Get the headers for the MCP client."""
        headers = {
            "User-Agent": self.user_agent,
            "Connection": "keep-alive",
            "Keep-Alive": "timeout=30, max=100"
        }
        if self.server.args.env:
            headers.update(self.server.args.env)
        if self.server.args.headers:
            headers.update(self.server.args.headers)
        return headers

    @classmethod
    def build_client(cls, server: McpServerInfo) -> "McpClient":
        """Factory method to create an McpClient instance."""
        return cls(server)
