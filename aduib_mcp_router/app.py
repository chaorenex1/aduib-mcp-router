import asyncio

from aduib_mcp_router.app_factory import create_app
from aduib_mcp_router.libs import app_context
from aduib_mcp_router.mcp_router.router_manager import RouterManager

app=None
if not app:
    app=create_app()


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

    # Run the MCP server (lifespan will handle client initialization and cleanup)
    await mcp_factory.run_mcp_server()

# async def run_app():
#     router_manager = RouterManager.get_router_manager()
#     app.router_manager = router_manager
#     app_context.set(app)
#     callbacks= [run_mcp_server, router_manager.async_updator]
#     await router_manager.run_mcp_clients(callbacks=callbacks)


def main():
    asyncio.run(run_mcp_server())