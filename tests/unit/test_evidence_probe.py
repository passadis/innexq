import json
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from innexq_api import evidence_probe as module
from innexq_api.config import Settings

from tests.unit.test_evidence_config import ENABLED
from tests.unit.test_evidence_runtime import system


def config(**changes):
    values = {
        **ENABLED,
        "environment": "dev",
        "evidence_tools_enabled": False,
        "certificate_agent_name": "innexq-certificate-team",
        "certificate_agent_version": "3",
        "managed_identity_client_id": str(UUID(int=801)),
        "certificate_reader_client_id": str(UUID(int=802)),
        "cosmos_endpoint": "https://offline.documents.azure.com",
        "foundry_project_endpoint": "https://offline.services.ai.azure.com/api/projects/test",
        "certificate_blob_endpoint": "https://offline.blob.core.windows.net",
        "document_intelligence_endpoint": "https://offline.cognitiveservices.azure.com",
    }
    return Settings(_env_file=None, **(values | changes))


@pytest.mark.parametrize("version", ["3", "", "latest", "0", "-1"])
def test_probe_requires_new_immutable_version(version):
    with pytest.raises(ValueError):
        module.validate_probe(config(), version, "DEMO-PT-001", True)


@pytest.mark.parametrize(
    "changes",
    [
        {"environment": "local"},
        {"evidence_broker_enabled": False},
        {"evidence_tools_enabled": True},
        {"certificate_agent_name": "other"},
        {"cosmos_endpoint": ""},
        {"managed_identity_client_id": str(UUID(int=802))},
    ],
)
def test_probe_cannot_change_live_routing_or_share_identity(changes):
    with pytest.raises(ValueError):
        module.validate_probe(config(**changes), "4", "DEMO-PT-001", True)


def test_probe_requires_execute_and_preserves_selected_version():
    original = config()
    with pytest.raises(ValueError):
        module.validate_probe(original, "4", "DEMO-PT-001", False)
    with pytest.raises(ValueError):
        module.validate_probe(original, "4", "FOREIGN", True)
    assert (
        module.validate_probe(original, "4", "DEMO-PT-001", True).certificate_agent_version == "4"
    )
    assert original.certificate_agent_version == "3"


@pytest.mark.parametrize("fail", [False, True])
def test_probe_outputs_only_verified_activity_and_aborts_failed_attempt(monkeypatch, fail):
    reader, team, repository, _ = system()
    team.fail = fail
    monkeypatch.setattr(module, "disable_telemetry", lambda: None)
    for name in (
        "ManagedIdentityCredential",
        "CosmosClient",
        "DocumentIntelligenceExtractor",
        "CertificateEvidenceBackend",
        "EvidenceBroker",
        "HostedEvidenceTeam",
    ):
        monkeypatch.setattr(module, name, MagicMock())
    monkeypatch.setattr(module, "PrivateCertificateRepository", lambda *args: repository)
    monkeypatch.setattr(module, "BrokerInvestigatedEvidence", lambda *args: reader)
    monkeypatch.setattr(module.Path, "read_text", lambda *args, **kwargs: "Offline policy")
    result = module.probe(config(), "4", "DEMO-PT-001", execute=True)
    assert set(result) == {"status", "attempt_id", "tools"}
    assert result["status"] == ("fail" if fail else "pass")
    assert reader.active_binding and result["attempt_id"] == str(reader.active_binding.request_id)
    for tool in result["tools"]:
        assert set(tool) == {"tool_name", "receipt_id"}
    assert "scope_handle" not in json.dumps(result)
    if fail:
        for role in ("document_analyst", "equipment_service"):
            assert (
                reader.broker.store._read(reader.active_binding.request_id, f"scope-{role}")[
                    "state"
                ]
                == "failed"
            )


def test_cli_sanitizes_invalid_arguments_and_configuration(monkeypatch, capsys):
    monkeypatch.setattr(module, "disable_telemetry", lambda: None)
    assert module.main(["--unknown", "private-input"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "fail",
        "attempt_id": None,
        "tools": [],
    }


@pytest.mark.parametrize("completed", [False, True])
def test_canary_never_issues_scope_and_cannot_claim_transport_success(monkeypatch, completed):
    project, client = MagicMock(), MagicMock()
    project.__enter__.return_value = project
    client.__enter__.return_value = client
    project.get_openai_client.return_value = client
    project.agents.create_session.return_value.agent_session_id = "offline-session"
    client.responses.create.return_value.status = "completed" if completed else "failed"
    monkeypatch.setattr(module, "AIProjectClient", MagicMock(return_value=project))
    monkeypatch.setattr(module, "ManagedIdentityCredential", MagicMock())
    monkeypatch.setattr(
        module, "CosmosClient", MagicMock(side_effect=AssertionError("no scope issuance"))
    )
    result = module.transport_canary(config(), "4", True)
    assert result["status"] == ("fail" if completed else "canary_sent")
    assert result["session_id"] == "offline-session"
    call = client.responses.create.call_args.kwargs
    assert result["marker"] not in call["input"]
    assert all(result["marker"] in value for value in call["extra_headers"].values())
    assert call["store"] is False
