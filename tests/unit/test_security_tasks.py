import pytest

from scripts.tasks import assert_no_deployment_state


def test_deployment_state_cannot_be_committed() -> None:
    assert_no_deployment_state(
        [".azure/deployment-plan.md", ".azure/.gitignore", "src/api/main.py"]
    )
    for path in [
        ".azure/dev/.env",
        ".azure\\dev\\infra\\main.tfplan",
        "infra/terraform.tfstate",
        "infra/terraform.tfstate.backup",
    ]:
        with pytest.raises(ValueError, match="never be tracked"):
            assert_no_deployment_state([path])
