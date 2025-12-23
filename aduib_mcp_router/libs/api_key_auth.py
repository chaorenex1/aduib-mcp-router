import datetime
import json
import logging
import secrets
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from mcp.server.auth.provider import (
    OAuthAuthorizationServerProvider,
    AccessTokenT,
    AccessToken,
    RefreshTokenT,
    AuthorizationCodeT,
    AuthorizationParams,
    AuthorizationCode,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from aduib_mcp_router.configs import config
from aduib_mcp_router.utils import jsonable_encoder

logger = logging.getLogger(__name__)


# ---- In-memory API key storage -------------------------------------------------


@dataclass
class ApiKeyRecord:
    id: int
    name: str  # usually client_id
    api_key: str  # used as refresh token
    hash_key: str  # used as access token
    description: str | None = None
    source: str | None = None
    created_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)


class ApiKeyService:
    """Simple in-memory API key service for OAuth2-like flows.

    This implementation is intentionally minimal and process-local. It should
    not be used as-is in production, but it's sufficient for MCP router
    development and demo scenarios.
    """

    _store: Dict[int, ApiKeyRecord] = {}
    _by_name: Dict[str, int] = {}
    _id_counter: int = 1

    @classmethod
    def create_api_key(cls, name: str, description: str | None, source: str | None) -> ApiKeyRecord:
        api_key = secrets.token_urlsafe(32)
        hash_key = secrets.token_urlsafe(32)
        rec_id = cls._id_counter
        cls._id_counter += 1

        record = ApiKeyRecord(
            id=rec_id,
            name=name,
            api_key=api_key,
            hash_key=hash_key,
            description=description,
            source=source,
        )
        cls._store[rec_id] = record
        cls._by_name[name] = rec_id
        logger.debug("Created in-memory api key record: %s", record)
        return record

    @classmethod
    def update_api_key(cls, rec_id: int, name: str, description: str | None, source: str | None) -> ApiKeyRecord:
        if rec_id not in cls._store:
            raise KeyError(f"ApiKey with id {rec_id} not found")
        record = cls._store[rec_id]
        record.name = name
        record.description = description
        record.source = source
        cls._by_name[name] = rec_id
        logger.debug("Updated in-memory api key record: %s", record)
        return record

    @classmethod
    def get_api_key_by_name(cls, name: str) -> Optional[ApiKeyRecord]:
        rec_id = cls._by_name.get(name)
        if rec_id is None:
            return None
        return cls._store.get(rec_id)


# ---- Error types compatible with oauth provider contract ----------------------


class BadRequestError(Exception):
    """Raised when OAuth client or params are invalid."""


class UnauthorizedError(Exception):
    """Raised when token or authorization code is invalid."""


# ---- OAuth2 ApiKey-based AuthorizationServerProvider --------------------------


class ApiKeyAuthorizationServerProvider(OAuthAuthorizationServerProvider):
    """OAuth2 authorization server provider using API key semantics, in-memory.

    - `register_client` 会为 client_id 创建一条 ApiKey 记录，并把 client 信息
      以 JSON 存入 description。
    - `authorize` 生成一次性授权码（code），回写到 ApiKey 的 description 里。
    - `exchange_authorization_code` / `exchange_refresh_token` 用 ApiKey 的
      `hash_key` 作为 access_token，用 `api_key` 作为 refresh_token。
    """

    async def load_access_token(self, token: str) -> AccessTokenT | None:
        logger.debug("Loading access token %s", token)

        # 静态配置的 AUTH_KEY 优先（全局 API Key）
        if token == config.AUTH_KEY:
            return AccessToken(token=token, expires_at=None, client_id="api_key", scopes=["user"])

        # 其次从内存 ApiKeyService 中查找
        for record in ApiKeyService._store.values():
            if record.hash_key == token:
                return AccessToken(token=token, expires_at=None, client_id=record.name, scopes=["user"])

        return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        logger.debug("Registering client %s", client_info)
        data: Dict[str, Any] = {
            "client_info": client_info.model_dump(exclude_none=True)
        }
        # description 存储 JSON 串
        ApiKeyService.create_api_key(
            name=client_info.client_id,
            description=json.dumps(jsonable_encoder(data)),
            source="mcp",
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        logger.debug("Getting client %s", client_id)
        api_key = ApiKeyService.get_api_key_by_name(client_id)
        if not api_key or not api_key.description:
            return None
        data = json.loads(api_key.description)
        return OAuthClientInformationFull.model_validate(data["client_info"])

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        logger.debug("Authorizing client %s with params %s", client, params)
        api_key = ApiKeyService.get_api_key_by_name(client.client_id)
        if not api_key:
            raise BadRequestError("Client not found")
        if client.client_id != api_key.name:
            raise BadRequestError("Client id mismatch")

        # 校验 scopes
        if client.scope and params.scopes:
            allowed = set(client.scope.split(" "))
            for scope in params.scopes:
                if scope not in allowed:
                    raise BadRequestError(f"Client was not registered with scope {scope}")

        # 校验 redirect_uri
        if client.redirect_uris and params.redirect_uri:
            if params.redirect_uri not in client.redirect_uris:
                raise BadRequestError(f"Redirect URI '{params.redirect_uri}' not registered for client")

        params_dict = params.model_dump(exclude_none=True)
        params_dict["code"] = secrets.token_urlsafe(16)

        data: Dict[str, Any] = {
            "client_info": client.model_dump(exclude_none=True),
            "auth_params": params_dict,
        }

        # 使用 jsonable_encoder 保证可序列化
        encoded = json.dumps(jsonable_encoder(obj=data))
        ApiKeyService.update_api_key(api_key.id, api_key.name, encoded, api_key.source)

        return construct_redirect_uri(str(params.redirect_uri), code=params_dict["code"], state=params.state)

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCodeT | None:
        logger.debug("Loading authorization code %s", authorization_code)
        api_key = ApiKeyService.get_api_key_by_name(client.client_id)
        if not api_key or not api_key.description:
            raise BadRequestError("Client not found")
        if client.client_id != api_key.name:
            raise BadRequestError("Client id mismatch")

        data = json.loads(api_key.description)
        params = data.get("auth_params") or {}

        # 校验 code
        if params.get("code") != authorization_code:
            raise UnauthorizedError("Invalid authorization code")

        # 构造 AuthorizationCode 对象
        expires_at = datetime.datetime.now().timestamp() + 30  # 授权码 30 秒有效
        auth_params = AuthorizationCode(
            code=params["code"],
            scopes=[client.scope] if client.scope else [],
            expires_at=expires_at,
            client_id=client.client_id,
            code_challenge=params.get("code_challenge"),
            redirect_uri=params.get("redirect_uri"),
            redirect_uri_provided_explicitly=params.get("redirect_uri_provided_explicitly", False),
        )
        return auth_params

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCodeT,
    ) -> OAuthToken:
        logger.debug("Exchanging authorization code %s", authorization_code)
        api_key = ApiKeyService.get_api_key_by_name(client.client_id)
        if not api_key or not api_key.description:
            raise BadRequestError("Client not found")
        if client.client_id != api_key.name:
            raise BadRequestError("Client id mismatch")

        if client.scope and authorization_code.scopes:
            allowed = set(client.scope.split(" "))
            for scope in authorization_code.scopes:
                if scope not in allowed:
                    raise BadRequestError(f"Client was not registered with scope {scope}")

        data = json.loads(api_key.description)
        auth_params = data.get("auth_params") or {}
        if auth_params.get("code") != authorization_code.code:
            raise UnauthorizedError("Invalid authorization code")

        return OAuthToken(
            access_token=api_key.hash_key,
            expires_in=36000,
            refresh_token=api_key.api_key,
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshTokenT | None:
        logger.debug("Loading refresh token %s", refresh_token)
        api_key = ApiKeyService.get_api_key_by_name(client.client_id)
        if not api_key:
            raise BadRequestError("Client not found")
        if client.client_id != api_key.name:
            raise BadRequestError("Client id mismatch")
        if api_key.api_key != refresh_token:
            raise UnauthorizedError("Invalid refresh token")

        return RefreshToken(
            token=refresh_token,
            client_id=client.client_id,
            scopes=[client.scope] if client.scope else [],
            expires_at=None,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshTokenT,
        scopes: list[str],
    ) -> OAuthToken:
        logger.debug("Exchanging refresh token %s", refresh_token)
        api_key = ApiKeyService.get_api_key_by_name(client.client_id)
        if not api_key:
            raise BadRequestError("Client not found")
        if client.client_id != api_key.name:
            raise BadRequestError("Client id mismatch")
        if api_key.api_key != refresh_token.token:
            raise UnauthorizedError("Invalid refresh token")

        # 校验请求的 scopes
        if client.scope and scopes:
            allowed = set(client.scope.split(" "))
            for scope in scopes:
                if scope not in allowed:
                    raise BadRequestError(f"Client was not registered with scope {scope}")

        return OAuthToken(
            access_token=api_key.hash_key,
            token_type="Bearer",
            expires_in=36000,
            refresh_token=api_key.api_key,
            scope=" ".join(scopes) if scopes else None,
        )

    async def revoke_token(self, token: AccessTokenT | RefreshTokenT) -> None:
        logger.debug("Revoking token %s", token)
        # 在纯 API Key 模式中，通常不做真正的撤销，除非主动删除 ApiKey 记录。
        # 这里保持 no-op。
        return None
