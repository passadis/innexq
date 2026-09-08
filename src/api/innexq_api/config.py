"""Safe application configuration conventions."""

from typing import Literal

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
    tenant_id: str = "35de4c50-7dcd-4871-8685-61789c017da2"
    approver_user_id: str = "11b101d5-96dd-4d25-ad68-38b54de937bf"
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
    sender_mailbox: str = "superuser@alfacloud.gr"
    test_recipient: str = "passadis@outlook.com"
    teams_team_id: str = "ee42f3fa-d2aa-4033-99ef-bddea5363b46"
    teams_channel_id: str = "19:f87553c02fda46978cf84bf2e965dcf3@thread.tacv2"
    corpus_path: str = "corpus/blob/phase1.json"
    contract_path: str = "corpus/fixtures/fabrikam-contract.json"
    policy_path: str = "corpus/fixtures/phase1-policy.json"
