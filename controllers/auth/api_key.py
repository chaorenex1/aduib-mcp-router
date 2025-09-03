from fastapi import APIRouter

from controllers.common.base import BaseResponse
from libs.deps import CurrentApiKeyDep
from service.api_key_service import ApiKeyService

router = APIRouter(tags=['auth'],prefix='/api_key')

@router.post('/get_api_key',response_model=BaseResponse)
def get_api_key(api_key:str,current_key:CurrentApiKeyDep):
    return ApiKeyService.get_by_api_key(api_key)


@router.post('/create_api_key',response_model=BaseResponse)
def create_api_key(name:str,description:str):
    return ApiKeyService.create_api_key(name,description)