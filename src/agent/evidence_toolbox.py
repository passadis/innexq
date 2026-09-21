"""ADR-017 consumer, wired only into the opt-in candidate agent entrypoint.

Adapted from Microsoft's 04-foundry-toolbox client lifecycle. The raw toolbox is
never exposed to the model. A production broker must independently authorize
each opaque scope and verify source provenance; this client grants no authority.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from agent_framework import tool
from agent_framework.foundry import FoundryToolbox
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr


class EvidenceScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID
    tenant_id: UUID
    customer_id: str = Field(pattern=r"^DEMO-[A-Z0-9-]+$")
    equipment_id: str = Field(pattern=r"^DEMO-[A-Z0-9-]+$")
    specialist: Literal["document_analyst", "equipment_service"]
    scope_handle: SecretStr = Field(min_length=43, max_length=128)
    expires_at: AwareDatetime


class EvidenceResult(BaseModel):
    """Transport binding only. Business truth is revalidated by the controller."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID
    tenant_id: UUID
    customer_id: str
    equipment_id: str
    specialist: Literal["document_analyst", "equipment_service"]
    tool_name: str
    receipt_id: UUID
    payload: dict[str, Any]


TOOL_NAMES = (
    "get_equipment_record",
    "list_equipment_documents",
    "analyze_document",
    "retrieve_policy",
)
ROLE_TOOLS = {
    "document_analyst": frozenset({"list_equipment_documents", "analyze_document"}),
    "equipment_service": frozenset({"get_equipment_record", "retrieve_policy"}),
}
SERVER_LABEL = "innexq_evidence"


def failure_category(error: BaseException) -> str:
    """Fixed diagnostics only: never stringify provider errors or inspect bodies."""
    if isinstance(error, BaseExceptionGroup):
        categories = {failure_category(item) for item in error.exceptions[:12]}
        return sorted(categories)[0] if len(categories) == 1 else "multiple"
    status = getattr(getattr(error, "response", None), "status_code", None)
    if type(status) is int and status in {400, 401, 403, 404, 408, 429, 500, 502, 503, 504}:
        return f"http_{status}"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ValueError):
        return "validation"
    return "transport_or_provider"


def validate_toolbox_endpoint(endpoint: str, project_endpoint: str) -> None:
    """Only a pinned toolbox in the configured project receives an Entra token."""
    project = urlsplit(project_endpoint)
    target = urlsplit(endpoint)
    if (
        project.scheme != "https"
        or not project.hostname
        or not project.hostname.endswith(".services.ai.azure.com")
        or project.username
        or project.password
        or project.port not in (None, 443)
        or project.query
        or project.fragment
        or not re.fullmatch(r"/api/projects/[A-Za-z0-9_-]+", project.path)
        or target.scheme != "https"
        or target.netloc != project.netloc
        or target.fragment
        or target.query != "api-version=v1"
        or not re.fullmatch(
            re.escape(project.path) + r"/toolboxes/[A-Za-z0-9_-]+/versions/[1-9][0-9]*/mcp",
            target.path,
        )
    ):
        raise ValueError("a version-pinned toolbox in the configured Foundry project is required")


class ScopedEvidenceTools:
    """Per-specialist instance; never share mutable context across requests."""

    def __init__(
        self,
        session: Any,
        scope: EvidenceScope,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.session, self.scope, self.now = session, scope, now
        self.failed = False
        self.calls = 0
        self.receipt_ids: list[UUID] = []
        self.results: list[dict[str, Any]] = []
        self._call_lock = asyncio.Lock()

    async def call(self, name: str, arguments: dict[str, str]) -> dict[str, Any]:
        """Serialize one specialist's calls to match the durable broker reservation."""
        try:
            async with self._call_lock:
                # Expiry, failure and budget must be checked after waiting too.
                return await self._call(name, arguments)
        except asyncio.CancelledError:
            # Cancelling a queued call also poisons the whole investigation. An
            # in-flight predecessor checks this latch before accepting its result.
            self.failed = True
            raise

    async def _call(self, name: str, arguments: dict[str, str]) -> dict[str, Any]:
        """No reconnect/retry: a failed branch cannot become a successful proposal."""
        try:
            if self.failed or self.now() >= self.scope.expires_at or self.calls >= 6:
                raise ValueError("scope unavailable")
            if name not in ROLE_TOOLS[self.scope.specialist]:
                raise ValueError("tool unavailable")
            expected = (
                {"document_id"}
                if name == "analyze_document"
                else ({"query"} if name == "retrieve_policy" else set())
            )
            if set(arguments) != expected:
                raise ValueError("unexpected arguments")
            if name == "analyze_document" and not re.fullmatch(
                r"DEMO-[A-Z0-9-]{1,100}", arguments["document_id"]
            ):
                raise ValueError("invalid document reference")
            if name == "retrieve_policy" and not 1 <= len(arguments["query"].strip()) <= 1000:
                raise ValueError("invalid query")
            self.calls += 1  # reserve before await; queued calls share the budget
            # Call the public MCP session directly: the generic convenience
            # call_tool wrapper reconnects/retries on some failures by default.
            result = await asyncio.wait_for(
                self.session.call_tool(
                    f"{SERVER_LABEL}___{name}",
                    arguments={
                        **arguments,
                        "scope_handle": self.scope.scope_handle.get_secret_value(),
                    },
                ),
                timeout=120,
            )
            if result.isError or result.structuredContent is None:
                raise ValueError("tool did not return evidence")
            encoded = json.dumps(result.structuredContent, allow_nan=False)
            if len(encoded) > 50000 or self.scope.scope_handle.get_secret_value() in encoded:
                raise ValueError("unsafe result")
            value = EvidenceResult.model_validate(result.structuredContent)
            for key in ("request_id", "tenant_id", "customer_id", "equipment_id", "specialist"):
                if getattr(value, key) != getattr(self.scope, key):
                    raise ValueError("tool binding mismatch")
            if (
                value.tool_name != name
                or value.receipt_id in self.receipt_ids
                or self.failed
                or self.now() >= self.scope.expires_at
            ):
                raise ValueError("tool receipt unavailable")
            self.receipt_ids.append(value.receipt_id)
            returned = value.model_dump(mode="json")
            self.results.append(returned)
            return returned
        except asyncio.CancelledError:
            self.failed = True
            raise
        except Exception:
            self.failed = True
            raise ValueError("Evidence tool failed; investigation must stop") from None

    def model_tools(self) -> list[Any]:
        # Only these wrappers reach Agent(tools=...). The discovery schemas and
        # scope_handle never do. No function accepts customer, URL, token or scope.
        @tool
        async def get_equipment_record() -> dict[str, Any]:
            """Read the equipment record for this investigation's fixed machine."""
            return await self.call("get_equipment_record", {})

        @tool
        async def list_equipment_documents() -> dict[str, Any]:
            """Discover permitted source document IDs for the fixed equipment."""
            return await self.call("list_equipment_documents", {})

        @tool
        async def analyze_document(document_id: str) -> dict[str, Any]:
            """Request cited Document Intelligence extraction of a discovered document ID."""
            return await self.call("analyze_document", {"document_id": document_id})

        @tool
        async def retrieve_policy(query: str) -> dict[str, Any]:
            """Retrieve cited certificate policy evidence; never decide authorization."""
            return await self.call("retrieve_policy", {"query": query})

        functions = [
            get_equipment_record,
            list_equipment_documents,
            analyze_document,
            retrieve_policy,
        ]
        return [f for f in functions if f.name in ROLE_TOOLS[self.scope.specialist]]


@asynccontextmanager
async def open_evidence_tools(
    credential: Any, endpoint: str, project_endpoint: str, scope: EvidenceScope
) -> AsyncIterator[ScopedEvidenceTools]:
    """Real SDK lifecycle; no default endpoint or production fake/live fallback."""
    validate_toolbox_endpoint(endpoint, project_endpoint)
    # Discovery is checked explicitly. No remote prompts, skills, dynamic tool
    # expansion or convenience-function invocation is passed to the model.
    phase = "connect"
    try:
        async with FoundryToolbox(
            credential, url=endpoint, load_tools=False, load_prompts=False, timeout=125
        ) as toolbox:
            phase = "discovery"
            if toolbox.session is None:
                raise ValueError("Evidence toolbox unavailable")
            discovered = await toolbox.session.list_tools()
            phase = "manifest"
            expected = {f"{SERVER_LABEL}___{name}" for name in TOOL_NAMES}
            if (
                discovered.nextCursor
                or len(discovered.tools) != len(expected)
                or {t.name for t in discovered.tools} != expected
            ):
                raise ValueError("Evidence toolbox manifest changed")
            phase = "investigation"
            yield ScopedEvidenceTools(toolbox.session, scope)
    except Exception as error:
        logging.getLogger("innexq.evidence").warning(
            "Evidence toolbox stopped: phase=%s category=%s", phase, failure_category(error)
        )
        raise
