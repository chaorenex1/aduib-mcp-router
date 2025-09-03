import logging
from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import SettingsConfigDict, BaseSettings, PydanticBaseSettingsSource

from .cache.redis_config import RedisConfig
from .db import DBConfig
from .deploy import DeploymentConfig, AuthConfig, MCPConfig
from .logging import LoggingConfig
from .remote import RemoteSettingsSource, RemoteSettingsSourceName, RemoteSettingsSourceConfig, DiscoveryConfig
from .remote.base import NacosSettingsSource

logger = logging.getLogger(__name__)


class RemoteSettingsSourceFactory(PydanticBaseSettingsSource):
    config_source: RemoteSettingsSource

    def __init__(self, settings_cls: type[BaseSettings]):
        super().__init__(settings_cls)

    def __call__(self) -> dict[str, Any]:
        current_state = self.current_state
        remote_source_name = current_state.get("REMOTE_SETTINGS_SOURCE_NAME")
        if not remote_source_name:
            return {}

        logger.info("RemoteSettingsSourceFactory source_name: %s", remote_source_name)
        remote_source: RemoteSettingsSource | None = None
        match remote_source_name:
            case RemoteSettingsSourceName.NACOS:
                remote_source = NacosSettingsSource(current_state)
            case _:
                logger.warning(f"Unsupported remote source: {remote_source_name}")
                return {}

        d: dict[str, Any] = {}

        for field_name, field in self.settings_cls.model_fields.items():
            field_value, field_key, value_is_complex = remote_source.get_field_value(field, field_name)
            field_value = remote_source.prepare_field_value(field_name, field, field_value, value_is_complex)
            if field_value is not None:
                d[field_key] = field_value

        self.config_source = remote_source
        return d

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        logger.debug(f"get_field_value: {field}, {field_name}")
        return self.config_source.get_field_value(field, field_name)


class AduibAiConfig(
    DeploymentConfig,
    AuthConfig,
    MCPConfig,
    LoggingConfig,
    DBConfig,
    RedisConfig,
    RemoteSettingsSourceConfig,
    DiscoveryConfig
):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./aduib_ai/)
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            RemoteSettingsSourceFactory(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )