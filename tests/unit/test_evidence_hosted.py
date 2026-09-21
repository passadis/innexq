"""Hosted transport contract with SDK doubles; no remote invocation."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from innexq_api.certificates import EvidenceUnavailable
from innexq_api.config import Settings
from innexq_api.evidence_runtime import HostedEvidenceTeam

from tests.unit.test_evidence_broker import ROLES, setup


def system(monkeypatch):
    _, binding, _, _, handles = setup()
    output = {
        "request_id": str(binding.request_id),
        "intent": "certificate_request",
        "specialists": [
            {
                "specialist": role,
                "response_id": f"response-{role}",
                "summary": "Evidence inspected.",
                "receipt_ids": [str(uuid4()), str(uuid4())],
            }
            for role in ROLES
        ],
    }
    response = SimpleNamespace(
        status="completed", id="response-coordinator", output_text=json.dumps(output)
    )
    project = MagicMock()
    project.__enter__.return_value = project
    project.agents.create_session.return_value = SimpleNamespace(agent_session_id="offline-session")
    client = project.get_openai_client.return_value.__enter__.return_value
    client.responses.create.return_value = response
    monkeypatch.setattr("innexq_api.evidence_runtime.AIProjectClient", lambda **kwargs: project)
    settings = Settings(
        _env_file=None,
        certificate_agent_name="offline-candidate",
        certificate_agent_version="17",
        foundry_project_endpoint="https://offline",
    )
    return (
        HostedEvidenceTeam(settings, object()),
        binding,
        handles,
        output,
        response,
        project,
        client,
    )


def test_scope_handles_only_cross_transport_headers_and_version_is_pinned(monkeypatch):
    team, binding, handles, _, _, project, client = system(monkeypatch)
    report, response_id = team.investigate(
        binding, handles, "My certificate", "certificate_request"
    )
    assert report.request_id == binding.request_id and response_id == "response-coordinator"
    kwargs = client.responses.create.call_args.kwargs
    assert kwargs["store"] is False
    assert kwargs["extra_body"] == {"agent_session_id": "offline-session"}
    assert kwargs["extra_headers"] == {
        f"x-client-innexq-evidence-{role.replace('_', '-')}": handle.get_secret_value()
        for role, handle in handles.items()
    }
    model = json.loads(kwargs["input"])
    assert model == {
        "mode": "evidence_investigation",
        "request_id": str(binding.request_id),
        "tenant_id": str(binding.tenant_id),
        "customer_id": binding.customer_id,
        "equipment_id": binding.equipment_id,
        "expires_at": binding.expires_at.isoformat(),
        "prompt": "My certificate",
        "intent": "certificate_request",
    }
    assert all(h.get_secret_value() not in kwargs["input"] for h in handles.values())
    assert "metadata" not in kwargs and "tools" not in kwargs
    assert project.agents.create_session.call_args.kwargs["version_indicator"].agent_version == "17"
    assert project.get_openai_client.call_args.kwargs["max_retries"] == 0
    assert client.responses.create.call_count == 1


@pytest.mark.parametrize(
    "failure",
    [
        "wrong-request",
        "wrong-intent",
        "missing-role",
        "duplicate-role",
        "unknown-role",
        "extra-authority",
        "extra-report-key",
        "missing-receipts",
        "bad-receipt",
        "empty-summary",
        "long-summary",
        "incomplete",
        "missing-response-id",
        "non-json",
        "oversize",
        "secret-echo",
    ],
)
def test_invalid_agent_output_is_sanitized_and_not_retried(monkeypatch, failure):
    team, binding, handles, output, response, _, client = system(monkeypatch)
    first = output["specialists"][0]
    if failure == "wrong-request":
        output["request_id"] = str(uuid4())
    elif failure == "wrong-intent":
        output["intent"] = "service_status"
    elif failure == "missing-role":
        output["specialists"] = output["specialists"][:1]
    elif failure == "duplicate-role":
        output["specialists"] = [first, first]
    elif failure == "unknown-role":
        first["specialist"] = "approver"
    elif failure == "extra-authority":
        output["approved"] = True
    elif failure == "extra-report-key":
        first["execute"] = True
    elif failure == "missing-receipts":
        first["receipt_ids"] = []
    elif failure == "bad-receipt":
        first["receipt_ids"] = ["forged", "forged"]
    elif failure == "empty-summary":
        first["summary"] = ""
    elif failure == "long-summary":
        first["summary"] = "x" * 2001
    elif failure == "incomplete":
        response.status = "incomplete"
    elif failure == "missing-response-id":
        response.id = ""
    elif failure == "secret-echo":
        first["summary"] = handles["document_analyst"].get_secret_value()
    response.output_text = json.dumps(output)
    if failure == "non-json":
        response.output_text = "PRIVATE malformed response"
    elif failure == "oversize":
        response.output_text = "x" * 20001
    with pytest.raises(EvidenceUnavailable, match=r"^scoped evidence specialists unavailable$"):
        team.investigate(binding, handles, "My certificate", "certificate_request")
    assert client.responses.create.call_count == 1


def test_transport_exception_and_missing_handle_do_not_leak_credentials(monkeypatch):
    team, binding, handles, _, _, _, client = system(monkeypatch)
    client.responses.create.side_effect = RuntimeError(
        handles["document_analyst"].get_secret_value()
    )
    with pytest.raises(EvidenceUnavailable, match=r"^scoped evidence specialists unavailable$"):
        team.investigate(binding, handles, "My certificate", "certificate_request")
    with pytest.raises(EvidenceUnavailable, match=r"^scoped evidence specialists unavailable$"):
        team.investigate(binding, {}, "My certificate", "certificate_request")
    assert client.responses.create.call_count == 1


@pytest.mark.parametrize(
    "values", [{}, {"certificate_agent_name": "candidate"}, {"certificate_agent_version": "17"}]
)
def test_hosted_candidate_requires_name_and_version(values):
    with pytest.raises(ValueError, match="immutable candidate agent required"):
        HostedEvidenceTeam(Settings(_env_file=None, **values), object())
