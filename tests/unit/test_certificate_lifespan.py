"""Offline app integration: identity separation, resource cleanup and CORS boundaries."""

import asyncio
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient
from innexq_api.certificate_store import CertificateNotification
from innexq_api.config import Settings
from innexq_api.main import create_app

from tests.unit.test_certificate_store import setup as store_setup
from tests.unit.test_certificates import CUSTOMER, REQUEST, TENANT
from tests.unit.test_customer_routes import ACTOR, ORIGIN, STAFF_ORIGIN, Runtime
from tests.unit.test_http_security import signed_api  # noqa: F401

EXECUTOR_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
READER_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest.fixture
def bootstrap(monkeypatch):
    executor, reader = MagicMock(), MagicMock()
    store, controller, certificate_runtime, certificate_store = (MagicMock() for _ in range(4))
    teams = MagicMock()
    teams.initialize = AsyncMock()
    task_state = {"started": False, "cancelled": False}

    async def notifications():
        task_state["started"] = True
        try:
            await asyncio.Future()
        finally:
            task_state["cancelled"] = True

    factories = {}
    for path, value in {
        "innexq_api.adapters.workload_credential": executor,
        "innexq_api.telemetry.configure_telemetry": None,
        "innexq_api.store.CosmosStore": store,
        "innexq_api.teams.TeamsApprovals": teams,
        "innexq_api.adapters.FoundryAgent": MagicMock(),
        "innexq_api.adapters.GraphExecutor": MagicMock(),
        "innexq_api.main.Controller": controller,
        "azure.identity.ManagedIdentityCredential": reader,
        "innexq_api.certificate_store.CosmosCertificateStore": certificate_store,
        "innexq_api.certificate_runtime.CertificateApplication": certificate_runtime,
        "innexq_api.certificate_repository.PrivateCertificateRepository": MagicMock(),
        "innexq_api.document_extraction.DocumentIntelligenceExtractor": MagicMock(),
        "innexq_api.certificate_runtime.HostedCertificateTeam": MagicMock(),
        "innexq_api.certificate_notifications.CertificateNotifications": MagicMock(
            run=notifications
        ),
        "innexq_api.adapters.CoverageBlobStorage": MagicMock(),
        "innexq_api.coverage_store.CosmosCoverageStore": MagicMock(),
        "innexq_api.coverage_sources.FixtureCoverageSourceReader": MagicMock(),
        "innexq_api.coverage_sources.FixtureCoverageInvestigator": MagicMock(),
        "innexq_api.coverage_controller.CoverageController": MagicMock(),
        "innexq_api.coverage_executor.CoverageExecutor": MagicMock(),
        "innexq_api.main.CoverageReviewService": MagicMock(),
        "innexq_api.coverage_customer.CoverageCustomerRuntime": MagicMock(),
        "innexq_api.coverage_runner.CoverageExecutionRunner": MagicMock(),
    }.items():
        factory = MagicMock(return_value=value)
        monkeypatch.setattr(path, factory)
        factories[path.rsplit(".", 1)[1]] = factory
    settings = Settings(
        _env_file=None,
        cosmos_endpoint="https://cosmos.example.invalid",
        certificates_enabled=True,
        managed_identity_client_id=EXECUTOR_ID,
        certificate_reader_client_id=READER_ID,
        customer_bindings={str(ACTOR): "DEMO-FAB"},
        customer_origins=[ORIGIN],
        web_origins=[STAFF_ORIGIN],
    )
    return settings, factories, executor, reader, task_state


def test_enabled_startup_wires_separate_retrieval_identity_and_cancels_worker(bootstrap):
    settings, factories, executor, reader, task_state = bootstrap
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert task_state["started"] and not task_state["cancelled"]
        assert app.state.certificates is factories["CertificateApplication"].return_value
        factories["ManagedIdentityCredential"].assert_called_once_with(client_id=READER_ID)
        assert factories["PrivateCertificateRepository"].call_args.args[-1] is reader
        assert factories["DocumentIntelligenceExtractor"].call_args.args[-1] is reader
        assert factories["GraphExecutor"].call_args.args[-1] is executor
        assert factories["FoundryAgent"].call_args.args[-1] is executor
        assert factories["HostedCertificateTeam"].call_args.args[-1] is executor
        assert factories["CosmosStore"].call_args.args[1] is executor
        assert factories["CosmosCertificateStore"].call_args.args[0] is (
            factories["CosmosStore"].return_value.container
        )
        factories["CertificateNotifications"].assert_called_once_with(
            factories["CosmosCertificateStore"].return_value,
            factories["TeamsApprovals"].return_value,
            UUID(settings.tenant_id),
            UUID(settings.approver_user_id),
        )
        executor.close.assert_not_called()
        reader.close.assert_not_called()
    assert task_state["cancelled"]
    executor.close.assert_called_once()
    reader.close.assert_called_once()


@pytest.mark.parametrize("missing", ["bindings", "origins", "reader", "separate_reader"])
def test_enabled_startup_rejects_missing_identity_or_origin_and_closes_executor(bootstrap, missing):
    settings, factories, executor, reader, _ = bootstrap
    if missing == "bindings":
        settings.customer_bindings = {}
    elif missing == "origins":
        settings.customer_origins = []
    elif missing == "reader":
        settings.certificate_reader_client_id = ""
    else:
        settings.certificate_reader_client_id = EXECUTOR_ID
    with pytest.raises(ValueError):
        with TestClient(create_app(settings)):
            pytest.fail("invalid configuration reached ready lifespan")
    executor.close.assert_called_once()
    reader.close.assert_not_called()
    factories["ManagedIdentityCredential"].assert_not_called()
    factories["CertificateNotifications"].assert_not_called()


@pytest.mark.parametrize("stage", ["telemetry", "cosmos", "teams", "repository", "extractor"])
def test_partial_startup_failure_closes_every_created_credential(bootstrap, stage):
    settings, factories, executor, reader, _ = bootstrap
    names = {
        "telemetry": "configure_telemetry",
        "cosmos": "CosmosStore",
        "repository": "PrivateCertificateRepository",
        "extractor": "DocumentIntelligenceExtractor",
    }
    if stage == "teams":
        factories["TeamsApprovals"].return_value.initialize.side_effect = RuntimeError("startup")
    else:
        factories[names[stage]].side_effect = RuntimeError("startup")
    with pytest.raises(RuntimeError, match="startup"):
        with TestClient(create_app(settings)):
            pytest.fail("failed startup was acknowledged")
    executor.close.assert_called_once()
    assert reader.close.call_count == int(stage in ("repository", "extractor"))
    factories["CertificateNotifications"].assert_not_called()


def test_reader_close_failure_still_closes_executor(bootstrap):
    settings, _, executor, reader, task_state = bootstrap
    reader.close.side_effect = RuntimeError("reader close")
    with pytest.raises(RuntimeError, match="reader close"):
        with TestClient(create_app(settings)) as client:
            assert client.get("/health/live").status_code == 200
    executor.close.assert_called_once()
    assert task_state["cancelled"]


def test_failed_background_task_still_closes_both_identities_on_shutdown(bootstrap):
    settings, factories, executor, reader, _ = bootstrap
    factories["CertificateNotifications"].return_value.run = AsyncMock(
        side_effect=RuntimeError("worker exited")
    )
    with pytest.raises(RuntimeError, match="worker exited"):
        with TestClient(create_app(settings)) as client:
            assert client.get("/health/live").status_code == 200
    reader.close.assert_called_once()
    executor.close.assert_called_once()


def test_disabled_pack_never_constructs_reader_or_certificate_worker(bootstrap):
    settings, factories, executor, reader, task_state = bootstrap
    settings.certificates_enabled = False
    settings.certificate_reader_client_id = ""
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
    for name in ("ManagedIdentityCredential", "CertificateApplication", "CertificateNotifications"):
        factories[name].assert_not_called()
    executor.close.assert_called_once()
    reader.close.assert_not_called()
    assert task_state == {"started": False, "cancelled": False}


def test_injected_local_runtime_never_creates_cloud_adapters(bootstrap):
    settings, factories, executor, reader, _ = bootstrap
    runtime = Runtime()
    app = create_app(settings, controller=MagicMock(), certificates=runtime)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert app.state.certificates is runtime
    assert all(factory.call_count == 0 for factory in factories.values())
    executor.close.assert_not_called()
    reader.close.assert_not_called()


def test_renewal_enabled_startup_wires_coverage_and_cancels_the_runner(bootstrap, monkeypatch):
    _, factories, _, _, _ = bootstrap
    coverage_state = {"started": False, "cancelled": False}

    async def coverage_worker():
        coverage_state["started"] = True
        try:
            await asyncio.Future()
        finally:
            coverage_state["cancelled"] = True

    monkeypatch.setattr(
        "innexq_api.coverage_runner.CoverageExecutionRunner",
        MagicMock(return_value=MagicMock(run=coverage_worker)),
    )
    settings = Settings(
        _env_file=None,
        cosmos_endpoint="https://cosmos.example.invalid",
        certificates_enabled=True,
        managed_identity_client_id=EXECUTOR_ID,
        certificate_reader_client_id=READER_ID,
        customer_bindings={str(ACTOR): "DEMO-FAB"},
        customer_origins=[ORIGIN],
        web_origins=[STAFF_ORIGIN],
        renewal_enabled=True,
        api_audience="api://innexq",
        renewal_operations_object_id="33333333-3333-4333-8333-333333333333",
        renewal_manager_object_id="44444444-4444-4444-8444-444444444444",
        renewal_blob_endpoint="https://issued.blob.core.windows.net",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert coverage_state["started"] and not coverage_state["cancelled"]
        assert app.state.coverage_review is factories["CoverageReviewService"].return_value
        factories["FixtureCoverageSourceReader"].assert_called_once_with(
            settings.renewal_scenarios_path, settings.renewal_policy_path
        )
        assert factories["CertificateApplication"].call_args.kwargs["coverage"] is (
            factories["CoverageCustomerRuntime"].return_value
        )
    assert coverage_state["cancelled"]


def test_disabled_renewal_never_constructs_coverage_runtime(bootstrap):
    settings, factories, _, _, _ = bootstrap
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
    assert app.state.coverage_review is None
    for name in ("CoverageCustomerRuntime", "CoverageReviewService", "CosmosCoverageStore"):
        factories[name].assert_not_called()


def test_mounted_customer_cors_does_not_inherit_employee_origin_or_methods():
    settings = Settings(_env_file=None, web_origins=[STAFF_ORIGIN], customer_origins=[ORIGIN])
    client = TestClient(create_app(settings))

    def preflight(path, origin, method):
        return client.options(
            path,
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    response = preflight("/api/customer/requests", ORIGIN, "POST")
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-credentials" not in response.headers
    assert preflight("/api/customer/catalog", STAFF_ORIGIN, "GET").status_code == 400
    assert preflight("/api/customer/requests", STAFF_ORIGIN, "POST").status_code == 400
    assert preflight("/api/runs", ORIGIN, "GET").status_code == 400
    assert preflight("/api/operations/certificates", ORIGIN, "GET").status_code == 400
    assert preflight("/api/runs", STAFF_ORIGIN, "POST").status_code == 400
    assert preflight("/api/customer/requests", ORIGIN, "DELETE").status_code == 400


def test_operations_case_read_requires_signed_approver_and_delegated_read_scope(
    signed_api: Any,  # noqa: F811
) -> None:
    client, controller, key, claims = signed_api
    from innexq_contracts.certificates import CertificateSources

    certificate_controller, evidence, certificate_store, _ = store_setup()
    evidence.value = CertificateSources()
    record = certificate_controller.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    notice = certificate_store.get_notification(REQUEST)
    assert isinstance(notice, CertificateNotification)
    store = MagicMock()
    store.list_operations_cases.return_value = [record]
    store.get_notification.return_value = replace(notice, tenant_id=UUID(claims["tid"]))
    client.app.state.certificate_store = store

    def headers(changes):
        return {"Authorization": "Bearer " + jwt.encode(claims | changes, key, algorithm="RS256")}

    response = client.get("/api/operations/certificates", headers=headers({"scp": "Runs.Read"}))
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()[0]["notification"]["state"] == "pending"
    store.list_operations_cases.assert_called_once_with(
        UUID(controller.settings.tenant_id), UUID(controller.settings.approver_user_id)
    )
    assert client.get("/api/operations/certificates").status_code == 401
    for changes in [
        {"oid": str(ACTOR), "scp": "Runs.Read"},
        {"oid": str(ACTOR), "scp": "Certificates.Request"},
        {"scp": "Certificates.Request"},
        {"scp": "", "roles": ["Runs.Read"]},
        {"tid": str(UUID(int=999)), "scp": "Runs.Read"},
    ]:
        assert (
            client.get("/api/operations/certificates", headers=headers(changes)).status_code == 403
        )
    assert store.list_operations_cases.call_count == 1
    assert (
        client.post(
            "/api/operations/certificates", headers=headers({"scp": "Runs.Read"})
        ).status_code
        == 405
    )
    client.app.state.certificate_store = None
    assert (
        client.get(
            "/api/operations/certificates", headers=headers({"scp": "Runs.Read"})
        ).status_code
        == 503
    )
