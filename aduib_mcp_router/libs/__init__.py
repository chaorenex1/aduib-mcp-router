# from contextvars import ContextVar
#
# from libs.contextVar_wrapper import ContextVarWrappers
# from models.api_key import ApiKey
#
# api_key_context: ContextVarWrappers[ApiKey]=ContextVarWrappers(ContextVar("api_key"))
from contextvars import ContextVar

from aduib_mcp_router.aduib_app import AduibAIApp
from aduib_mcp_router.libs.contextVar_wrapper import ContextVarWrappers

app_context: ContextVarWrappers[AduibAIApp]=ContextVarWrappers(ContextVar("app"))