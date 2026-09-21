import json
from pathlib import Path

import yaml


def test_azd_configuration_preserves_the_approved_service_boundaries() -> None:
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / "azure.yaml").read_text(encoding="utf-8"))
    services = config["services"]
    assert set(services) == {
        "innexq-api",
        "innexq-agent",
        "innexq-web",
        "innexq-customer",
        "innexq-certificate-team",
    }
    assert config["infra"]["provider"] == "terraform"
    for name, host in (
        ("innexq-api", "containerapp"),
        ("innexq-agent", "azure.ai.agent"),
        ("innexq-web", "containerapp"),
        ("innexq-customer", "containerapp"),
        ("innexq-certificate-team", "azure.ai.agent"),
    ):
        service = services[name]
        assert service["host"] == host
        # azd normalizes YAML and omits the optional false value after provisioning.
        assert isinstance(service["docker"].get("remoteBuild", False), bool)
        dockerfile = root / service["project"] / service["docker"]["path"]
        assert dockerfile.is_file()
    assert services["innexq-api"]["docker"].get("remoteBuild", False) is False
    assert (
        services["innexq-certificate-team"]["env"]["INNEXQ_AGENT_PACK"] == "certificate_fulfilment"
    )
    assert "INNEXQ_AGENT_PACK" not in services["innexq-agent"]["env"]


def test_evidence_identity_settings_are_explicit_azd_terraform_inputs() -> None:
    inputs = json.loads(Path("infra/main.tfvars.json").read_text(encoding="utf-8"))
    for name in (
        "evidence_identity_enabled",
        "evidence_broker_enabled",
        "evidence_agent_principal_id",
        "evidence_runtime_enabled",
    ):
        assert inputs[name] == "${TF_VAR_" + name + "}"
    source = Path("infra/evidence.tf").read_text(encoding="utf-8")
    assert "evidence_api_env = var.evidence_broker_enabled ?" in source
    assert "INNEXQ_EVIDENCE_TOOLS_ENABLED      = tostring(var.evidence_runtime_enabled)" in source
    assert "INNEXQ_EVIDENCE_BROKER_ENABLED     = tostring(var.evidence_broker_enabled)" in source
    assert "!var.evidence_runtime_enabled || (var.evidence_broker_enabled" in source
    assert (
        "!var.evidence_broker_enabled || (var.evidence_identity_enabled && "
        "var.certificate_runtime_enabled)" in source
    )
    broker_variable = source.split('variable "evidence_broker_enabled" {', 1)[1].split(
        'variable "evidence_agent_principal_id"', 1
    )[0]
    assert "default = false" in broker_variable


def test_certificate_infrastructure_is_opt_in_and_separates_read_identity() -> None:
    source = Path("infra/certificates.tf").read_text(encoding="utf-8")
    assert 'variable "certificate_infrastructure_enabled"' in source
    assert 'variable "certificate_runtime_enabled"' in source
    assert source.count("default = false") == 2
    assert 'role_definition_name = "Storage Blob Data Reader"' in source
    assert 'kind                  = "FormRecognizer"' in source
    assert "local_auth_enabled    = false" in source
    assert "app_role_assignment_required = true" in source
    assert '"DEMO-ALP"' not in source
    assert "Mail.Send" not in source and "Sites.Selected" not in source


def test_azd_explicitly_maps_sharepoint_destination_inputs() -> None:
    root = Path(__file__).resolve().parents[2]
    variables = json.loads((root / "infra/main.tfvars.json").read_text(encoding="utf-8"))
    for name in ("graph_site_id", "graph_drive_id", "graph_folder_id"):
        assert variables[name] == "${TF_VAR_" + name + "}"


def test_azd_maps_the_actual_hosted_identity_without_using_executor_identity() -> None:
    root = Path(__file__).resolve().parents[2]
    variables = json.loads((root / "infra/main.tfvars.json").read_text(encoding="utf-8"))
    assert variables["agent_principal_id"] == "${TF_VAR_agent_principal_id}"


def test_deployed_api_explicitly_pins_the_validated_agent_release() -> None:
    root = Path(__file__).resolve().parents[2]
    configuration = (root / "infra/api.tf").read_text(encoding="utf-8")
    version_line = next(
        line for line in configuration.splitlines() if "INNEXQ_FOUNDRY_AGENT_VERSION" in line
    )
    assert version_line.split("=", 1)[1].strip() == '"2"'


def test_azd_maps_certificate_flags_and_agent_build_includes_team() -> None:
    variables = json.loads(Path("infra/main.tfvars.json").read_text(encoding="utf-8"))
    for name in (
        "certificate_infrastructure_enabled",
        "certificate_runtime_enabled",
        "certificate_agent_version",
    ):
        assert variables[name] == "${TF_VAR_" + name + "}"
    assert (
        "!certificate_team.py"
        in Path("src/agent/.dockerignore").read_text(encoding="utf-8").splitlines()
    )
