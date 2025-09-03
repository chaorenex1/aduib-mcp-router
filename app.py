import asyncio
from multiprocessing.spawn import freeze_support

from app_factory import create_app, app_context, init_fast_mcp, run_mcp_server
from nacos_mcp import NacosMCP

app=None
if not app_context.get():
    app=create_app()

async def main(**kwargs):
    init_fast_mcp(app)
    import uvicorn
    config = uvicorn.Config(app=app, host=app.config.APP_HOST, port=app.config.APP_PORT, **kwargs)
    if isinstance(app.mcp,NacosMCP):
        await app.mcp.register_service(app.config.TRANSPORT_TYPE)
    run_mcp_server(app)
    await uvicorn.Server(config).serve()


if __name__ == '__main__':
    freeze_support()
    asyncio.run(main())