import asyncio
import json
import logging
import signal
from typing import Callable

import nacos
from v2.nacos import ClientConfigBuilder, GRPCConfig, NacosConfigService, NacosNamingService, ConfigParam

logger = logging.getLogger(__name__)

class NacosClient:
    def __init__(self, server_addr: str,
                 namespace: str,
                 group: str,
                 user_name:str,
                 password:str,
                 log_level: str = "INFO"):
        self.server_addr = server_addr
        self.namespace = namespace
        self.group = group
        self.user_name = user_name
        self.password = password
        self.cache = {}
        self.log_level = log_level
        self.client_config = (ClientConfigBuilder()
                         .username(self.user_name)
                         .password(self.password)
                         .server_address(self.server_addr)
                         .log_level(self.log_level)
                         .namespace_id(self.namespace)
                         .grpc_config(GRPCConfig(grpc_timeout=5000))
                         .build())
        self.client = nacos.NacosClient(server_addresses=server_addr, namespace=namespace, username=user_name,
                                   password=password)
        self.create_config_client()
        self.create_naming_client()
        self.config_watcher = ConfigWatcher(self)

    def create_config_client(self):
        self.config_client= asyncio.run(NacosConfigService.create_config_service(self.client_config))
        asyncio.run(self.config_client.server_health())

    def create_naming_client(self):
        self.naming_client=asyncio.run(NacosNamingService.create_naming_service(self.client_config))
        asyncio.run(self.naming_client.server_health())

    """
    get config value from nacos
    """
    def get_all_dicts(self, data_id: str):
        data = self.cache.get(data_id)
        # data is none or is ''
        if data is None or data == '':
            data = asyncio.run(self.config_client.get_config(ConfigParam(data_id=data_id, group=self.group)))
            # ''
            if data is not None and data != '':
                self.cache[data_id] = json.loads(data)
        return self.cache.get(data_id)

    def register_config_listener(self,data_id: str):
        try:
            # context = multiprocessing.get_context("spawn")
            # context.Process(target=(self.client.add_config_watcher(data_id=data_id,group=self.group,cb=ConfigWatcher(self))),
            #                 name=f"ConfigWatcher").start()
            # self.client.add_config_watcher(data_id=data_id, group=self.group, cb=ConfigWatcher(self))
            def config_listener(tenant, data_id, group, content):
                self.cache[data_id] = json.loads(content)
                logger.debug(f"config_listener data_id:{data_id},group:{group},data:{content}")

            def remove_config_watcher_signal(signal, frame):
                asyncio.run(self.config_client.remove_listener(data_id=data_id, group=self.group, listener=config_listener))
                logger.debug(f"remove_config_watcher_signal:{signal},{frame}")

            signal.signal(signal.SIGINT, remove_config_watcher_signal)
            signal.signal(signal.SIGTERM, remove_config_watcher_signal)
            asyncio.run(self.config_client.add_listener(data_id=data_id, group=self.group, listener=config_listener))
            logger.info(f"Config watcher {data_id} registered")
        except Exception as e:
            logger.error(f"register_config_watcher error:{e}")



    def publish_config(self, data_id: str, data: str):
        logger.debug(f"publish_config:{data_id},{data}")
        self.client.publish_config(data_id=data_id, group=self.group,content=data,config_type="json")

    def register_instance(self, service_name: str, ip: str, port: int):
        logger.debug(f"register_instance:{service_name},{ip},{port}")
        self.client.add_naming_instance(service_name=service_name, ip=ip, port=port)
        def remove_instance_signal(signal, frame):
            logger.debug(f"remove_instance_signal:{signal},{frame}")
            self.remove_instance(service_name=service_name, ip=ip, port=port)

        signal.signal(signal.SIGINT, remove_instance_signal)
        signal.signal(signal.SIGTERM, remove_instance_signal)
        self.client.subscribe(listener_fn=NameInstanceWatcher,service_name=service_name, namespace_id =self.namespace,group_name=self.group)

    def remove_instance(self, service_name: str, ip: str, port: int):
        self.client.unsubscribe(service_name=service_name,listener_name="NameInstanceWatcher")
        self.client.stop_subscribe()
        self.client.remove_naming_instance(service_name=service_name, ip=ip, port=port)


class ConfigWatcher(Callable):
    __name__ = "ConfigWatcher"

    def __init__(self, client: NacosClient):
        self.client = client
    def __call__(self, data_id: str, group: str, data: str):
        logger.info(f"ConfigWatcher data_id:{data_id},group:{group},data:{data}")
        self.client.cache[data_id] = json.loads(data)


class NameInstanceWatcher(Callable):
    listener_name = "NameInstanceWatcher"

    def launch(self, *args, **kwargs):
        logger.info(f"NameInstanceWatcher launch:{args},{kwargs}")