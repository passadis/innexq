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
