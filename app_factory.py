import contextlib
import logging
import os
import time
from contextvars import ContextVar
from typing import AsyncIterator

from fastapi.routing import APIRoute

from aduib_app import AduibAIApp
from component.cache.redis_cache import init_cache
from component.log.app_logging import init_logging
from configs import config
from controllers.route import api_router
from libs.api_key_auth import ApiKeyAuthorizationServerProvider
from libs.context import LoggingMiddleware, TraceIdContextMiddleware, ApiKeyContextMiddleware
from libs.contextVar_wrapper import ContextVarWrappers
from mcp_service import load_mcp_plugins

log=logging.getLogger(__name__)

app_context: ContextVarWrappers[AduibAIApp]=ContextVarWrappers(ContextVar("app_context"))


def create_app_with_configs()->AduibAIApp:
    """ Create the FastAPI app with necessary configurations and middlewares.
    :return: AduibAIApp instance
    """
    if app_context.get():
        return app_context.get()
    def custom_generate_unique_id(route: APIRoute) -> str:
        return f"{route.tags[0]}-{route.name}"

    app = AduibAIApp(
        title=config.APP_NAME,
        generate_unique_id_function=custom_generate_unique_id,
        debug=config.DEBUG,
        lifespan=lifespan if config.TRANSPORT_TYPE == "streamable-http" else None,
    )
    app.config=config
    if config.APP_HOME:
        app.app_home = config.APP_HOME
    else:
        app.app_home = os.getcwd()
    app.include_router(api_router)
    if config.AUTH_ENABLED:
        app.add_middleware(ApiKeyContextMiddleware)
    if config.DEBUG:
        log.warning("Running in debug mode, this is not recommended for production use.")
        app.add_middleware(LoggingMiddleware)
    app.add_middleware(TraceIdContextMiddleware)
    app_context.set(app)
    return app


def create_app()->AduibAIApp:
    start_time = time.perf_counter()
    app = create_app_with_configs()
    init_logging(app)
    init_apps(app)
    end_time = time.perf_counter()
    log.info(f"App home directory: {app.app_home}")
    log.info(f"Finished create_app ({round((end_time - start_time) * 1000, 2)} ms)")
    return app


def init_apps(app: AduibAIApp):
    """
    Initialize the app with necessary configurations and middlewares.
    :param app: AduibAIApp instance
    """
    log.info("Initializing middlewares")
    init_cache(app)
    log.info("middlewares initialized successfully")

def init_fast_mcp(app: AduibAIApp):
    global mcp
    if not config.DISCOVERY_SERVICE_ENABLED:
        from fast_mcp import FastMCP
        mcp = FastMCP(name=config.APP_NAME,instructions=config.APP_DESCRIPTION,version=config.APP_VERSION,auth_server_provider=ApiKeyAuthorizationServerProvider() if config.AUTH_ENABLED else None)
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
                           auth_server_provider=ApiKeyAuthorizationServerProvider() if config.AUTH_ENABLED else None)
    app.mcp = mcp
    load_mcp_plugins("mcp_service")
    log.info("fast mcp initialized successfully")

def run_mcp_server(app):
    if config.TRANSPORT_TYPE == "stdio":
        app.mcp.run(transport=config.TRANSPORT_TYPE)
    elif config.TRANSPORT_TYPE == "sse":
        app.mount("/", app.mcp.sse_app(), name="mcp_see")
    elif config.TRANSPORT_TYPE == "streamable-http":
        app.mount("/", app.mcp.streamable_http_app(), name="mcp_streamable_http")


@contextlib.asynccontextmanager
async def lifespan(app: AduibAIApp) -> AsyncIterator[None]:
    log.info("Lifespan is starting")
    session_manager = app.mcp.session_manager
    if session_manager:
        async with session_manager.run():
            yield
