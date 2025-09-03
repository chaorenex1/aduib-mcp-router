from pydantic import Field
from pydantic_settings import BaseSettings

class LoggingConfig(BaseSettings):
    LOG_LEVEL:str = Field(default="INFO",description="Log level")
    LOG_FORMAT:str = Field(default="%(asctime)s.%(msecs)03d %(levelname)s [%(threadName)s] [%(filename)s:%(lineno)d] - %(message)s",description="Log format")
    LOG_TZ:str = Field(default="UTC",description="Log timezone")
    LOG_FILE:str = Field(default="aduib_mcp_server.log",description="Log file name")
    LOG_FILE_MAX_BYTES:int = Field(default=10,description="Log file max size in bytes")
    LOG_FILE_BACKUP_COUNT:int = Field(default=5,description="Log file backup count")
    LOG_FILE_LEVEL:str = Field(default="INFO",description="Log file level")