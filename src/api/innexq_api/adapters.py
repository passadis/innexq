"""Azure transport adapters. No workflow decisions belong in this module."""

import json
import logging
import re
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from azure.identity import AzureCliCredential, ManagedIdentityCredential
from innexq_contracts.events import AgentProposal
from innexq_contracts.models import Action, ActionType, Run

from innexq_api.assembly_diagnostics import opaque_id, reason_code, response_status
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
        from azure.ai.projects.models import VersionRefIndicator
        from starlette.concurrency import run_in_threadpool

        def invoke() -> AgentProposal:
            with AIProjectClient(
                endpoint=self.settings.foundry_project_endpoint, credential=self.credential
            ) as project:
                # Hosted agents use their dedicated endpoint. Pin a fresh session to
                # the configured immutable version; never reuse another Run's history.
                session = project.agents.create_session(
                    agent_name=self.settings.foundry_agent_name,
                    version_indicator=VersionRefIndicator(
                        agent_version=self.settings.foundry_agent_version
                    ),
                )
                diagnostic_ids = {
                    "run_id": str(run.run_id),
                    "correlation_id": str(run.correlation_id),
                    "agent_session_id": opaque_id(session.agent_session_id),
                }
                logging.getLogger("innexq.audit").info(
                    "foundry_session_created", extra=diagnostic_ids
                )
                with project.get_openai_client(
                    agent_name=self.settings.foundry_agent_name, max_retries=0
                ) as client:
                    response = client.responses.create(
                        input=json.dumps(
                            {
                                "run_id": str(run.run_id),
                                "correlation_id": str(run.correlation_id),
                                "contract_id": run.contract_id,
                            }
                        ),
                        extra_body={"agent_session_id": session.agent_session_id},
                    )
                    logging.getLogger("innexq.audit").info(
                        "foundry_response_received",
                        extra={
                            **diagnostic_ids,
                            "response_id": opaque_id(response.id),
                            "response_status": response_status(response.status),
                            "reason_code": reason_code(getattr(response.error, "message", None)),
                        },
                    )
                    if response.status != "completed":
                        raise Denied("Hosted Agent response did not complete")
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
                base = {"sender", "recipient", "subject", "content"}
                if set(p) not in (base, base | {"content_type"}):
                    raise Denied("unexpected email parameters")
                content_type = p.get("content_type", "Text")
                if content_type not in ("Text", "HTML"):
                    raise Denied("unsupported email content type")
                if p["sender"] != self.settings.sender_mailbox or (
                    p["recipient"] != self.settings.test_recipient
                ):
                    raise Denied("mail destination is not allowlisted")
                response = await client.post(
                    f"users/{quote(self.settings.sender_mailbox, safe='')}/sendMail",
                    json={
                        "message": {
                            "subject": p["subject"],
                            "body": {"contentType": content_type, "content": content},
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


class CoverageBlobStorage:
    """Private issued-coverage artifact store over authenticated Azure Blob REST.

    Uses the API managed identity with a bearer token (never account keys or SAS).
    Writes are create-only (If-None-Match: *) so an executor retry cannot overwrite
    an issued document; the executor's own receipt already makes retries return early.
    """

    _NAME = re.compile(r"^coverage/[0-9a-f-]{36}/[A-Za-z0-9-]{1,120}\.pdf$")
    _MAX_BYTES = 8 * 1024 * 1024

    def __init__(
        self,
        settings: Settings,
        credential: Any,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(settings.renewal_blob_endpoint)
        container = settings.renewal_issued_container
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not re.fullmatch(r"[a-z0-9]{3,24}\.blob\.core\.windows\.net", parsed.hostname)
            or parsed.netloc != parsed.hostname
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", container)
            or not 3 <= len(container) <= 63
        ):
            raise Denied("exact private issued-coverage Blob origin/container required")
        self._origin = f"{settings.renewal_blob_endpoint.rstrip('/')}/{container}"
        self._credential, self._transport = credential, transport

    def _url(self, blob_name: str) -> str:
        if not self._NAME.fullmatch(blob_name):
            raise Denied("issued-coverage blob name is not allowlisted")
        return f"{self._origin}/{'/'.join(quote(part, safe='') for part in blob_name.split('/'))}"

    def _headers(self) -> dict[str, str]:
        token = self._credential.get_token("https://storage.azure.com/.default").token
        return {"Authorization": f"Bearer {token}", "x-ms-version": "2023-11-03"}

    def write(self, blob_name: str, content: bytes) -> None:
        if len(content) > self._MAX_BYTES:
            raise Denied("issued-coverage artifact exceeds the safe size limit")
        url = self._url(blob_name)
        with httpx.Client(
            timeout=30, follow_redirects=False, transport=self._transport, trust_env=False
        ) as client:
            response = client.put(
                url,
                content=content,
                headers={
                    **self._headers(),
                    "x-ms-blob-type": "BlockBlob",
                    "Content-Type": "application/pdf",
                    "If-None-Match": "*",
                },
            )
        # A create-only conflict means the identical artifact already exists; that is idempotent.
        if response.status_code == 409:
            return
        if response.status_code not in (201, 202):
            raise Denied("issued-coverage write was not accepted")

    def read(self, blob_name: str) -> bytes:
        url = self._url(blob_name)
        with httpx.Client(
            timeout=30, follow_redirects=False, transport=self._transport, trust_env=False
        ) as client:
            with client.stream("GET", url, headers=self._headers()) as response:
                if response.status_code != 200 or not response.headers.get("etag"):
                    raise Denied("issued-coverage artifact unavailable")
                content = bytearray()
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > self._MAX_BYTES:
                        raise Denied("issued-coverage artifact size limit")
                    content.extend(chunk)
                return bytes(content)
