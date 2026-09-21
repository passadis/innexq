from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from innexq_api.auth import EntraAuth
from innexq_api.certificates import EvidenceUnavailable
from innexq_api.config import Settings
from innexq_api.controller import Denied
from innexq_api.customer_routes import CustomerRequest, customer_app
from innexq_api.store import Conflict
from pydantic import ValidationError

ACTOR = UUID("b6491861-0f01-451a-aa40-fd1957c20747")
TENANT = UUID("35de4c50-7dcd-4871-8685-61789c017da2")
REQUEST_ID = uuid4()
ORIGIN = "https://customer.example.test"
STAFF_ORIGIN = "https://control.example.test"
PDF = b"%PDF-1.7\ncustomer route unit fixture"


class Runtime:
    error: Exception | None = None

    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []

    def check(self, tenant_id: UUID, actor_id: UUID) -> None:
        self.calls.append((tenant_id, actor_id))
        if self.error:
            raise self.error

    def catalog(self, tenant_id: UUID, actor_id: UUID) -> dict[str, Any]:
        self.check(tenant_id, actor_id)
        return {"equipment": [{"equipment_id": "DEMO-PT-001"}], "presets": []}

    def status(self, tenant_id: UUID, actor_id: UUID, request_id: UUID) -> dict[str, str]:
        self.check(tenant_id, actor_id)
        return {
            "request_id": str(request_id),
            "status": "operations_required",
            "case_status": "acknowledged",
            "updated_at": "2026-09-18T09:00:00Z",
            "message": "Operations is reviewing this request.",
            "internal_reason": "must not be exposed",
            "source_version": "private-etag",
        }

    def request(self, tenant_id: UUID, actor_id: UUID, body: CustomerRequest) -> dict[str, str]:
        return self.status(tenant_id, actor_id, body.request_id)

    def download(self, tenant_id: UUID, actor_id: UUID, request_id: UUID) -> bytes:
        self.check(tenant_id, actor_id)
        return PDF


def setup(runtime: Runtime | None = None, *, override_identity: bool = True) -> TestClient:
    settings = Settings(
        _env_file=None,
        customer_origins=[ORIGIN],
        web_origins=[STAFF_ORIGIN],
        customer_bindings={str(ACTOR): "DEMO-FAB"},
        api_audience="audience",
    )
    app = customer_app(settings, EntraAuth(settings), lambda: runtime)
    if override_identity:
        app.dependency_overrides[app.state.customer_dependency] = lambda: (TENANT, ACTOR)
    return TestClient(app, raise_server_exceptions=False)


def test_catalog_uses_only_verified_identity() -> None:
    runtime = Runtime()
    client = setup(runtime)
    response = client.get("/catalog", params={"customer_id": "DEMO-NW", "actor_id": str(uuid4())})
    assert response.status_code == 200
    assert runtime.calls == [(TENANT, ACTOR)]
    assert response.headers["Cache-Control"] == "no-store"


def test_status_and_submission_project_only_public_fields() -> None:
    runtime = Runtime()
    client = setup(runtime)
    body = {
        "request_id": str(REQUEST_ID),
        "equipment_id": "DEMO-PT-001",
        "prompt": "My certificate",
    }
    for response in [client.post("/requests", json=body), client.get(f"/requests/{REQUEST_ID}")]:
        assert response.status_code == 200
        assert set(response.json()) == {
            "request_id",
            "status",
            "message",
            "case_status",
            "updated_at",
        }
        assert "private-etag" not in response.text
        assert response.headers["Cache-Control"] == "no-store"


def test_download_is_attachment_nosniff_no_store_and_sandboxed() -> None:
    client = setup(Runtime())
    response = client.get(f"/requests/{REQUEST_ID}/pdf")
    assert response.content == PDF and response.headers["Content-Type"] == "application/pdf"
    assert (
        response.headers["Content-Disposition"] == f'attachment; filename="innexq-{REQUEST_ID}.pdf"'
    )
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == "sandbox; default-src 'none'"


@pytest.mark.parametrize(
    "path", ["/catalog", f"/requests/{REQUEST_ID}", f"/requests/{REQUEST_ID}/pdf"]
)
def test_disabled_runtime_is_503_and_no_store(path: str) -> None:
    response = setup().get(path)
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "error,status",
    [
        (Denied("secret foreign customer facts"), 404),
        (KeyError("secret absent identifier"), 404),
        (Conflict("secret revision"), 409),
        (EvidenceUnavailable("secret provider response"), 503),
        (RuntimeError("secret programming details"), 503),
    ],
)
def test_errors_are_private_generic_and_not_cached(error: Exception, status: int) -> None:
    runtime = Runtime()
    runtime.error = error
    response = setup(runtime).get(f"/requests/{REQUEST_ID}")
    assert response.status_code == status
    assert "secret" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_missing_bearer_is_401_before_runtime() -> None:
    runtime = Runtime()
    response = setup(runtime, override_identity=False).get("/catalog")
    assert response.status_code == 401 and runtime.calls == []
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "origin,allowed", [(ORIGIN, True), (STAFF_ORIGIN, False), ("https://evil.example.test", False)]
)
def test_customer_cors_is_exact_and_separate(origin: str, allowed: bool) -> None:
    client = setup(Runtime())
    response = client.get("/catalog", headers={"Origin": origin})
    assert (response.headers.get("Access-Control-Allow-Origin") == origin) is allowed
    preflight = client.options(
        "/requests",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert preflight.status_code == (200 if allowed else 400)
    assert preflight.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "change",
    [
        {"customer_id": "DEMO-NW"},
        {"tenant_id": str(uuid4())},
        {"actor_id": str(uuid4())},
        {"equipment_id": "../../private"},
        {"prompt": ""},
        {"prompt": "a" * 1001},
    ],
)
def test_customer_body_cannot_supply_authority_or_unbounded_input(change: dict[str, Any]) -> None:
    runtime = Runtime()
    response = setup(runtime).post(
        "/requests",
        json={
            "request_id": str(REQUEST_ID),
            "equipment_id": "DEMO-PT-001",
            "prompt": "Certificate please",
            **change,
        },
    )
    assert response.status_code == 422 and runtime.calls == []
    assert response.headers["Cache-Control"] == "no-store"


def test_public_schema_disabled_and_invalid_uuid_not_forwarded() -> None:
    runtime = Runtime()
    client = setup(runtime)
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/requests/invalid/pdf").status_code == 422
    assert runtime.calls == []


@pytest.mark.parametrize(
    "claim_changes",
    [
        {"scp": "Runs.Read"},
        {"scp": "user_impersonation"},
        {"scp": ""},
        {"scp": None},
        {"scp": ["Certificates.Request"]},
        {"idtyp": "app"},
        {"oid": str(uuid4())},
        {"scp": "", "roles": ["Certificates.Request"]},
    ],
)
def test_customer_auth_denies_wrong_scope_app_only_and_unassigned(
    monkeypatch: pytest.MonkeyPatch, claim_changes: dict[str, Any]
) -> None:
    settings = Settings(_env_file=None, customer_bindings={str(ACTOR): "DEMO-FAB"})
    auth = EntraAuth(settings)
    claims = {"tid": str(TENANT), "oid": str(ACTOR), "scp": "Certificates.Request", **claim_changes}
    monkeypatch.setattr(auth, "claims", lambda request: claims)
    with pytest.raises(HTTPException) as error:
        auth.customer(Request({"type": "http", "headers": []}))
    assert error.value.status_code == 403


def test_customer_auth_permits_assigned_delegated_user(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, customer_bindings={str(ACTOR): "DEMO-FAB"})
    auth = EntraAuth(settings)
    monkeypatch.setattr(
        auth,
        "claims",
        lambda request: {
            "tid": str(TENANT),
            "oid": str(ACTOR),
            "scp": "openid Certificates.Request",
        },
    )
    assert auth.customer(Request({"type": "http", "headers": []})) == (str(TENANT), str(ACTOR))


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "http://example.test",
        ORIGIN + "/",
        ORIGIN + "/path",
        ORIGIN + "?query=true",
        "https://user:password@example.test",  # pragma: allowlist secret
    ],
)
def test_configuration_rejects_unsafe_customer_cors(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, customer_origins=[origin])
