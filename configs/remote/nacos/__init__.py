from pydantic import Field
from pydantic_settings import BaseSettings


class NacosConfig(BaseSettings):
    NACOS_SERVER_ADDR: str = Field(default="",description="Server address")
    NACOS_NAMESPACE: str = Field(default="",description="Namespace")
    NACOS_GROUP: str = Field(default="DEFAULT_GROUP",description="Group")
    NACOS_USERNAME: str = Field(default="",description="Username")
    NACOS_PASSWORD: str = Field(default="",description="Password")