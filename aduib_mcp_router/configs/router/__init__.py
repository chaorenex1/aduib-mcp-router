from pydantic import Field
from pydantic_settings import BaseSettings


class RouterConfig(BaseSettings):
    MCP_CONFIG_PATH: str = Field(default_factory=str, description="Path to the router configuration file (e.g., /etc/aduib/router_config.yaml or https://example.com/router_config.yaml)")
    ROUTER_HOME: str = Field(default_factory=str,description="Path to the router home directory")
    MCP_REFRESH_INTERVAL: int = Field(default=3000, description="Interval in seconds to refresh the MCP configuration")