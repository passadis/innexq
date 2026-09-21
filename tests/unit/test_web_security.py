from typing import Any
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from innexq_api.config import Settings
from innexq_api.main import create_app

from tests.unit.test_http_security import signed_api  # noqa: F401


def test_read_scope_cannot_trigger_any_workflow_or_agent_write(signed_api: Any) -> None:  # noqa: F811
    client, _, key, claims = signed_api
    headers = {
        "Authorization": "Bearer "
        + jwt.encode(claims | {"scp": "Runs.Read"}, key, algorithm="RS256"),
        "Idempotency-Key": "read-only-test-command",
    }
    assert client.get("/api/runs", headers=headers).status_code == 200
    assert client.get("/api/runs", headers=headers).headers["cache-control"] == "no-store"
    for path, body in [
        ("/api/runs/detect", {}),
        ("/api/demo/reset", {}),
        (f"/api/runs/{uuid4()}/assemble", {"revision": 1}),
        (f"/api/runs/{uuid4()}/request-approval", {"revision": 1}),
        (
            "/api/tools/pricing",
            {"run_id": str(uuid4()), "correlation_id": str(uuid4()), "contract_id": "test"},
        ),
    ]:
        assert client.post(path, json=body, headers=headers).status_code == 403
    other_actor = claims | {"scp": "Runs.Read", "oid": str(uuid4())}
    assert (
        client.get(
            "/api/runs",
            headers={"Authorization": "Bearer " + jwt.encode(other_actor, key, algorithm="RS256")},
        ).status_code
        == 403
    )


def test_cors_is_exact_origin_and_get_only() -> None:
    client = TestClient(create_app(Settings(web_origins=["https://web.example.test"])))

    def preflight(origin: str, method: str) -> Any:
        return client.options(
            "/api/runs",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "authorization",
            },
        )

    response = preflight("https://web.example.test", "GET")
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://web.example.test"
    assert "access-control-allow-credentials" not in response.headers
    assert preflight("https://web.example.test", "POST").status_code == 400
    assert preflight("https://evil.example.test", "GET").status_code == 400


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "http://example.test",
        "https://example.test/",
        "https://user:pass@example.test",  # pragma: allowlist secret -- rejected fixture URL
        "https://example.test?redirect=evil",
    ],
)
def test_invalid_web_origin_config_is_rejected(origin: str) -> None:
    with pytest.raises(ValueError):
        Settings(web_origins=[origin])
