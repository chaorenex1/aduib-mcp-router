import asyncio

from aduib_mcp_router.app_factory import create_app
from aduib_mcp_router.libs import app_context
from aduib_mcp_router.mcp_factory import MCPFactory
from aduib_mcp_router.mcp_router.router_manager import RouterManager

app=None
if not app:
    app=create_app()

async def run_app():
    router_manager = RouterManager.get_router_manager()
    app.router_manager = router_manager
    mcp_factory = MCPFactory.get_mcp_factory()
    app.mcp=mcp_factory.get_mcp()
    app_context.set(app)
    task= [router_manager.init_mcp_clients(), mcp_factory.run_mcp_server()]
    await asyncio.gather(*task, return_exceptions=True)


def main():
    asyncio.run(run_app())