"""Authenticated read-only MCP surface, separate from employee/customer routes."""

import re
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import SecretStr
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from innexq_api.auth import EntraAuth
from innexq_api.evidence_broker import EvidenceBroker, EvidenceDenied

_identity: ContextVar[tuple[UUID, UUID] | None] = ContextVar("evidence_identity", default=None)


class EvidenceAuthentication:
    def __init__(
        self,
        app: ASGIApp,
        auth: EntraAuth,
        principal_id: UUID,
        client_id: UUID,
        required_role: str = "Evidence.Read",
    ) -> None:
        self.app, self.auth = app, auth
        self.principal_id, self.client_id = principal_id, client_id
        self.required_role = required_role

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            # Authenticate every protocol request, including discovery and notifications.
            headers = scope.get("headers", [])
            if sum(name.lower() == b"authorization" for name, _ in headers) != 1:
                raise HTTPException(401, "invalid authentication")
            claims = await run_in_threadpool(self.auth.claims, Request(scope))
            roles = claims.get("roles")
            if (
                "scp" in claims
                or claims.get("idtyp") not in (None, "app")
                or claims.get("oid") != str(self.principal_id)
                or claims.get("azp") != str(self.client_id)
                or not isinstance(roles, list)
                or self.required_role not in roles
            ):
                raise HTTPException(403, "evidence identity required")
            tenant_id = UUID(claims["tid"])
        except HTTPException as exc:
            await JSONResponse({"error": "Evidence access denied"}, status_code=exc.status_code)(
                scope, receive, send
            )
            return
        token = _identity.set((tenant_id, self.principal_id))
        try:
            await self.app(scope, receive, send)
        finally:
            _identity.reset(token)


def evidence_mcp(
    broker: EvidenceBroker,
    auth: EntraAuth,
    principal_id: UUID,
    client_id: UUID,
    allowed_host: str,
) -> tuple[ASGIApp, FastMCP]:
    # Exact configured API hostname, not caller-supplied Host or forwarded headers.
    label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    if len(allowed_host) > 253 or not re.fullmatch(label + r"(?:\." + label + r")+", allowed_host):
        raise ValueError("exact evidence API hostname required")
    server = FastMCP(
        "innexq_evidence",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[allowed_host],
            allowed_origins=[f"https://{allowed_host}"],
        ),
    )

    async def call(handle: str, name: str, arguments: dict[str, str]) -> dict[str, Any]:
        identity = _identity.get()
        if identity is None:
            raise EvidenceDenied("Evidence access denied")
        return await run_in_threadpool(broker.call, *identity, SecretStr(handle), name, arguments)

    @server.tool()
    async def get_equipment_record(scope_handle: str) -> dict[str, Any]:
        """Read the fixed equipment record under a controller-issued evidence scope."""
        return await call(scope_handle, "get_equipment_record", {})

    @server.tool()
    async def list_equipment_documents(scope_handle: str) -> dict[str, Any]:
        """List only document references permitted by the controller's scope."""
        return await call(scope_handle, "list_equipment_documents", {})

    @server.tool()
    async def analyze_document(scope_handle: str, document_id: str) -> dict[str, Any]:
        """Extract cited fields from one existing permitted PDF using Document Intelligence."""
        return await call(scope_handle, "analyze_document", {"document_id": document_id})

    @server.tool()
    async def retrieve_policy(scope_handle: str, query: str) -> dict[str, Any]:
        """Read the applicable version-pinned standing-release policy; no decisions."""
        return await call(scope_handle, "retrieve_policy", {"query": query})

    return EvidenceAuthentication(
        server.streamable_http_app(), auth, principal_id, client_id
    ), server


def renewal_mcp(
    broker: EvidenceBroker,
    auth: EntraAuth,
    principal_id: UUID,
    client_id: UUID,
    allowed_host: str,
) -> tuple[ASGIApp, FastMCP]:
    """Read-only Service Coverage Renewal tools behind the Renewal.Read app role (ADR-018)."""

    label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    if len(allowed_host) > 253 or not re.fullmatch(label + r"(?:\." + label + r")+", allowed_host):
        raise ValueError("exact renewal API hostname required")
    server = FastMCP(
        "innexq_renewal",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[allowed_host],
            allowed_origins=[f"https://{allowed_host}"],
        ),
    )

    async def call(handle: str, name: str, arguments: dict[str, str]) -> dict[str, Any]:
        identity = _identity.get()
        if identity is None:
            raise EvidenceDenied("Evidence access denied")
        return await run_in_threadpool(broker.call, *identity, SecretStr(handle), name, arguments)

    @server.tool()
    async def get_equipment_record(scope_handle: str) -> dict[str, Any]:
        """Read the fixed equipment record under a controller-issued renewal scope."""
        return await call(scope_handle, "get_equipment_record", {})

    @server.tool()
    async def list_service_coverage_documents(scope_handle: str) -> dict[str, Any]:
        """List only service-coverage document references permitted by the scope."""
        return await call(scope_handle, "list_service_coverage_documents", {})

    @server.tool()
    async def analyze_service_coverage_document(
        scope_handle: str, document_id: str
    ) -> dict[str, Any]:
        """Extract cited fields from one permitted coverage PDF using Document Intelligence."""
        return await call(
            scope_handle, "analyze_service_coverage_document", {"document_id": document_id}
        )

    @server.tool()
    async def retrieve_renewal_policy(scope_handle: str, query: str) -> dict[str, Any]:
        """Read the version-pinned Service Coverage Renewal policy; no decisions."""
        return await call(scope_handle, "retrieve_renewal_policy", {"query": query})

    @server.tool()
    async def calculate_renewal_quote(scope_handle: str, base_amount: str) -> dict[str, Any]:
        """Citable quote from the deterministic pricing tool; controller always recomputes."""
        return await call(scope_handle, "calculate_renewal_quote", {"base_amount": base_amount})

    return EvidenceAuthentication(
        server.streamable_http_app(), auth, principal_id, client_id, required_role="Renewal.Read"
    ), server
