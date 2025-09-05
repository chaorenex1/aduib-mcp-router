from abc import ABC, abstractmethod


class ConfigLoader(ABC):
    """Abstract base class for configuration loaders."""

    @abstractmethod
    def load(self) -> str:
        """Load configuration and return as a string."""
        ...

    @classmethod
    def get_config_loader(cls,config_path: str,router_home:str) -> 'ConfigLoader':
        """Factory function to get the appropriate ConfigLoader based on the config_path."""
        from aduib_mcp_router.configs import config
        from aduib_mcp_router.mcp_router.config_loader.file_loader import FileConfigLoader
        from aduib_mcp_router.mcp_router.config_loader.url_loader import URLLoader
        from aduib_mcp_router.mcp_router.config_loader.remote_config_loader import RemoteConfigLoader

        if config_path.startswith("http://") or config_path.startswith("https://"):
            return URLLoader()
        elif config_path.startswith("nacos://"):
            # Extract data_id from the URL
            data_id = config_path[len("nacos://"):]
            from aduib_mcp_router.configs.remote.nacos.client import NacosClient
            client = NacosClient(server_addr=config.NACOS_SERVER_ADDR,
                                 namespace=config.NACOS_NAMESPACE,
                                 user_name=config.NACOS_USERNAME,
                                 group="aduib-mcp-router",
                                 password=config.NACOS_PASSWORD)
            return RemoteConfigLoader(data_id, client)
        else:
            return FileConfigLoader(router_home)