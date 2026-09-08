"""Explicit Entra audience, issuer, lifetime and actor checks."""

from typing import Any

import jwt
from fastapi import HTTPException, Request

from innexq_api.config import Settings


class EntraAuth:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.keys = jwt.PyJWKClient(
            f"https://login.microsoftonline.com/{settings.tenant_id}/discovery/v2.0/keys",
            timeout=10,
        )

    def claims(self, request: Request) -> dict[str, Any]:
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or not self.settings.api_audience:
            raise HTTPException(401, "Entra access token required")
        token = authorization[7:]
        try:
            key = self.keys.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.settings.api_audience,
                issuer=f"https://login.microsoftonline.com/{self.settings.tenant_id}/v2.0",
                options={"require": ["exp", "iat", "nbf", "aud", "iss", "tid", "oid"]},
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(401, "invalid Entra access token") from exc
        if claims["tid"] != self.settings.tenant_id:
            raise HTTPException(403, "wrong tenant")
        return claims

    def user(self, request: Request) -> tuple[str, str]:
        claims = self.claims(request)
        if "user_impersonation" not in claims.get("scp", "").split():
            raise HTTPException(403, "delegated user scope required")
        if claims["oid"] != self.settings.approver_user_id:
            raise HTTPException(403, "user is not assigned to the Phase 1 workflow")
        return claims["tid"], claims["oid"]

    def agent(self, request: Request) -> None:
        claims = self.claims(request)
        if (
            not self.settings.agent_principal_id
            or claims["oid"] != self.settings.agent_principal_id
            or "Pricing.Read" not in claims.get("roles", [])
        ):
            raise HTTPException(403, "read-only agent identity required")
