from aduib_mcp_router.mcp_router.router_manager import RouterManager
from app_factory import create_app, init_fast_mcp, run_mcp_server
from nacos_mcp import NacosMCP

app=None
if not app:
    app=create_app()

async def main():

    init_fast_mcp(app)
    if isinstance(app.mcp,NacosMCP):
        await app.mcp.register_service(app.config.TRANSPORT_TYPE)
    await RouterManager.init_mcp_clients(app)
    await run_mcp_server(app)