import pytest
from fastapi.testclient import TestClient
from innexq_api.config import Settings
from innexq_api.main import app

client = TestClient(app)


def test_liveness() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness() -> None:
    response = client.get("/health/ready")
    assert response.status_code == 503


def test_configuration_defaults_are_safe() -> None:
    settings = Settings(_env_file=None)
    assert settings.environment == "local"
    assert settings.log_level == "INFO"
    assert settings.renewal_enabled is False


OPERATIONS = "11b101d5-96dd-4d25-ad68-38b54de937bf"
MANAGER = "4243bff0-ef6a-4c2a-a3ae-8ee20fd4a1b8"


def renewal_settings(**changes: object) -> Settings:
    base = {
        "_env_file": None,
        "renewal_enabled": True,
        "certificates_enabled": True,
        "api_audience": "audience",
        "renewal_operations_object_id": OPERATIONS,
        "renewal_manager_object_id": MANAGER,
        "renewal_blob_endpoint": "https://stinnexq123.blob.core.windows.net",
    }
    return Settings(**(base | changes))


def test_renewal_gate_accepts_distinct_identities_and_https_endpoint() -> None:
    settings = renewal_settings()
    assert settings.renewal_enabled and settings.renewal_coverage_container == "coverage"


@pytest.mark.parametrize(
    "changes",
    [
        {"certificates_enabled": False},
        {"api_audience": ""},
        {"renewal_manager_object_id": OPERATIONS},
        {"renewal_blob_endpoint": "http://insecure.example"},
    ],
)
def test_renewal_gate_rejects_unsafe_configuration(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        renewal_settings(**changes)
