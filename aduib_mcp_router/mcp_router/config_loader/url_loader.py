from aduib_mcp_router.configs import config
from aduib_mcp_router.mcp_router.config_loader.config_loader import ConfigLoader


class URLLoader(ConfigLoader):
    """ Load configuration from a URL. """

    def load(self) -> str:
        # Implement the logic to fetch and parse the configuration from the URL.
        # This is a placeholder implementation.
        import requests

        response = requests.get(url=config.MCP_CONFIG_PATH, headers={"User-Agent": config.DEFAULT_USER_AGENT})
        return response.text