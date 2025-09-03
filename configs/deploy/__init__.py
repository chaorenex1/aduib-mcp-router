from pydantic import Field
from pydantic_settings import BaseSettings


class DeploymentConfig(BaseSettings):
    APP_NAME: str = Field(default="aduib_mcp_server", description="Application name")
    APP_DESCRIPTION: str = Field(default="Aduib MCP Server", description="Application description")
    APP_HOME: str = Field(default="", description="Application home directory")
    APP_VERSION: str = Field(default="1.0.0", description="Application version")
    APP_HOST: str = Field(default="0.0.0.0",description="Application host")
    APP_PORT: int = Field(default=5001,description="Application port")
    APP_MAX_REQUESTS: int = Field(
        default=1000, description="Maximum number of requests the app can handle"
    )
    APP_MAX_WORKERS: int = Field(
        default=4, description="Number of worker processes for handling requests"
    )
    DEPLOY_ENV: str = Field(
        description="Deployment environment (e.g., 'PRODUCTION', 'DEVELOPMENT'), default to PRODUCTION",
        default="PRODUCTION",
    )
    DEFAULT_USER_AGENT: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0",
        description="Default User-Agent header for HTTP requests",
    )
    IS_SSL: bool = Field(default=False, description="Enable SSL")
    SSL_CERTFILE: str = Field(default="", description="Path to the SSL certificate file")
    SSL_KEYFILE: str = Field(default="", description="Path to the SSL key file")
    DEBUG: bool = Field(default=True, description="Enable debug mode")


    @property
    def url(self) -> str:
        protocol = "https" if self.IS_SSL else "http"
        return f"{protocol}://{self.APP_HOST}:{self.APP_PORT}"

class AuthConfig(BaseSettings):
    AUTH_ENABLED: bool = Field(default=False, description="Enable authentication")


class MCPConfig(BaseSettings):
    TRANSPORT_TYPE: str = Field(default="streamable-http", description="MCP transport type (stdio, sse, streamable-http)")
