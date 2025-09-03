import logging

from mcp.server.auth.provider import OAuthAuthorizationServerProvider, AccessTokenT, AccessToken, RefreshTokenT, \
    AuthorizationCodeT, AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from service import ApiKeyService

logger = logging.getLogger(__name__)


class ApiKeyAuthorizationServerProvider(OAuthAuthorizationServerProvider):

    async def load_access_token(self, token: str) -> AccessTokenT | None:
        logger.debug(f"Loading access token {token}")
        if ApiKeyService.validate_api_key(token):
            return AccessToken(token=token, expires_at=None, client_id="api_key", scopes=["user"])
        else:
            return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        logger.debug(f"Registering client {client_info}")
        return await super().register_client(client_info)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        logger.debug(f"Getting client {client_id}")
        return await super().get_client(client_id)

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        logger.debug(f"Authorizing client {client}")
        return await super().authorize(client, params)

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCodeT | None:
        logger.debug(f"Loading authorization code {authorization_code}")
        return await super().load_authorization_code(client, authorization_code)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCodeT) -> OAuthToken:
        logger.debug(f"Exchanging authorization code {authorization_code}")
        return await super().exchange_authorization_code(client, authorization_code)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshTokenT | None:
        logger.debug(f"Loading refresh token {refresh_token}")
        return await super().load_refresh_token(client, refresh_token)

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshTokenT,
                                     scopes: list[str]) -> OAuthToken:
        logger.debug(f"Exchanging refresh token {refresh_token}")
        return await super().exchange_refresh_token(client, refresh_token, scopes)

    async def revoke_token(self, token: AccessTokenT | RefreshTokenT) -> None:
        logger.debug(f"Revoking token {token}")
        return await super().revoke_token(token)

