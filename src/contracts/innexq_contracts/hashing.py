"""Canonical Decision Brief hashing and approval binding."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

from pydantic import BaseModel, JsonValue

from innexq_contracts.models import (
    ActionManifest,
    ApprovalDecision,
    AuthorityVerdict,
    Decision,
    DecisionBrief,
    VersionedBrief,
)


class ApprovalBindingError(ValueError):
    """Raised when a brief and manifest cannot form one approval envelope."""


def _reject_floats(value: Any) -> None:
    if isinstance(value, float):
        raise TypeError("floating-point values are not allowed in canonical approval data")
    if isinstance(value, Mapping):
        for nested in value.values():
            _reject_floats(nested)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            _reject_floats(nested)


def _json_value(value: BaseModel | JsonValue) -> JsonValue:
    if isinstance(value, BaseModel):
        return cast(JsonValue, value.model_dump(mode="json", exclude_none=False))
    return value


def canonical_json_bytes(value: BaseModel | JsonValue) -> bytes:
    """Serialize JSON data deterministically for cross-component hashing.

    Contracts encode decimal values as strings. Raw binary floating-point values are
    rejected because their cross-language normalization is not part of the v1 contract.
    """

    json_value = _json_value(value)
    _reject_floats(json_value)
    serialized = json.dumps(
        json_value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return serialized.encode("utf-8")


def compute_brief_hash(brief: DecisionBrief, manifest: ActionManifest) -> str:
    """Hash a validated, internally consistent approval envelope."""

    if brief.run_id != manifest.run_id:
        raise ApprovalBindingError("brief and manifest must reference the same Run")
    if brief.brief_version != manifest.brief_version:
        raise ApprovalBindingError("brief and manifest versions must match")
    if brief.action_manifest_id != manifest.manifest_id:
        raise ApprovalBindingError("brief must reference the supplied manifest")

    envelope: JsonValue = {
        "schema_version": "1.0",
        "decision_brief": brief.model_dump(mode="json", exclude_none=False),
        "action_manifest": manifest.model_dump(mode="json", exclude_none=False),
    }
    return hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()


def version_brief(
    brief: DecisionBrief,
    manifest: ActionManifest,
    previous: VersionedBrief | None = None,
) -> VersionedBrief:
    """Create the next immutable version and its approval hash.

    Incoming version numbers are never trusted; the controller assigns them.
    """

    next_version = 1 if previous is None else previous.brief.brief_version + 1
    if previous is not None and previous.brief.run_id != brief.run_id:
        raise ApprovalBindingError("a new version cannot change its Run")

    versioned_brief = brief.model_copy(update={"brief_version": next_version})
    versioned_manifest = manifest.model_copy(update={"brief_version": next_version})
    brief_hash = compute_brief_hash(versioned_brief, versioned_manifest)
    return VersionedBrief(
        brief=versioned_brief,
        action_manifest=versioned_manifest,
        brief_hash=brief_hash,
    )


def approval_matches_current_version(
    approval: ApprovalDecision,
    current: VersionedBrief,
) -> bool:
    """Return whether an approval authorizes this exact immutable version."""

    return (
        approval.decision is Decision.APPROVE
        and approval.authority_result.verdict is AuthorityVerdict.AUTHORIZED
        and approval.run_id == current.brief.run_id
        and approval.brief_version == current.brief.brief_version
        and approval.brief_hash == current.brief_hash
    )
