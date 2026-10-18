import os
import secrets
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class StrictAuthMiddleware:
    """ASGI Middleware for strict authentication across all endpoints."""

    ALLOWED_UNAUTHENTICATED_PATHS = frozenset({"/health"})

    def __init__(self, app: ASGIApp):
        self.app = app
        self.expected_key = os.environ.get("VLLM_API_KEY", "").strip()

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "websocket":
            headers = dict(scope.get("headers", []))
            raw_auth = headers.get(b"authorization", b"").decode("latin-1", errors="ignore").strip()
            client_token = raw_auth[7:].strip() if raw_auth.lower().startswith("bearer ") else ""
            if not self.expected_key or not client_token or not secrets.compare_digest(client_token, self.expected_key):
                await send({"type": "websocket.close", "code": 4401})
                return
            await self.app(scope, receive, send)
            return

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.ALLOWED_UNAUTHENTICATED_PATHS:
            await self.app(scope, receive, send)
            return

        if not self.expected_key:
            response = JSONResponse(
                {"error": "Server API key is not configured"},
                status_code=500,
            )
            await response(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_auth = headers.get(b"authorization", b"").decode("latin-1", errors="ignore").strip()

        if not raw_auth.lower().startswith("bearer "):
            response = JSONResponse(
                {"error": "Unauthorized: Missing or invalid Bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        client_token = raw_auth[7:].strip()
        if not client_token or not client_token.isascii() or not secrets.compare_digest(client_token, self.expected_key):
            response = JSONResponse(
                {"error": "Unauthorized: Invalid API key"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
