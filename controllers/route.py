from fastapi import APIRouter

from .auth import api_key

api_router = APIRouter()

#auth
api_router.include_router(api_key.router)