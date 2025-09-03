from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel

from utils import jsonable_encoder


class BaseHttpException(HTTPException):
    error_code = 0
    error_msg = ""
    def __init__(self, error_code: int, error_msg: str):
        super().__init__(status_code=error_code, detail=error_msg)
        self.error_code = error_code
        self.error_msg = error_msg



class BaseResponse(BaseModel):
    """
    Base response class for all responses
    """
    code: int
    msg: str
    data: dict[str, Any]
    def __init__(self, /, code: int = 0, msg: str = "success", data: dict | None = None):
        super().__init__(code=code, msg=msg, data=data)
        self.code = code
        self.msg = msg
        self.data = data if data is not None else {}

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "msg": self.msg,
            "data": self.data
        }
    @classmethod
    def ok(cls, data: Any | None = None) -> "BaseResponse":
        return cls(code=0, msg="success", data=jsonable_encoder(obj=data, exclude_none=True) if data is not None else {})

    @classmethod
    def error(cls, error_code: int, error_msg: str) -> "BaseResponse":
        return cls(code=error_code, msg=error_msg, data=None)