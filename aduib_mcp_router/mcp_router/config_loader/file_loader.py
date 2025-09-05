import logging
import os

from aduib_mcp_router.configs import config
from aduib_mcp_router.mcp_router.config_loader.config_loader import ConfigLoader

logger = logging.getLogger(__name__)

class FileConfigLoader(ConfigLoader):
    """
    Load configuration from a local file.
    The file path is specified in the MCP_CONFIG_PATH environment variable or defaults to ./mcp
    """
    def __init__(self, router_home: str):
        self.router_home = router_home

    def load(self) -> str:
        if not os.path.exists(config.MCP_CONFIG_PATH):
            logger.warning(f"MCP configuration file {config.MCP_CONFIG_PATH} does not exist.")
            config.MCP_CONFIG_PATH = os.getenv("MCP_CONFIG_PATH")
            if not config.MCP_CONFIG_PATH or not os.path.exists(config.MCP_CONFIG_PATH):
                if os.path.exists(os.path.join(self.router_home, "mcp_config.json")):
                    config.MCP_CONFIG_PATH = os.path.join(self.router_home, "mcp_config.json")
                else:
                    logger.warning(
                        f"MCP configuration file {config.MCP_CONFIG_PATH} does not exist, using default empty config.")
                    raise FileNotFoundError(f"MCP configuration file {config.MCP_CONFIG_PATH} does not exist.")
        with open(config.MCP_CONFIG_PATH, 'rt', encoding='utf-8') as f:
            content = f.read()
        logger.info(f"Loaded MCP configuration from {config.MCP_CONFIG_PATH}")
        return content