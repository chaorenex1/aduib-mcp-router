from pydantic import Field
from pydantic_settings import BaseSettings


class RouterConfig(BaseSettings):
    MCP_CONFIG_PATH: str = Field(default_factory=str, description="Path to the router configuration file (e.g., /etc/aduib/router_config.yaml or https://example.com/router_config.yaml)")
    ROUTER_HOME: str = Field(default_factory=str,description="Path to the router home directory")
    MCP_REFRESH_INTERVAL: int = Field(default=1800, description="Interval in seconds to refresh the MCP configuration")
    CHROMADB_RESET_ON_START: bool = Field(default=False, description="If True, reset ChromaDB on startup (delete all cached data)")

    # Timeout configurations (in seconds)
    MCP_CONNECTION_TIMEOUT: int = Field(default=600, description="Timeout for MCP SSE/HTTP connections")
    MCP_KEEP_ALIVE_TIMEOUT: int = Field(default=30, description="Keep-Alive timeout for MCP connections")
    MCP_KEEP_ALIVE_MAX: int = Field(default=100, description="Maximum number of keep-alive requests")

    # Health check configurations
    MCP_HEALTH_CHECK_INTERVAL: int = Field(default=30, description="Interval in seconds between health checks (heartbeat)")
    MCP_HEALTH_CHECK_TIMEOUT: int = Field(default=10, description="Timeout for health check ping in seconds")
    MCP_MAX_CONSECUTIVE_FAILURES: int = Field(default=3, description="Max consecutive failures before marking client as dead")
    MCP_AUTO_RECONNECT: bool = Field(default=True, description="Automatically reconnect when client becomes unhealthy")
    MCP_RECONNECT_DELAY: int = Field(default=5, description="Delay in seconds before attempting reconnection")

    # Cache configurations
    MCP_CACHE_TTL: int = Field(default=300, description="Server feature cache TTL in seconds (default 5 minutes)")
    MCP_CACHE_STALE_TTL: int = Field(default=600, description="Maximum time stale cache can still be used in seconds (default 10 minutes)")
    MCP_ENABLE_AUTO_REFRESH: bool = Field(default=True, description="Enable background auto-refresh of feature cache")