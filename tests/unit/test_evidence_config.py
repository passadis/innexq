"""Explicit opt-in wiring and identity gate, without credential acquisition."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from innexq_api.config import Settings
from innexq_api.evidence_runtime import BrokerInvestigatedEvidence
from innexq_api.evidence_setup import configure_evidence
from pydantic import ValidationError

from tests.unit.test_certificate_runtime import NOW, Repository
from tests.unit.test_certificate_store import Container

PRINCIPAL, CLIENT = str(UUID(int=700)), str(UUID(int=701))
HOST = "ca-innexq-dev-api.delightfulstone-498e0b81.swedencentral.azurecontainerapps.io"
ENABLED = {
    "evidence_broker_enabled": True,
    "evidence_tools_enabled": True,
    "certificates_enabled": True,
    "api_audience": "offline-audience",
    "evidence_agent_principal_id": PRINCIPAL,
    "evidence_agent_client_id": CLIENT,
    "evidence_api_host": HOST,
    "certificate_agent_name": "offline-team",
    "certificate_agent_version": "17",
}


def test_evidence_is_disabled_by_default_and_setup_cannot_silently_enable_it():
    config = Settings(_env_file=None)
    assert not config.evidence_broker_enabled
    assert not config.evidence_tools_enabled
    with pytest.raises(ValueError, match="broker not enabled"):
        configure_evidence(config, None, None, None, None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence_broker_enabled": False},
        {"certificates_enabled": False},
        {"api_audience": ""},
        {"evidence_agent_principal_id": ""},
        {"evidence_agent_principal_id": "invalid"},
        {"evidence_agent_client_id": ""},
        {"evidence_agent_client_id": "invalid"},
        {"evidence_api_host": ""},
        {"evidence_api_host": "evil.example.test"},
        {"evidence_api_host": f"https://{HOST}"},
        {"evidence_api_host": f"{HOST}/mcp"},
        {"evidence_api_host": f"{HOST}:443"},
        {"evidence_api_host": f"*.{HOST}"},
    ],
)
def test_candidate_requires_explicit_runtime_audience_identity_and_hostname(changes):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**ENABLED, **changes})


def test_wiring_reuses_reader_credential_and_returns_request_bound_factory(monkeypatch):
    config = Settings(_env_file=None, **ENABLED)
    reader_credential, agent_credential, auth = object(), object(), object()
    extractor = SimpleNamespace(
        endpoint="https://offline.cognitiveservices.azure.com", credential=reader_credential
    )
    app = SimpleNamespace(
        repository=Repository(), extractor=extractor, now=lambda: NOW, evidence_factory=None
    )
    replacement = MagicMock()
    construct = MagicMock(return_value=replacement)
    monkeypatch.setattr("innexq_api.evidence_setup.DocumentIntelligenceExtractor", construct)
    monkeypatch.setattr(
        "innexq_api.evidence_setup.Path.read_text", lambda *a, **kw: "Policy fixture"
    )
    mcp = MagicMock(return_value=("offline-asgi", "offline-server"))
    monkeypatch.setattr("innexq_api.evidence_setup.evidence_mcp", mcp)
    result = configure_evidence(config, app, auth, Container(), agent_credential)  # type: ignore[arg-type]
    assert result == ("offline-asgi", "offline-server")
    construct.assert_called_once_with(extractor.endpoint, reader_credential, deadline_seconds=45)
    assert app.extractor is extractor
    request_id = uuid4()
    evidence = app.evidence_factory(request_id, "Customer question", "service_status")
    assert isinstance(evidence, BrokerInvestigatedEvidence)
    assert evidence.workflow_request_id == request_id
    assert evidence.prompt == "Customer question" and evidence.intent == "service_status"
    assert evidence.repository is app.repository and evidence.backend.extractor is replacement
    assert evidence.team.credential is agent_credential
    assert evidence.principal_id == UUID(PRINCIPAL)
    assert evidence.now() == NOW
    args = mcp.call_args.args
    assert args == (evidence.broker, auth, UUID(PRINCIPAL), UUID(CLIENT), HOST)


@pytest.mark.parametrize("existing_factory", [None, object()])
def test_broker_only_preserves_customer_routing_and_does_not_create_hosted_team(
    monkeypatch, existing_factory
):
    config = Settings(
        _env_file=None,
        **{
            **ENABLED,
            "evidence_tools_enabled": False,
            "certificate_agent_name": "",
            "certificate_agent_version": "",
        },
    )
    reader_credential = object()
    app = SimpleNamespace(
        repository=Repository(),
        extractor=SimpleNamespace(
            endpoint="https://offline.cognitiveservices.azure.com", credential=reader_credential
        ),
        now=lambda: NOW,
        evidence_factory=existing_factory,
    )
    monkeypatch.setattr(
        "innexq_api.evidence_setup.Path.read_text", lambda *a, **kw: "Policy fixture"
    )
    team = MagicMock(side_effect=AssertionError("broker staging must not create candidate team"))
    monkeypatch.setattr("innexq_api.evidence_setup.HostedEvidenceTeam", team)
    mcp = MagicMock(return_value=("offline-asgi", "offline-server"))
    monkeypatch.setattr("innexq_api.evidence_setup.evidence_mcp", mcp)
    assert configure_evidence(config, app, object(), Container(), object()) == (  # type: ignore[arg-type]
        "offline-asgi",
        "offline-server",
    )
    assert app.evidence_factory is existing_factory
    assert not hasattr(app, "evidence_broker")
    team.assert_not_called()
    assert mcp.call_args.args[-3:] == (UUID(PRINCIPAL), UUID(CLIENT), HOST)


@pytest.mark.parametrize(
    "changes",
    [
        {"certificates_enabled": False},
        {"api_audience": ""},
        {"evidence_agent_principal_id": ""},
        {"evidence_agent_client_id": ""},
        {"evidence_api_host": ""},
    ],
)
def test_broker_only_still_requires_runtime_and_explicit_identity(changes):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**ENABLED, "evidence_tools_enabled": False, **changes})
