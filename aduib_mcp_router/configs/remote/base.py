import asyncio
import json
from collections.abc import Mapping
from typing import Any

from pydantic.fields import FieldInfo

from .nacos.client import NacosClient


class RemoteSettingsSource:
    def __init__(self, configs: Mapping[str, Any]):
        pass

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        raise NotImplementedError

    def prepare_field_value(self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool) -> Any:
        return value


class NacosSettingsSource(RemoteSettingsSource):
    """
    A settings source that retrieves configuration settings from Nacos
    """

    def __init__(self, configs: Mapping[str, Any]):
        super().__init__(configs)
        self.configs = configs
        self.client = NacosClient(
            server_addr=configs["NACOS_SERVER_ADDR"],
            namespace=configs["NACOS_NAMESPACE"],
            group=configs["NACOS_GROUP"] or configs["APP_NAME"],
            user_name=configs["NACOS_USERNAME"],
            password=configs["NACOS_PASSWORD"],
        )
        self.data_id = f".env.{self.configs.get('APP_NAME')}.{configs['DEPLOY_ENV']}"
        asyncio.run(self.client.register_config_listener(self.data_id))

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        remote_configs = self.client.get_config_sync(self.data_id)
        if not remote_configs:
            self.client.publish_config_sync(self.data_id, json.dumps(self.configs, indent=4))
            remote_configs = self.configs
        return remote_configs.get(field_name), field_name, False