from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from innexq_contracts import (
    Action,
    ApprovalDecision,
    AuthorityVerdict,
    Run,
    RunState,
    version_brief,
)
from innexq_contracts.models import ActionType, Classification
from innexq_contracts.schema_export import schema_documents
from pydantic import ValidationError

from tests.unit.factories import approval, brief, manifest


def test_run_requires_consistent_brief_pointer_and_ordered_timestamps() -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    base = {
        "run_id": UUID(int=1),
        "contract_id": "CON-FAB-2025-001",
        "state": RunState.DETECTED,
        "created_at": now,
        "updated_at": now,
        "correlation_id": UUID(int=2),
    }
    assert Run(**base).current_brief_version == 0

    with pytest.raises(ValidationError, match="unversioned Run"):
        Run(**base, current_brief_hash="a" * 64)
    with pytest.raises(ValidationError, match="requires a current brief hash"):
        Run(**base, current_brief_version=1)
    with pytest.raises(ValidationError, match="cannot precede"):
        Run(**(base | {"updated_at": now - timedelta(seconds=1)}))


def test_unknown_contract_fields_and_unknown_actions_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        brief().model_copy().model_validate({**brief().model_dump(), "surprise": True})

    payload = manifest().actions[0].model_dump()
    payload["action_type"] = "graph.delete_site"
    with pytest.raises(ValidationError):
        Action.model_validate(payload)
    assert set(ActionType) == {
        ActionType.SHAREPOINT_CREATE_FILE,
        ActionType.GRAPH_SEND_MAIL,
        ActionType.TEAMS_SEND_STATUS,
    }


def test_hash_and_required_claim_constraints_are_enforced() -> None:
    payload = manifest().actions[0].model_dump()
    payload["artifact_hash"] = "not-a-hash"
    with pytest.raises(ValidationError):
        Action.model_validate(payload)

    invalid_brief = brief().model_dump()
    invalid_brief["material_claims"][0]["evidence_ids"] = []
    with pytest.raises(ValidationError):
        type(brief()).model_validate(invalid_brief)


def test_approval_schema_round_trip() -> None:
    current = version_brief(brief(), manifest())
    decision = approval(current)
    restored = ApprovalDecision.model_validate_json(decision.model_dump_json())
    assert restored == decision
    assert restored.authority_result.verdict is AuthorityVerdict.AUTHORIZED


def test_committed_schemas_match_models() -> None:
    schema_directory = Path("src/contracts/schemas/v1")
    for filename, expected in schema_documents().items():
        actual = json.loads((schema_directory / filename).read_text(encoding="utf-8"))
        assert actual == expected


def test_synthetic_fixtures_are_consistent() -> None:
    contract = json.loads(Path("corpus/fixtures/fabrikam-contract.json").read_text())
    service = json.loads(Path("corpus/fixtures/fabrikam-service-history.json").read_text())
    assert contract["synthetic"] is True
    assert service["synthetic"] is True
    assert contract["contract_id"] == service["contract_id"]
    assert contract["covered_assets"] == service["asset_count"] == 18
    assert service["emergency_callouts"] > service["previous_comparable_period_emergency_callouts"]
    assert Classification.RESTRICTED.value == "restricted"


def test_approved_azure_scope_is_frozen() -> None:
    azure_manifest = yaml.safe_load(Path("azure.yaml").read_text(encoding="utf-8"))
    assert azure_manifest["infra"] == {"provider": "terraform", "path": "./infra"}
    assert "innexq-api" in azure_manifest["services"]
    # ADR-013 extends the product with the separately hosted E1 customer/team path.
    assert set(azure_manifest["services"]) == {
        "innexq-api",
        "innexq-agent",
        "innexq-web",
        "innexq-customer",
        "innexq-certificate-team",
    }

    terraform_source = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("infra").glob("*.tf")
    )
    assert 'resource "azurerm_cosmosdb_account"' in terraform_source
    for forbidden in ("azurerm_kubernetes_cluster", "azurerm_servicebus_namespace"):
        assert forbidden not in terraform_source
