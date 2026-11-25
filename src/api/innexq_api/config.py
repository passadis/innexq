"""Safe application configuration conventions."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Non-secret settings loaded from the INNEXQ_ namespace."""

    model_config = SettingsConfigDict(
        env_prefix="INNEXQ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["local", "dev", "demo"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    web_origins: list[str] = []
    customer_origins: list[str] = []
    certificates_enabled: bool = False
    customer_bindings: dict[str, str] = {}
    certificate_blob_endpoint: str = ""
    certificate_reader_client_id: str = ""
    certificate_container: str = "certificate-sources"
    document_intelligence_endpoint: str = ""
    certificate_agent_name: str = ""
    certificate_agent_version: str = ""
    evidence_broker_enabled: bool = False
    evidence_tools_enabled: bool = False
    evidence_agent_principal_id: str = ""
    evidence_agent_client_id: str = ""
    evidence_api_host: str = ""
    renewal_enabled: bool = False
    renewal_coverage_container: str = "coverage"
    renewal_issued_container: str = "issued-coverage"
    renewal_blob_endpoint: str = ""
    renewal_operations_object_id: str = ""
    renewal_manager_object_id: str = ""
    renewal_agent_name: str = ""
    renewal_agent_version: str = ""
    renewal_scenarios_path: str = "corpus/fixtures/coverage-scenarios.json"
    renewal_policy_path: str = "corpus/fixtures/coverage-renewal-policy-v1.json"

    @model_validator(mode="after")
    def evidence_identity_gate(self) -> "Settings":
        if self.evidence_tools_enabled and not self.evidence_broker_enabled:
            raise ValueError("evidence candidate runtime requires the broker gate")
        if self.evidence_broker_enabled:
            import re
            from uuid import UUID

            if not self.certificates_enabled or not self.api_audience:
                raise ValueError("certificate runtime and explicit audience required for evidence")
            UUID(self.evidence_agent_principal_id)
            UUID(self.evidence_agent_client_id)
            if not re.fullmatch(
                r"[a-z0-9-]+\.[a-z0-9-]+\.[a-z0-9]+\.azurecontainerapps\.io", self.evidence_api_host
            ):
                raise ValueError("exact evidence API hostname required")
        return self

    @field_validator("web_origins", "customer_origins")
    @classmethod
    def exact_https_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in value
            ):
                raise ValueError("web origins must be exact HTTPS origins")
        return values

    tenant_id: str = "35de4c50-7dcd-4871-8685-61789c017da2"
    approver_user_id: str = "11b101d5-96dd-4d25-ad68-38b54de937bf"
    manager_user_id: str = ""

    @model_validator(mode="after")
    def distinct_employee_roles(self) -> "Settings":
        if self.manager_user_id:
            from uuid import UUID

            manager = UUID(self.manager_user_id)
            if manager == UUID(self.approver_user_id) or str(manager) in self.customer_bindings:
                raise ValueError("Manager must be distinct from Operations and customers")
        if self.approver_user_id in self.customer_bindings:
            raise ValueError("Operations must be distinct from customers")
        return self

    @model_validator(mode="after")
    def renewal_identity_gate(self) -> "Settings":
        if not self.renewal_enabled:
            return self
        from uuid import UUID

        if not self.certificates_enabled or not self.api_audience:
            raise ValueError("certificate runtime and explicit audience required for renewal")
        operations = UUID(self.renewal_operations_object_id)
        manager = UUID(self.renewal_manager_object_id)
        if operations == manager:
            raise ValueError("renewal Operations and Manager must be distinct identities")
        if not self.renewal_blob_endpoint.startswith("https://"):
            raise ValueError("renewal requires an exact HTTPS blob endpoint")
        return self

    api_audience: str = ""
    agent_principal_id: str = ""
    managed_identity_client_id: str = ""
    cosmos_endpoint: str = ""
    cosmos_database: str = "innexq"
    cosmos_container: str = "runs"
    foundry_project_endpoint: str = ""
    foundry_agent_name: str = "innexq-agent"
    foundry_agent_version: str = "1"
    graph_site_id: str = ""
    graph_drive_id: str = ""
    graph_folder_id: str = ""
    graph_output_folder_url: str = ""

    @field_validator("graph_output_folder_url")
    @classmethod
    def approved_output_link(cls, value: str) -> str:
        # The owner-confirmed output location, not a sharing link or arbitrary URL.
        if value not in (
            "",
            "https://passadisoutlook498.sharepoint.com/sites/InnexQ/InnexQDocs/Output",
        ):
            raise ValueError("output link must match the approved SharePoint folder")
        return value

    sender_mailbox: str = "superuser@alfacloud.gr"
    test_recipient: str = "passadis@outlook.com"
    teams_team_id: str = "ee42f3fa-d2aa-4033-99ef-bddea5363b46"
    teams_channel_id: str = "19:f87553c02fda46978cf84bf2e965dcf3@thread.tacv2"
    corpus_path: str = "corpus/blob/phase1.json"
    contract_path: str = "corpus/fixtures/fabrikam-contract.json"
    policy_path: str = "corpus/fixtures/phase1-policy.json"
