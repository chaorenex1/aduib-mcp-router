import asyncio
import json
import logging
from concurrent import futures
from types import CoroutineType, FunctionType
from typing import Callable

try:
    import nacos
    from v2.nacos import ClientConfigBuilder, GRPCConfig, NacosConfigService, NacosNamingService, ConfigParam, \
    RegisterInstanceParam, DeregisterInstanceParam, ListInstanceParam, Instance, Service, GetServiceParam, \
    SubscribeServiceParam
except ImportError:
    nacos = None
    ClientConfigBuilder = None
    GRPCConfig = None
    NacosConfigService = None
    NacosNamingService = None
    ConfigParam = None
    RegisterInstanceParam = None
    DeregisterInstanceParam = None
    ListInstanceParam = None
    Instance = None
    Service = None
    GetServiceParam = None

logger = logging.getLogger(__name__)

async_thread_pool = futures.ThreadPoolExecutor(thread_name_prefix='nacos_thread_pool')

def run_async(func_or_coro, *args, **kwargs):
    """
        使用线程池在独立事件循环中运行协程任务，
        主线程阻塞等待结果。
        """

    def run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 判断是协程对象还是函数
            if isinstance(func_or_coro, CoroutineType):
                coro = func_or_coro
            elif isinstance(func_or_coro, FunctionType):
                coro = func_or_coro(*args, **kwargs)
            else:
                raise TypeError("func_or_coro must be an async function or coroutine object")
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    # 在线程池中执行协程
    future = async_thread_pool.submit(run_in_thread)
    return future.result()


class NacosClient:
    def __init__(self, server_addr: str,
                 namespace: str,
                 user_name: str,
                 password: str,
                 group: str = "DEFAULT_GROUP",
                 log_level: str = "INFO"):
        self.naming_service = None
        self.config_service = None
        self.server_addr = server_addr
        self.namespace = namespace
        self.group = group
        self.user_name = user_name
        self.password = password
        self.config_cache = {}
        self.service_cache = {}
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
        self.config_watcher = ConfigWatcher(self)
        self.config_service: None
        self.naming_service: None

    async def create_config_service(self):
        self.config_service = await NacosConfigService.create_config_service(self.client_config)

    async def create_naming_service(self):
        self.naming_service = await NacosNamingService.create_naming_service(self.client_config)

    """
    get config value from nacos
    """

    async def get_config(self, data_id: str):
        if self.config_service is None:
            await self.create_config_service()
        # first get from config_cache
        data = self.config_cache.get(data_id)
        # data is none or is ''
        if data is None or data == '':
            data = await self.config_service.get_config(ConfigParam(data_id=data_id, group=self.group))
            # ''
            if data is not None and data != '':
                self.config_cache[data_id] = json.loads(data)
        return self.config_cache.get(data_id)

    def get_config_sync(self, data_id: str):
        return run_async(self.get_config(data_id))

    async def register_config_listener(self, data_id: str):
        if self.config_service is None:
            await self.create_config_service()
        try:
            # context = multiprocessing.get_context("spawn")
            # context.Process(target=(self.client.add_config_watcher(data_id=data_id,group=self.group,cb=ConfigWatcher(self))),
            #                 name=f"ConfigWatcher").start()
            # self.client.add_config_watcher(data_id=data_id, group=self.group, cb=ConfigWatcher(self))
            logger.debug(f"config_listener data_id:{data_id}")
            await self.config_service.add_listener(data_id=data_id, group=self.group, listener=self.config_watcher)
            logger.info(f"Config watcher {data_id} registered")
        except Exception as e:
            logger.error(f"register_config_watcher error:{e}")

    def register_config_listener_sync(self, data_id: str):
        return run_async(self.register_config_listener(data_id))

    async def publish_config(self, data_id: str, data: str):
        logger.debug(f"publish_config:{data_id},{data}")
        if self.config_service is None:
            await self.create_config_service()
        await self.config_service.publish_config(ConfigParam(data_id=data_id, group=self.group, content=data))

    def publish_config_sync(self, data_id: str, data: str):
        return run_async(self.publish_config, data_id, data)

    async def register_instance(self, service_name: str, ip: str, port: int, weight: int = 1, metadata=None):
        if metadata is None:
            metadata = {}
        if self.naming_service is None:
            await self.create_naming_service()
        logger.debug(f"register_instance:{service_name},{ip},{port},{weight},{metadata}")
        await self.naming_service.register_instance(
            RegisterInstanceParam(service_name=service_name, ip=ip, port=port, weight=weight, metadata=metadata))

    def register_instance_sync(self, service_name: str, ip: str, port: int, weight: int = 1, metadata=None):
        return run_async(self.register_instance, service_name, ip, port, weight, metadata)

    async def remove_instance(self, service_name: str, ip: str = None, port: int = None):
        if self.naming_service is None:
            await self.create_naming_service()
        logger.debug(f"remove_instance:{service_name},{ip},{port}")
        await self.naming_service.deregister_instance(
            DeregisterInstanceParam(service_name=service_name, ip=ip, port=port))

    def remove_instance_sync(self, service_name: str, ip: str = None, port: int = None):
        return run_async(self.remove_instance, service_name, ip, port)

    async def get_service(self, service_name: str)-> Service:
        if self.naming_service is None:
            await self.create_naming_service()
        return await self.naming_service.get_service(GetServiceParam(service_name=service_name, group_name=self.group))

    def get_service_sync(self, service_name: str)-> Service:
        return run_async(self.get_service, service_name)

    async def list_instances(self, service_name: str)-> list[Instance]:
        if self.naming_service is None:
            await self.create_naming_service()
        if service_name in self.config_cache:
            return self.config_cache[service_name]
        list = await self.naming_service.list_instances(
            ListInstanceParam(service_name=service_name, group_name=self.group, healthy_only=True, ))
        self.config_cache[service_name] = list
        return list

    def list_instances_sync(self, service_name: str)-> list[Instance]:
        return run_async(self.list_instances, service_name)

    async def subscribe(self,service_name: str):
        if self.naming_service is None:
            await self.create_naming_service()
        await self.naming_service.subscribe(SubscribeServiceParam(service_name=service_name, group_name=self.group,subscribe_callback=NameInstanceWatcher))

    def subscribe_sync(self,service_name: str):
        return run_async(self.subscribe, service_name)

    async def unsubscribe(self,service_name: str):
        if self.naming_service is None:
            await self.create_naming_service()
        await self.naming_service.unsubscribe(SubscribeServiceParam(service_name=service_name, group_name=self.group,subscribe_callback=NameInstanceWatcher))

    def unsubscribe_sync(self,service_name: str):
        return run_async(self.unsubscribe, service_name)

class ConfigWatcher(Callable):
    __name__ = "ConfigWatcher"

    def __init__(self, client: NacosClient):
        self.client = client

    def __call__(self, data_id: str, group: str, data: str):
        logger.info(f"ConfigWatcher data_id:{data_id},group:{group},data:{data}")
        self.client.config_cache[data_id] = json.loads(data)


class NameInstanceWatcher(Callable):
    __name__ = "NameInstanceWatcher"

    def __init__(self, client: NacosClient):
        self.client = client

    def __call__(self, list_instance: list[Instance]):
        logger.info(f"NameInstanceWatcher list_instance:{list_instance}")
        # 按照serviceName分组缓存
        service_instances = {}
        for instance in list_instance:
            service_name = instance.serviceName
            if service_name not in service_instances:
                service_instances[service_name] = []
            service_instances[service_name].append(instance)

        # 更新缓存，完全替换旧的实例列表
        for service_name, instances in service_instances.items():
            self.client.service_cache[service_name] = instances

        logger.info(f"NameInstanceWatcher service_cache:{self.client.service_cache}")
