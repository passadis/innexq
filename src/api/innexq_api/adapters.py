"""Azure transport adapters. No workflow decisions belong in this module."""

import json
from typing import Any
from urllib.parse import quote

import httpx
from azure.identity import AzureCliCredential, ManagedIdentityCredential
from innexq_contracts.events import AgentProposal
from innexq_contracts.models import Action, ActionType, Run

from innexq_api.config import Settings
from innexq_api.controller import Denied, digest


def workload_credential(settings: Settings) -> Any:
    if settings.environment == "local":
        return AzureCliCredential(tenant_id=settings.tenant_id)
    if not settings.managed_identity_client_id:
        raise Denied("managed identity must be explicitly configured")
    return ManagedIdentityCredential(client_id=settings.managed_identity_client_id)


class FoundryAgent:
    def __init__(self, settings: Settings, credential: Any) -> None:
        self.settings, self.credential = settings, credential

    async def propose(self, run: Run) -> AgentProposal:
        from azure.ai.projects import AIProjectClient
        from starlette.concurrency import run_in_threadpool

        def invoke() -> AgentProposal:
            with AIProjectClient(
                endpoint=self.settings.foundry_project_endpoint, credential=self.credential
            ) as project:
                with project.get_openai_client() as client:
                    response = client.responses.create(
                        input=json.dumps(
                            {
                                "run_id": str(run.run_id),
                                "correlation_id": str(run.correlation_id),
                                "contract_id": run.contract_id,
                            }
                        ),
                        extra_body={
                            "agent": {
                                "type": "agent_reference",
                                "name": self.settings.foundry_agent_name,
                                "version": self.settings.foundry_agent_version,
                            }
                        },
                    )
                    return AgentProposal.model_validate_json(response.output_text)

        return await run_in_threadpool(invoke)


class GraphExecutor:
    def __init__(self, settings: Settings, credential: Any) -> None:
        self.settings, self.credential = settings, credential

    async def execute(self, action: Action) -> str:
        p = action.parameters
        content = p.get("content")
        if not isinstance(content, str) or digest(content) != action.artifact_hash:
            raise Denied("action content hash mismatch")
        token = self.credential.get_token("https://graph.microsoft.com/.default").token
        headers = {"Authorization": f"Bearer {token}", "client-request-id": str(action.action_id)}
        async with httpx.AsyncClient(
            base_url="https://graph.microsoft.com/v1.0/",
            headers=headers,
            timeout=30,
            follow_redirects=False,
        ) as client:
            if action.action_type == ActionType.SHAREPOINT_CREATE_FILE:
                if set(p) != {"drive_id", "folder_id", "filename", "content"}:
                    raise Denied("unexpected SharePoint parameters")
                if (
                    not self.settings.graph_drive_id
                    or not self.settings.graph_folder_id
                    or p["drive_id"] != self.settings.graph_drive_id
                    or p["folder_id"] != self.settings.graph_folder_id
                ):
                    raise Denied("SharePoint destination is not allowlisted")
                filename = p["filename"]
                if (
                    not isinstance(filename, str)
                    or not filename.startswith("innexq-")
                    or any(char in filename for char in ("/", "\\", ":", ".."))
                ):
                    raise Denied("invalid generated filename")
                drive = quote(self.settings.graph_drive_id, safe="")
                folder = quote(self.settings.graph_folder_id, safe="")
                path = f"drives/{drive}/items/{folder}:/{quote(filename, safe='')}:/content"
                response = await client.put(
                    path,
                    params={"@microsoft.graph.conflictBehavior": "fail"},
                    content=content.encode(),
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                )
                response.raise_for_status()
                return str(response.json()["id"])
            if action.action_type == ActionType.GRAPH_SEND_MAIL:
                if set(p) != {"sender", "recipient", "subject", "content"}:
                    raise Denied("unexpected email parameters")
                if p["sender"] != self.settings.sender_mailbox or (
                    p["recipient"] != self.settings.test_recipient
                ):
                    raise Denied("mail destination is not allowlisted")
                response = await client.post(
                    f"users/{quote(self.settings.sender_mailbox, safe='')}/sendMail",
                    json={
                        "message": {
                            "subject": p["subject"],
                            "body": {"contentType": "Text", "content": content},
                            "toRecipients": [{"emailAddress": {"address": p["recipient"]}}],
                            "internetMessageHeaders": [
                                {"name": "x-innexq-action-id", "value": str(action.action_id)}
                            ],
                        },
                        "saveToSentItems": True,
                    },
                )
                response.raise_for_status()
                # Graph accepts a send request; it does not prove recipient delivery.
                return f"accepted:{response.headers.get('request-id', str(action.action_id))}"
            raise Denied("unsupported external action")
