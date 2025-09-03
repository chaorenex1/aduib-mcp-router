from urllib.parse import quote_plus

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings


class DBConfig(BaseSettings):
    """Database configuration settings."""
    DB_ENABLED: bool = Field(default=False, description="Enable database")
    DB_DRIVER: str = Field(default="", description="Database driver")
    DB_HOST: str = Field(default="", description="Database host")
    DB_PORT: int = Field(default=-1, description="Database port")
    DB_USERNAME: str = Field(default="", description="Database username")
    DB_PASSWORD: str = Field(default="", description="Database password")
    DB_DATABASE: str = Field(default="", description="Database name")
    DB_CHARSET: str = Field(default="utf8mb4", description="Database charset")
    DB_EXTRAS: str = Field(default="", description="Database extras")
    POOL_SIZE: int = Field(default=50, description="Database connection pool size")

    @computed_field
    @property
    def DATABASE_URI(self) -> str:
        db_extras = (
            f"{self.DB_EXTRAS}&client_encoding={self.DB_CHARSET}" if self.DB_CHARSET else self.DB_EXTRAS
        ).strip("&")
        db_extras = f"?{db_extras}" if db_extras else ""
        return (
            f"{self.DB_DRIVER}://"
            f"{quote_plus(self.DB_USERNAME)}:{quote_plus(self.DB_PASSWORD)}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_DATABASE}"
            f"{db_extras}"
        )