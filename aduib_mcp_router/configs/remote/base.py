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

    def __init__(self, configs:Mapping[str, Any]):
        super().__init__(configs)
        self.client = NacosClient(
            server_addr=configs["NACOS_SERVER_ADDR"],
            namespace=configs["NACOS_NAMESPACE"],
            group=configs["NACOS_GROUP"] or "DEFAULT_GROUP",
            user_name=configs["NACOS_USERNAME"],
            password=configs["NACOS_PASSWORD"],
        )
        self.data_id = f".env.{configs['DEPLOY_ENV']}"
        self.client.register_config_listener(self.data_id)
        self.remote_configs=self.client.get_all_dicts(self.data_id)
        if not self.remote_configs:
            self.client.publish_config(self.data_id, json.dumps(configs, indent=4))
            self.remote_configs = configs
        # self.client.register_instance(service_name=f"{configs['APP_NAME']}_{get_local_ip()}_{configs['APP_PORT']}",ip=get_local_ip(),port=configs["APP_PORT"])

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return self.remote_configs.get(field_name), field_name, False

