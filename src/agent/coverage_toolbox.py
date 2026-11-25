"""ADR-018 consumer for the innexq_renewal Toolbox; read-only, no authority.

Mirrors the certificate evidence toolbox lifecycle. The raw toolbox is never
exposed to the model; the controller recomputes every quote and eligibility.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from agent_framework import tool
from agent_framework.foundry import FoundryToolbox
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr

from evidence_toolbox import failure_category, validate_toolbox_endpoint

CoverageRole = Literal["renewal_coordinator", "coverage_billing"]


class CoverageScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID
    tenant_id: UUID
    customer_id: str = Field(pattern=r"^DEMO-[A-Z0-9-]+$")
    equipment_id: str = Field(pattern=r"^DEMO-[A-Z0-9-]+$")
    specialist: CoverageRole
    scope_handle: SecretStr = Field(min_length=43, max_length=128)
    expires_at: AwareDatetime


class CoverageResult(BaseModel):
    """Transport binding only. Business truth is revalidated by the controller."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID
    tenant_id: UUID
    customer_id: str
    equipment_id: str
    specialist: CoverageRole
    tool_name: str
    receipt_id: UUID
    payload: dict[str, Any]


COVERAGE_TOOL_NAMES = (
    "get_equipment_record",
    "list_service_coverage_documents",
    "analyze_service_coverage_document",
    "retrieve_renewal_policy",
    "calculate_renewal_quote",
)
COVERAGE_ROLE_TOOLS: dict[CoverageRole, frozenset[str]] = {
    "renewal_coordinator": frozenset({"get_equipment_record"}),
    "coverage_billing": frozenset(
        {
            "list_service_coverage_documents",
            "analyze_service_coverage_document",
            "retrieve_renewal_policy",
            "calculate_renewal_quote",
        }
    ),
}
COVERAGE_SERVER_LABEL = "innexq_renewal"


class ScopedCoverageTools:
    """Per-specialist instance; never share mutable context across requests."""

    def __init__(
        self,
        session: Any,
        scope: CoverageScope,
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
        try:
            async with self._call_lock:
                return await self._call(name, arguments)
        except asyncio.CancelledError:
            self.failed = True
            raise

    async def _call(self, name: str, arguments: dict[str, str]) -> dict[str, Any]:
        """No reconnect/retry: a failed branch cannot become a successful proposal."""
        try:
            if self.failed or self.now() >= self.scope.expires_at or self.calls >= 6:
                raise ValueError("scope unavailable")
            if name not in COVERAGE_ROLE_TOOLS[self.scope.specialist]:
                raise ValueError("tool unavailable")
            expected = (
                {"document_id"}
                if name == "analyze_service_coverage_document"
                else (
                    {"query"}
                    if name == "retrieve_renewal_policy"
                    else ({"base_amount"} if name == "calculate_renewal_quote" else set())
                )
            )
            if set(arguments) != expected:
                raise ValueError("unexpected arguments")
            if name == "analyze_service_coverage_document" and not re.fullmatch(
                r"DEMO-[A-Z0-9-]{1,100}", arguments["document_id"]
            ):
                raise ValueError("invalid document reference")
            if name == "retrieve_renewal_policy" and not (
                1 <= len(arguments["query"].strip()) <= 1000
            ):
                raise ValueError("invalid query")
            if name == "calculate_renewal_quote" and not re.fullmatch(
                r"\d{1,12}\.\d{2}", arguments["base_amount"]
            ):
                raise ValueError("invalid quote input")
            self.calls += 1  # reserve before await; queued calls share the budget
            result = await asyncio.wait_for(
                self.session.call_tool(
                    f"{COVERAGE_SERVER_LABEL}___{name}",
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
            value = CoverageResult.model_validate(result.structuredContent)
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
            raise ValueError("Coverage tool failed; investigation must stop") from None

    def model_tools(self) -> list[Any]:
        # Only these wrappers reach Agent(tools=...); scope_handle never does.
        @tool
        async def get_equipment_record() -> dict[str, Any]:
            """Read the equipment record for this renewal's fixed machine."""
            return await self.call("get_equipment_record", {})

        @tool
        async def list_service_coverage_documents() -> dict[str, Any]:
            """Discover permitted service-coverage document IDs for the fixed equipment."""
            return await self.call("list_service_coverage_documents", {})

        @tool
        async def analyze_service_coverage_document(document_id: str) -> dict[str, Any]:
            """Request cited extraction of a discovered coverage document ID."""
            return await self.call(
                "analyze_service_coverage_document", {"document_id": document_id}
            )

        @tool
        async def retrieve_renewal_policy(query: str) -> dict[str, Any]:
            """Retrieve cited renewal policy evidence; never decide eligibility."""
            return await self.call("retrieve_renewal_policy", {"query": query})

        @tool
        async def calculate_renewal_quote(base_amount: str) -> dict[str, Any]:
            """Cite a deterministic quote for a decimal base amount; never compute one."""
            return await self.call("calculate_renewal_quote", {"base_amount": base_amount})

        functions = [
            get_equipment_record,
            list_service_coverage_documents,
            analyze_service_coverage_document,
            retrieve_renewal_policy,
            calculate_renewal_quote,
        ]
        return [f for f in functions if f.name in COVERAGE_ROLE_TOOLS[self.scope.specialist]]


@asynccontextmanager
async def open_coverage_tools(
    credential: Any, endpoint: str, project_endpoint: str, scope: CoverageScope
) -> AsyncIterator[ScopedCoverageTools]:
    """Real SDK lifecycle; no default endpoint or production fake/live fallback."""
    validate_toolbox_endpoint(endpoint, project_endpoint)
    phase = "connect"
    try:
        async with FoundryToolbox(
            credential, url=endpoint, load_tools=False, load_prompts=False, timeout=125
        ) as toolbox:
            phase = "discovery"
            if toolbox.session is None:
                raise ValueError("Renewal toolbox unavailable")
            discovered = await toolbox.session.list_tools()
            phase = "manifest"
            expected = {f"{COVERAGE_SERVER_LABEL}___{name}" for name in COVERAGE_TOOL_NAMES}
            if (
                discovered.nextCursor
                or len(discovered.tools) != len(expected)
                or {t.name for t in discovered.tools} != expected
            ):
                raise ValueError("Renewal toolbox manifest changed")
            phase = "investigation"
            yield ScopedCoverageTools(toolbox.session, scope)
    except Exception as error:
        logging.getLogger("innexq.renewal").warning(
            "Renewal toolbox stopped: phase=%s category=%s", phase, failure_category(error)
        )
        raise
