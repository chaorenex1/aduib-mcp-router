import json

from aduib_mcp_router.configs.remote.nacos.client import NacosClient
from aduib_mcp_router.mcp_router.config_loader.config_loader import ConfigLoader


class RemoteConfigLoader(ConfigLoader):
    """ Load configuration from a remote source (e.g., URL or config center). """
    def __init__(self, data_id: str,client:NacosClient):
        self.client=client
        self.data_id = data_id

    def load(self) -> str:
        return json.dumps(self.client.get_config_sync(self.data_id))