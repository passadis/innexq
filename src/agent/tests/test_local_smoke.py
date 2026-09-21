"""The opt-in probe must not acquire an agent API token as the developer."""

from pathlib import Path
from unittest.mock import Mock

from contracts import RunRequest
from scripts.local_smoke import LocalPricingCredential


def test_local_pricing_credential_never_requests_api_token():
    actual = Mock()
    credential = LocalPricingCredential(actual, "api://fixture/.default")
    token = credential.get_token("api://fixture/.default")
    assert token.token == "local-fixture-not-an-access-token"
    actual.get_token.assert_not_called()


def test_local_retrieval_uses_real_credential():
    actual = Mock()
    credential = LocalPricingCredential(actual, "api://fixture/.default")
    assert (
        credential.get_token("https://search.azure.com/.default") is actual.get_token.return_value
    )
    actual.get_token.assert_called_once_with("https://search.azure.com/.default")


def test_local_probe_is_not_in_production_container():
    agent_root = Path(__file__).resolve().parents[1]
    dockerfile = (agent_root / "Dockerfile").read_text(encoding="utf-8")
    assert "contracts.py retrieval.py main.py certificate_team.py ./" in dockerfile
    assert "scripts" not in dockerfile
    assert "!scripts" not in (agent_root / ".dockerignore").read_text(encoding="utf-8")


def test_local_protocol_payload_contains_only_synthetic_run_identifiers():
    payload = (Path(__file__).parent / "local-smoke-request.json").read_text("utf-8")
    request = RunRequest.model_validate_json(payload)
    assert request.contract_id == "CON-FAB-2025-001"
