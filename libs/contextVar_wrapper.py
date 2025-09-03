from contextvars import ContextVar
from typing import Generic, TypeVar

T=TypeVar("T")

class ContextVarWrappers(Generic[T]):
    """
    通用请求上下文存储工具，类似 ThreadLocal
    基于 contextvars 实现，支持异步 FastAPI
    """
    def __init__(self, context_var: ContextVar[T]):
        self._storage = context_var


    def set(self, value: T):
        self._storage.set(value)

    def get(self) -> T:
        try:
            return self._storage.get()
        except LookupError:
            return None

    def clear(self) -> None:
        self._storage.set({})