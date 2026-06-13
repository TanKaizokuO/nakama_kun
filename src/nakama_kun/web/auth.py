from __future__ import annotations

import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, APIKeyQuery
from starlette.websockets import WebSocket

# Generate a random 32-character hex token at startup
WEB_SESSION_TOKEN = secrets.token_hex(16)

# Standard API Key configurations
API_KEY_HEADER = APIKeyHeader(name="X-Web-Token", auto_error=False)
API_KEY_QUERY = APIKeyQuery(name="token", auto_error=False)


def get_session_token() -> str:
    """Return the generated web session token."""
    return WEB_SESSION_TOKEN


def verify_token(token: str | None) -> bool:
    """Check if the provided token matches the generated web session token."""
    if not token:
        return False
    return secrets.compare_digest(token, WEB_SESSION_TOKEN)


async def check_auth_token(
    token_header: str | None = Security(API_KEY_HEADER),
    token_query: str | None = Security(API_KEY_QUERY),
) -> str:
    """FastAPI dependency to verify headers or query string tokens.

    Raises 401 Unauthorized if verification fails.
    """
    token = token_header or token_query
    if not token or not verify_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Web-Token",
        )
    return token


async def check_websocket_auth(websocket: WebSocket) -> bool:
    """Verify WebSocket authentication via query parameter.

    Closes the connection with 4001 status code if invalid.
    """
    token = websocket.query_params.get("token")
    if not token or not verify_token(token):
        await websocket.close(code=4001, reason="Unauthorized")
        return False
    return True
