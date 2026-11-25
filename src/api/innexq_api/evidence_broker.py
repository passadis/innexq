"""ADR-017 candidate durable evidence broker; not mounted in the live API yet.

Only the controller issues scopes. An authenticated MCP adapter may call tools;
neither scopes nor receipts authorize a release or any business-state mutation.
"""

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr

from innexq_api.certificate_store import CosmosCertificateStore
from innexq_api.store import Conflict

Role = Literal["document_analyst", "equipment_service", "renewal_coordinator", "coverage_billing"]
WorkflowPack = Literal["certificate-fulfilment", "service-coverage-renewal"]
PACK_ROLES: dict[WorkflowPack, tuple[Role, ...]] = {
    "certificate-fulfilment": ("document_analyst", "equipment_service"),
    "service-coverage-renewal": ("renewal_coordinator", "coverage_billing"),
}
ROLES: tuple[Role, ...] = PACK_ROLES["certificate-fulfilment"]
ALLOWED = {
    "document_analyst": {"list_equipment_documents", "analyze_document"},
    "equipment_service": {"get_equipment_record", "retrieve_policy"},
    "renewal_coordinator": {"get_equipment_record"},
    "coverage_billing": {
        "list_service_coverage_documents",
        "analyze_service_coverage_document",
        "retrieve_renewal_policy",
        "calculate_renewal_quote",
    },
}
_DOCUMENT_TOOLS = {"analyze_document", "analyze_service_coverage_document"}
_QUERY_TOOLS = {"retrieve_policy", "retrieve_renewal_policy"}
# Which analysis tool must cover every scoped document before finish() closes a role.
_MANDATORY_ANALYZER: dict[str, str] = {
    "document_analyst": "analyze_document",
    "coverage_billing": "analyze_service_coverage_document",
}


class EvidenceDenied(ValueError):
    """Sanitized failure; all evidence must be discarded for this investigation."""


class EvidenceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID
    workflow_request_id: UUID
    tenant_id: UUID
    agent_principal_id: UUID
    customer_id: str = Field(pattern=r"^DEMO-[A-Z0-9-]+$", max_length=80)
    equipment_id: str = Field(pattern=r"^DEMO-[A-Z0-9-]+$", max_length=80)
    source_version: str = Field(min_length=1, max_length=200)
    policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    # Exact document IDs and content hashes selected by the trusted controller.
    document_hashes: dict[str, str] = Field(min_length=1, max_length=10)
    expires_at: AwareDatetime
    workflow_pack: WorkflowPack = "certificate-fulfilment"


class EvidenceBackend(Protocol):
    def read(
        self, binding: EvidenceBinding, name: str, arguments: dict[str, str]
    ) -> dict[str, Any]: ...


class EvidenceStore(CosmosCertificateStore):
    """Reuse the existing Cosmos container, isolated from all workflow partitions."""

    @staticmethod
    def _partition(request_id: UUID) -> str:
        return f"evidence:{request_id}"


class EvidenceBroker:
    def __init__(
        self,
        store: EvidenceStore,
        backend: EvidenceBackend,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store, self.backend, self.now = store, backend, now

    def issue(self, binding: EvidenceBinding) -> dict[Role, SecretStr]:
        """Controller-only method; never expose a scope-issuance MCP/HTTP tool."""
        binding = EvidenceBinding.model_validate(binding.model_dump())
        now = self.now()
        if not now < binding.expires_at <= now + timedelta(minutes=5) or any(
            not re.fullmatch(r"DEMO-[A-Z0-9-]{1,100}", doc)
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
            for doc, digest in binding.document_hashes.items()
        ):
            raise EvidenceDenied("invalid evidence scope")
        handles: dict[Role, SecretStr] = {}
        operations: list[Any] = []
        for role in PACK_ROLES[binding.workflow_pack]:
            handle = f"{binding.request_id.hex}.{role}.{secrets.token_urlsafe(32)}"
            handles[role] = SecretStr(handle)
            record = {
                "id": f"scope-{role}",
                "run_id": self.store._partition(binding.request_id),
                "binding": binding.model_dump(mode="json"),
                "specialist": role,
                "handle_hash": hashlib.sha256(handle.encode()).hexdigest(),
                "state": "active",
                "calls": 0,
                "receipts": [],
            }
            operations.append(("create", (record,)))
        self.store._batch(binding.request_id, operations)
        return handles

    def _replace(self, request_id: UUID, record: dict[str, Any], **changes: Any) -> None:
        self.store._batch(
            request_id,
            [("replace", (record["id"], record | changes), {"if_match_etag": record["_etag"]})],
        )

    def _fail(self, request_id: UUID, role: str) -> None:
        # CAS metadata only; never retry an evidence tool. If storage is unavailable,
        # the outstanding calling state still prevents a successful finalization.
        for _ in range(3):
            record = self.store._read(request_id, f"scope-{role}")
            if record["state"] in {"failed", "closed"}:
                return
            try:
                self._replace(request_id, record, state="failed")
                return
            except Conflict:
                continue
        raise EvidenceDenied("evidence scope unavailable")

    def abort(self, binding: EvidenceBinding) -> None:
        """Controller revocation, including outstanding tools after caller timeout."""
        for role in PACK_ROLES[binding.workflow_pack]:
            record = self.store._read(binding.request_id, f"scope-{role}")
            if EvidenceBinding.model_validate(record["binding"]) != binding:
                raise EvidenceDenied("evidence revocation binding mismatch")
            self._fail(binding.request_id, role)

    def call(
        self,
        tenant_id: UUID,
        principal_id: UUID,
        handle: SecretStr,
        name: str,
        arguments: dict[str, str],
    ) -> dict[str, Any]:
        """Identity comes from verified Entra claims, never the MCP arguments."""
        authenticated: tuple[UUID, str] | None = None
        try:
            raw = handle.get_secret_value()
            match = re.fullmatch(
                r"([0-9a-f]{32})\."
                r"(document_analyst|equipment_service|renewal_coordinator|coverage_billing)\."
                r"([A-Za-z0-9_-]{43})",
                raw,
            )
            if not match:
                raise EvidenceDenied("scope denied")
            request_id, role = UUID(hex=match[1]), match[2]
            record = self.store._read(request_id, f"scope-{role}")
            binding = EvidenceBinding.model_validate(record["binding"])
            if (
                binding.request_id != request_id
                or record["specialist"] != role
                or binding.tenant_id != tenant_id
                or binding.agent_principal_id != principal_id
                or not hmac.compare_digest(
                    record["handle_hash"], hashlib.sha256(raw.encode()).hexdigest()
                )
            ):
                raise EvidenceDenied("scope denied")
            authenticated = (request_id, role)
            if (
                record["state"] != "active"
                or self.now() >= binding.expires_at
                or record["calls"] >= 6
                or name not in ALLOWED[role]
            ):
                raise EvidenceDenied("scope unavailable")
            expected = (
                {"document_id"}
                if name in _DOCUMENT_TOOLS
                else (
                    {"query"}
                    if name in _QUERY_TOOLS
                    else ({"base_amount"} if name == "calculate_renewal_quote" else set())
                )
            )
            if set(arguments) != expected or any(
                not isinstance(v, str) for v in arguments.values()
            ):
                raise EvidenceDenied("invalid evidence arguments")
            if name in _DOCUMENT_TOOLS and arguments["document_id"] not in binding.document_hashes:
                raise EvidenceDenied("document outside scope")
            if name in _QUERY_TOOLS and not 1 <= len(arguments["query"].strip()) <= 1000:
                raise EvidenceDenied("invalid evidence query")
            if name == "calculate_renewal_quote" and not re.fullmatch(
                r"\d{1,12}\.\d{2}", arguments["base_amount"]
            ):
                raise EvidenceDenied("invalid quote input")
            self._replace(request_id, record, state="calling", calls=record["calls"] + 1)
            reserved = self.store._read(request_id, record["id"])
            if reserved["state"] != "calling":
                raise EvidenceDenied("evidence reservation lost")
            payload = self.backend.read(binding, name, arguments)
            encoded = json.dumps(payload, allow_nan=False)
            if (
                not isinstance(payload, dict)
                or not payload
                or len(encoded) > 40000
                or raw in encoded
            ):
                raise EvidenceDenied("invalid evidence result")
            if self.now() >= binding.expires_at:
                raise EvidenceDenied("evidence expired during tool execution")
            receipt_id = uuid4()
            result = {
                "request_id": str(request_id),
                "tenant_id": str(binding.tenant_id),
                "customer_id": binding.customer_id,
                "equipment_id": binding.equipment_id,
                "specialist": role,
                "tool_name": name,
                "receipt_id": str(receipt_id),
                "payload": payload,
            }
            receipt = {
                "id": f"receipt-{receipt_id}",
                "run_id": reserved["run_id"],
                "result": result,
                "arguments": arguments,
                "source_version": binding.source_version,
                "completed_at": self.now().isoformat(),
            }
            self.store._batch(
                request_id,
                [
                    (
                        "replace",
                        (
                            reserved["id"],
                            reserved
                            | {
                                "state": "active",
                                "receipts": [*reserved["receipts"], str(receipt_id)],
                            },
                        ),
                        {"if_match_etag": reserved["_etag"]},
                    ),
                    ("create", (receipt,)),
                ],
            )
            return result
        except Exception:
            if authenticated is not None:
                try:
                    self._fail(*authenticated)
                except Exception:  # noqa: S110 - never log provider errors or private scopes
                    pass  # No usable receipt is returned on a persistence failure.
            raise EvidenceDenied("Evidence tool failed; investigation must stop") from None

    def finish(
        self, binding: EvidenceBinding, receipt_ids: dict[Role, list[UUID]]
    ) -> list[dict[str, Any]]:
        """Controller verifies exact durable receipts and closes both scopes atomically.

        Source revalidation and deterministic eligibility remain controller duties.
        Missing or failed tool activity is never converted into authorization.
        """
        results: list[dict[str, Any]] = []
        operations: list[Any] = []
        pack_roles = PACK_ROLES[binding.workflow_pack]
        if set(receipt_ids) != set(pack_roles) or self.now() >= binding.expires_at:
            raise EvidenceDenied("complete unexpired evidence required")
        for role in pack_roles:
            record = self.store._read(binding.request_id, f"scope-{role}")
            ids = [str(item) for item in receipt_ids[role]]
            if (
                EvidenceBinding.model_validate(record["binding"]) != binding
                or record["state"] != "active"
                or not ids
                or ids != record["receipts"]
                or len(ids) != len(set(ids))
            ):
                raise EvidenceDenied("complete durable evidence required")
            for receipt_id in ids:
                receipt = self.store._read(binding.request_id, f"receipt-{receipt_id}")
                result = receipt["result"]
                if (
                    result["specialist"] != role
                    or receipt["source_version"] != binding.source_version
                ):
                    raise EvidenceDenied("receipt binding mismatch")
                results.append(
                    result
                    | {
                        "completed_at": receipt["completed_at"],
                        "source_version": receipt["source_version"],
                    }
                )
            role_receipts = [
                self.store._read(binding.request_id, f"receipt-{item}") for item in ids
            ]
            if {item["result"]["tool_name"] for item in role_receipts} != ALLOWED[role]:
                raise EvidenceDenied("mandatory evidence tools missing")
            analyzer = _MANDATORY_ANALYZER.get(role)
            if analyzer is not None and {
                item["arguments"]["document_id"]
                for item in role_receipts
                if item["result"]["tool_name"] == analyzer
            } != set(binding.document_hashes):
                raise EvidenceDenied("mandatory document evidence missing")
            operations.append(
                (
                    "replace",
                    (record["id"], record | {"state": "closed"}),
                    {"if_match_etag": record["_etag"]},
                )
            )
        self.store._batch(binding.request_id, operations)
        return results
