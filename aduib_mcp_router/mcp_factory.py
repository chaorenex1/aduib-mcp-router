import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from aduib_mcp_router.configs import config
from .fast_mcp import FastMCP
log=logging.getLogger(__name__)

class MCPFactory:
    """ Factory class to create and manage FastMCP instances."""
    def __init__(self):
        self.mcp = self.init_fast_mcp()
        self.router_manager = None

    def get_mcp(self)->FastMCP:
        return self.mcp

    @classmethod
    def get_mcp_factory(cls)->'MCPFactory':
        return cls()

    def set_router_manager(self, router_manager):
        """Set the router manager for lifecycle management."""
        self.router_manager = router_manager

    @asynccontextmanager
    async def create_lifespan(self, mcp: FastMCP) -> AsyncIterator[None]:
        """Lifespan context manager for MCP client initialization and cleanup."""
        log.info("Starting MCP application lifespan...")

        # Initialize MCP clients on startup
        if self.router_manager:
            log.info("Initializing MCP clients and feature caches...")
            await self.router_manager.initialize_all_features()
            log.info("MCP clients and features initialized successfully")

        try:
            yield
        finally:
            # Cleanup MCP clients on shutdown
            if self.router_manager:
                log.info("Cleaning up MCP clients...")
                await self.router_manager.cleanup_clients()
                log.info("MCP clients cleaned up successfully")

    def init_fast_mcp(self)->FastMCP:
        mcp= None
        if not config.DISCOVERY_SERVICE_ENABLED:
            from aduib_mcp_router.fast_mcp import FastMCP
            from aduib_mcp_router.libs.api_key_auth import ApiKeyAuthorizationServerProvider
            mcp = FastMCP(
                name=config.APP_NAME,
                instructions=config.APP_DESCRIPTION,
                version=config.APP_VERSION,
                auth_server_provider=ApiKeyAuthorizationServerProvider() if config.AUTH_ENABLED else None,
                lifespan=self.create_lifespan
            )
        else:
            if config.DISCOVERY_SERVICE_TYPE=="nacos":
                from nacos_mcp_wrapper.server.nacos_settings import NacosSettings
                nacos_settings = NacosSettings(
                    SERVER_ADDR=config.NACOS_SERVER_ADDR if config.NACOS_SERVER_ADDR else os.environ.get("NACOS_SERVER_ADDR"),
                    NAMESPACE=config.NACOS_NAMESPACE if config.NACOS_NAMESPACE else os.environ.get("NACOS_NAMESPACE"),
                    USERNAME=config.NACOS_USERNAME if config.NACOS_USERNAME else os.environ.get("NACOS_USERNAME"),
                    PASSWORD=config.NACOS_PASSWORD if config.NACOS_PASSWORD else os.environ.get("NACOS_PASSWORD"),
                    SERVICE_GROUP=config.NACOS_GROUP if config.NACOS_GROUP else os.environ.get("NACOS_GROUP", "DEFAULT_GROUP"),
                    SERVICE_PORT=config.APP_PORT,
                    SERVICE_NAME=config.APP_NAME,
                    APP_CONN_LABELS={"version": config.APP_VERSION} if config.APP_VERSION else None,
                    SERVICE_META_DATA={"transport": config.TRANSPORT_TYPE},
                )
                from nacos_mcp import NacosMCP
                from aduib_mcp_router.libs.api_key_auth import ApiKeyAuthorizationServerProvider
                mcp = NacosMCP(
                    name=config.APP_NAME,
                    nacos_settings=nacos_settings,
                    instructions=config.APP_DESCRIPTION,
                    version=config.APP_VERSION,
                    auth_server_provider=ApiKeyAuthorizationServerProvider() if config.AUTH_ENABLED else None,
                    lifespan=self.create_lifespan
                )
        log.info("fast mcp initialized successfully")
        return mcp

    async def run_mcp_server(self):
        from aduib_mcp_router.mcp_service import load_mcp_plugins
        load_mcp_plugins("aduib_mcp_router.mcp_service")
        if not self.mcp:
            log.warning("MCP is not initialized, skipping MCP server startup.")
            return
        if config.TRANSPORT_TYPE == "stdio":
            await self.mcp.run_stdio_async()
        elif config.TRANSPORT_TYPE == "sse":
            await self.mcp.run_sse_async()
        elif config.TRANSPORT_TYPE == "streamable-http":
            await self.mcp.run_streamable_http_async()
        else:
            log.error(f"Unsupported TRANSPORT_TYPE: {config.TRANSPORT_TYPE}")
