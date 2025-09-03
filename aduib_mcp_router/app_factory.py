import logging
import os
import time

from aduib_app import AduibAIApp
from aduib_mcp_router.mcp_router.router_manager import RouterManager
from component.log.app_logging import init_logging
from configs import config

log=logging.getLogger(__name__)

def create_app_with_configs()->AduibAIApp:
    """ Create the FastAPI app with necessary configurations and middlewares.
    :return: AduibAIApp instance
    """

    app = AduibAIApp()
    app.config=config
    if config.APP_HOME:
        app.app_home = config.APP_HOME
    else:
        app.app_home = os.getcwd()
    return app


def create_app()->AduibAIApp:
    start_time = time.perf_counter()
    app = create_app_with_configs()
    init_logging(app)
    end_time = time.perf_counter()
    log.info(f"App home directory: {app.app_home}")
    log.info(f"Finished create_app ({round((end_time - start_time) * 1000, 2)} ms)")
    return app

def init_fast_mcp(app: AduibAIApp):
    mcp= None
    if not config.DISCOVERY_SERVICE_ENABLED:
        from fast_mcp import FastMCP
        mcp = FastMCP(name=config.APP_NAME,instructions=config.APP_DESCRIPTION,version=config.APP_VERSION,auth_server_provider=None)
    else:
        if config.DISCOVERY_SERVICE_TYPE=="nacos":
            from nacos_mcp_wrapper.server.nacos_settings import NacosSettings
            nacos_settings = NacosSettings(
                SERVER_ADDR=config.NACOS_SERVER_ADDR,
                NAMESPACE=config.NACOS_NAMESPACE,
                USERNAME=config.NACOS_USERNAME,
                PASSWORD=config.NACOS_PASSWORD,
                SERVICE_GROUP=config.NACOS_GROUP,
                SERVICE_PORT=config.APP_PORT,
                SERVICE_NAME=config.APP_NAME,
                APP_CONN_LABELS={"version": config.APP_VERSION} if config.APP_VERSION else None,
                SERVICE_META_DATA={"transport": config.TRANSPORT_TYPE},
            )
            from nacos_mcp import NacosMCP
            mcp = NacosMCP(name=config.APP_NAME,
                           nacos_settings=nacos_settings,
                           instructions=config.APP_DESCRIPTION,
                           version=config.APP_VERSION,
                           auth_server_provider=None)
    app.mcp = mcp
    from mcp_service import load_mcp_plugins
    load_mcp_plugins("mcp_service")
    RouterManager.init_router_env(app)
    log.info("fast mcp initialized successfully")

async def run_mcp_server(app):
    await app.mcp.run_stdio_async()
