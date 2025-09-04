import asyncio

from aduib_mcp_router.mcp_router.router_manager import RouterManager
from app_factory import create_app, init_fast_mcp, run_mcp_server

app=None
if not app:
    app=create_app()

async def main():

    router_manager = RouterManager.get_router_manager(app)
    app.extensions['router']=router_manager
    init_fast_mcp(app)
    task= [router_manager.init_mcp_clients(app), run_mcp_server(app)]
    await asyncio.gather(*task)