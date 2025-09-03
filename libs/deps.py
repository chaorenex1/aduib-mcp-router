from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from .context import verify_api_key_in_db
from models import get_db
from utils.snowflake_id import SnowflakeIDGenerator, id_generator

idGeneratorDep=Annotated[SnowflakeIDGenerator, Depends(id_generator)]

SessionDep = Annotated[Session, Depends(get_db)]

CurrentApiKeyDep = Annotated[None, Depends(verify_api_key_in_db)]