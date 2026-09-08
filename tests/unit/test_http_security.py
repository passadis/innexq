import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from innexq_api.main import create_app
from innexq_api.telemetry import configure_telemetry
from innexq_contracts.models import RunState

from tests.unit.test_controller import detected


@pytest.fixture
def api(system: Any) -> tuple[TestClient, Any]:
    c, _, _, _, _ = system
    application = create_app(c.settings, c)
    application.dependency_overrides[application.state.user_dependency] = lambda: (
        c.settings.tenant_id,
        c.settings.approver_user_id,
    )
    application.dependency_overrides[application.state.agent_dependency] = lambda: None
    return TestClient(application), system


def test_http_workflow_and_preserving_reset(api: Any) -> None:
    client, (_, store, _, _, approvals) = api
    headers = {"Idempotency-Key": "synthetic-reset-0001"}
    reset = client.post("/api/demo/reset", headers=headers).json()
    assert reset == client.post("/api/demo/reset", headers=headers).json()
    headers = {"Idempotency-Key": reset["attempt_key"]}
    record = client.post("/api/runs/detect", json={}, headers=headers)
    assert record.status_code == 200, record.text
    r = record.json()
    run_id = r["run"]["run_id"]
    assert client.post("/api/runs/detect", json={}, headers=headers).json() == r
    assert len(client.get("/api/runs").json()) == 1
    assert client.get(f"/api/runs/{run_id}").json() == r
    assert client.get(f"/api/runs/{run_id}/events").status_code == 200
    assert client.post(f"/api/runs/{run_id}/assemble", json={"revision": 1}).status_code == 422
    result = client.post(f"/api/runs/{run_id}/assemble", json={"revision": 1}, headers=headers)
    assert result.status_code == 200, result.text
    assert (
        client.post(f"/api/runs/{run_id}/assemble", json={"revision": 1}, headers=headers).json()
        == result.json()
    )
    assert (
        client.post(
            f"/api/runs/{run_id}/assemble", json={"revision": 2}, headers=headers
        ).status_code
        == 409
    )
    card = client.post(
        f"/api/runs/{run_id}/request-approval",
        json={"revision": result.json()["revision"]},
        headers=headers,
    )
    assert card.status_code == 200, card.text
    assert (
        client.post(
            f"/api/runs/{run_id}/request-approval",
            json={"revision": result.json()["revision"]},
            headers=headers,
        ).json()
        == card.json()
    )
    assert len(approvals.calls) == 1
    assert client.post(f"/internal/runs/{run_id}/execute").status_code == 404
    assert client.get(f"/api/runs/{uuid4()}").status_code == 404
    assert (
        client.post(
            "/api/runs/detect", json={"contract_id": "northwind"}, headers=headers
        ).status_code
        == 403
    )
    assert client.post("/api/runs/detect", json={}).status_code == 422
    assert client.get("/privacy").status_code == client.get("/terms").status_code == 200
    assert client.get("/health/ready").status_code == 503
    store.save_teams_reference({"id": "ref"})
    assert client.get("/health/ready").status_code == 200


def test_http_pricing_bound_to_run(api: Any) -> None:
    client, (c, _, _, _, _) = api
    r = detected(c)
    body = {
        "run_id": str(r.run.run_id),
        "correlation_id": str(r.run.correlation_id),
        "contract_id": r.run.contract_id,
    }
    assert client.post("/api/tools/pricing", json=body).status_code == 403
    c.record(r, "test.assembling", "controller", target=RunState.CONTEXT_ASSEMBLING)
    result = client.post("/api/tools/pricing", json=body)
    assert result.status_code == 200 and result.json()["discount_amount"] == "14400.00"
    assert client.post("/api/tools/pricing", json=body | {"annual_value": "1"}).status_code == 422


def test_http_unconfigured_and_wrong_owner(api: Any) -> None:
    client, (c, store, _, _, _) = api
    r = detected(c)
    store.records[r.run.run_id] = r.model_copy(
        update={"run": r.run.model_copy(update={"owner_user_id": "outsider"})}
    )
    assert client.get(f"/api/runs/{r.run.run_id}").status_code == 403
    c.settings.api_audience = ""
    assert client.get("/health/ready").status_code == 503


@pytest.fixture
def signed_api(system: Any, monkeypatch: Any) -> tuple[TestClient, Any, Any, dict[str, Any]]:
    c, _, _, _, _ = system
    application = create_app(c.settings, c)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        application.state.auth.keys,
        "get_signing_key_from_jwt",
        lambda _: SimpleNamespace(key=key.public_key()),
    )
    claims = {
        "aud": c.settings.api_audience,
        "iss": f"https://login.microsoftonline.com/{c.settings.tenant_id}/v2.0",
        "tid": c.settings.tenant_id,
        "oid": c.settings.approver_user_id,
        "exp": int(time.time()) + 600,
        "iat": int(time.time()) - 10,
        "nbf": int(time.time()) - 10,
        "scp": "user_impersonation",
    }
    return TestClient(application), c, key, claims


def test_real_jwt_validation_allows_only_expected_user_and_agent(signed_api: Any) -> None:
    client, c, key, claims = signed_api

    def bearer(data: Any) -> dict[str, str]:
        return {"Authorization": "Bearer " + jwt.encode(data, key, algorithm="RS256")}

    assert client.get("/api/runs", headers=bearer(claims)).status_code == 200
    assert client.get("/api/runs").status_code == 401
    for field, value, code in [
        ("tid", "foreign", 403),
        ("oid", "impostor", 403),
        ("aud", "foreign", 401),
        ("iss", "foreign", 401),
        ("exp", 1, 401),
        ("scp", "", 403),
    ]:
        assert client.get("/api/runs", headers=bearer(claims | {field: value})).status_code == code
    r = detected(c)
    c.record(r, "test.assembling", "controller", target=RunState.CONTEXT_ASSEMBLING)
    body = {
        "run_id": str(r.run.run_id),
        "correlation_id": str(r.run.correlation_id),
        "contract_id": r.run.contract_id,
    }
    assert client.post("/api/tools/pricing", json=body, headers=bearer(claims)).status_code == 403
    agent_claims = claims | {"oid": c.settings.agent_principal_id, "roles": ["Pricing.Read"]}
    agent_claims.pop("scp")
    assert (
        client.post("/api/tools/pricing", json=body, headers=bearer(agent_claims)).status_code
        == 200
    )
    assert client.get("/api/runs", headers=bearer(agent_claims)).status_code == 403


def test_telemetry_no_content_capture(monkeypatch: Any) -> None:
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    configure_telemetry(MagicMock())
    configure = MagicMock()
    monkeypatch.setattr("azure.monitor.opentelemetry.configure_azure_monitor", configure)
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "offline-placeholder")
    configure_telemetry(MagicMock())
    kwargs = configure.call_args.kwargs
    assert kwargs["logger_name"] == "innexq.audit"
    assert all(not item["enabled"] for item in kwargs["instrumentation_options"].values())
