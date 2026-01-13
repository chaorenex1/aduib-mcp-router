import asyncio
import logging

from aduib_mcp_router.app_factory import create_app
from aduib_mcp_router.libs import app_context
from aduib_mcp_router.mcp_router.router_manager import RouterManager

app=None
if not app:
    app=create_app()

# Event to signal when router_manager is initialized
_router_initialized = asyncio.Event()


async def run_mcp_server():
    """Run the MCP server."""
    from aduib_mcp_router.mcp_factory import MCPFactory

    mcp_factory = MCPFactory.get_mcp_factory()
    mcp=mcp_factory.get_mcp()
    app.mcp = mcp

    router_manager = RouterManager.get_router_manager()
    app.router_manager = router_manager
    app_context.set(app)

    # Set router manager on factory for lifespan management
    mcp_factory.set_router_manager(router_manager)

    # Signal that router_manager is now initialized
    _router_initialized.set()

    # Run the MCP server (lifespan will handle client initialization and cleanup)
    await mcp_factory.run_mcp_server()


async def warmup_router():
    """Initialize router manager clients/features after app startup."""
    # Wait for router_manager to be initialized before proceeding
    try:
        await asyncio.wait_for(_router_initialized.wait(), timeout=30.0)
    except asyncio.TimeoutError:
        logging.getLogger(__name__).error("Timeout waiting for router_manager initialization")
        return

    if not app or not app.router_manager:
        return
    try:
        await app.router_manager.initialize_all_features()
    except Exception as exc:  # noqa: BLE001
        # Log warmup errors but don't crash the application
        logging.getLogger(__name__).error("Router warmup failed: %s", exc, exc_info=exc)


def main():
    async def runner():
        # Reset event for fresh run
        _router_initialized.clear()
        # Start MCP server and warmup concurrently
        # warmup_router will wait for _router_initialized before proceeding
        server_task = asyncio.create_task(run_mcp_server())
        warmup_task = asyncio.create_task(warmup_router())
        await server_task
        await warmup_task

    asyncio.run(runner())
