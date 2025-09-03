from .base import BaseServiceError


class ApiKeyNotFound(BaseServiceError):
    pass

class ModelNotFound(BaseServiceError):
    pass

class ModelProviderNotFound(BaseServiceError):
    pass