import asyncio
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from innexq_api.adapters import FoundryAgent, GraphExecutor, workload_credential
from innexq_api.config import Settings
from innexq_api.controller import Denied, digest
from innexq_api.store import Conflict, CosmosStore
from innexq_contracts.models import Action, ActionType

from tests.unit.test_controller import detected


def action(kind: ActionType = ActionType.SHAREPOINT_CREATE_FILE, **changes: Any) -> Action:
    params = {
        "drive_id": "drive",
        "folder_id": "folder",
        "filename": "innexq-test.txt",
        "content": "approved text",
    }
    if kind == ActionType.GRAPH_SEND_MAIL:
        params = {
            "sender": "superuser@alfacloud.gr",
            "recipient": "passadis@outlook.com",
            "subject": "synthetic",
            "content": "approved text",
        }
    return Action(
        action_id=uuid4(),
        action_type=kind,
        parameters=params | changes,
        artifact_hash=digest("approved text"),
        idempotency_key="test-action-00001",
    )


@pytest.fixture
def graph(monkeypatch: Any) -> tuple[GraphExecutor, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            202 if request.method == "POST" else 201,
            json={"id": "file-id"},
            headers={"request-id": "receipt"},
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        "innexq_api.adapters.httpx.AsyncClient",
        lambda **kw: client(transport=httpx.MockTransport(handle), **kw),
    )
    credential = MagicMock()
    credential.get_token.return_value.token = "offline-placeholder"  # noqa: S105
    return GraphExecutor(
        Settings(_env_file=None, graph_drive_id="drive", graph_folder_id="folder"), credential
    ), requests


def test_graph_exact_allowlisted_file_and_mail(graph: Any) -> None:
    executor, requests = graph
    assert asyncio.run(executor.execute(action())) == "file-id"
    assert asyncio.run(executor.execute(action(ActionType.GRAPH_SEND_MAIL))) == "accepted:receipt"
    assert requests[0].url.host == "graph.microsoft.com"
    assert requests[0].method == "PUT" and requests[1].method == "POST"
    assert requests[0].url.params["@microsoft.graph.conflictBehavior"] == "fail"
    assert requests[0].content == b"approved text"


@pytest.mark.parametrize(
    "changes",
    [
        {"content": "tampered"},
        {"drive_id": "other"},
        {"folder_id": "other"},
        {"filename": "../secret"},
        {"filename": "innexq-../escape"},
        {"extra": "field"},
    ],
)
def test_graph_file_rejects_unapproved_parameters(graph: Any, changes: Any) -> None:
    executor, requests = graph
    with pytest.raises(Denied):
        asyncio.run(executor.execute(action(**changes)))
    assert not requests


@pytest.mark.parametrize(
    "changes",
    [{"recipient": "outsider@example.com"}, {"sender": "outsider@example.com"}, {"extra": "field"}],
)
def test_graph_mail_rejects_unapproved_parameters(graph: Any, changes: Any) -> None:
    executor, requests = graph
    with pytest.raises(Denied):
        asyncio.run(executor.execute(action(ActionType.GRAPH_SEND_MAIL, **changes)))
    assert not requests


def test_graph_unsupported_action_denied(graph: Any) -> None:
    executor, requests = graph
    with pytest.raises(Denied, match="unsupported"):
        asyncio.run(executor.execute(action(ActionType.TEAMS_SEND_STATUS)))
    assert not requests


def test_workload_credentials_are_explicit(monkeypatch: Any) -> None:
    cli, managed = MagicMock(), MagicMock()
    monkeypatch.setattr("innexq_api.adapters.AzureCliCredential", cli)
    monkeypatch.setattr("innexq_api.adapters.ManagedIdentityCredential", managed)
    workload_credential(Settings(_env_file=None))
    cli.assert_called_once()
    with pytest.raises(Denied, match="explicitly"):
        workload_credential(Settings(_env_file=None, environment="dev"))
    workload_credential(
        Settings(_env_file=None, environment="dev", managed_identity_client_id="identity")
    )
    managed.assert_called_once_with(client_id="identity")


@pytest.mark.parametrize("status", ["completed", "failed", "incomplete", "cancelled"])
def test_foundry_invocation_binds_only_run_identifiers(
    system: Any, monkeypatch: Any, status: str
) -> None:
    c, _, fake, _, _ = system
    r = detected(c)
    project = MagicMock()
    response_client = MagicMock()
    project.__enter__.return_value = project
    project.agents.create_session.return_value.agent_session_id = "fresh-run-session"
    project.get_openai_client.return_value.__enter__.return_value = response_client
    response_client.responses.create.return_value.output_text = fake.proposal.model_dump_json()
    response_client.responses.create.return_value.status = status
    monkeypatch.setattr("azure.ai.projects.AIProjectClient", MagicMock(return_value=project))
    if status == "completed":
        result = asyncio.run(FoundryAgent(c.settings, MagicMock()).propose(r.run))
        assert result == fake.proposal
    else:
        with pytest.raises(Denied, match="did not complete"):
            asyncio.run(FoundryAgent(c.settings, MagicMock()).propose(r.run))
    kwargs = response_client.responses.create.call_args.kwargs
    assert "annual_value" not in kwargs["input"]
    project.get_openai_client.assert_called_once_with(agent_name="innexq-agent", max_retries=0)
    session_args = project.agents.create_session.call_args.kwargs
    assert session_args["agent_name"] == "innexq-agent"
    assert session_args["version_indicator"].agent_version == c.settings.foundry_agent_version
    assert kwargs["extra_body"] == {"agent_session_id": "fresh-run-session"}
    assert "conversation" not in kwargs and "previous_response_id" not in kwargs


@pytest.fixture
def cosmos(monkeypatch: Any) -> tuple[CosmosStore, Any]:
    client, container = MagicMock(), MagicMock()
    client.get_database_client.return_value.get_container_client.return_value = container
    monkeypatch.setattr("innexq_api.store.CosmosClient", MagicMock(return_value=client))
    return CosmosStore("https://cosmos.documents.azure.com", MagicMock(), "db", "runs"), container


def test_cosmos_atomic_snapshot_event_and_etag(system: Any, cosmos: Any) -> None:
    c, memory, _, _, _ = system
    r = detected(c)
    store, container = cosmos
    event = memory.events(r.run.run_id)[0]
    store.commit(r, event, 0)
    operations = container.execute_item_batch.call_args.args[0]
    assert len(operations) == 2
    assert all(op[0] == "create" for op in operations)
    doc = {"record": r.model_dump(mode="json"), "_etag": "old"}
    container.read_item.return_value = doc
    assert store.get(r.run.run_id) == r
    updated = r.model_copy(update={"revision": 2})
    store.commit(updated, event.model_copy(update={"sequence": 2}), 1)
    operations = container.execute_item_batch.call_args.args[0]
    assert operations[0][2] == {"if_match_etag": "old"}
    with pytest.raises(Conflict):
        store.commit(r, event, 3)
    container.read_item.return_value = {"record": {"revision": 99}}
    with pytest.raises(Conflict):
        store.commit(updated, event.model_copy(update={"sequence": 2}), 1)


@pytest.mark.parametrize("status", [409, 412, 424, 500])
def test_cosmos_batch_failures(system: Any, cosmos: Any, status: int) -> None:
    c, memory, _, _, _ = system
    r = detected(c)
    store, container = cosmos
    container.execute_item_batch.side_effect = CosmosHttpResponseError(status_code=status)
    with pytest.raises(Conflict if status != 500 else CosmosHttpResponseError):
        store.commit(r, memory.events(r.run.run_id)[0], 0)


def test_cosmos_brief_history_commits_atomically_with_pointer(system: Any, cosmos: Any) -> None:
    from tests.unit.test_controller import assembled

    c, memory, _, _, _ = system
    record = assembled(c)
    store, container = cosmos
    container.read_item.return_value = {
        "record": {"revision": record.revision - 1},
        "_etag": "previous",
    }
    store.commit(record, memory.events(record.run.run_id)[-1], record.revision - 1)
    operations = container.execute_item_batch.call_args.args[0]
    assert len(operations) == 3
    assert operations[0][0] == "replace"
    assert operations[2][0] == "create"
    version = operations[2][1][0]
    assert version["id"] == "brief-00000001"
    assert version["envelope"]["brief_hash"] == record.run.current_brief_hash
    assert len(version["evidence"]) == 6


def test_cosmos_reads_reference_and_actor_query(system: Any, cosmos: Any) -> None:
    c, memory, _, _, _ = system
    r = detected(c)
    store, container = cosmos
    container.read_item.side_effect = CosmosResourceNotFoundError(status_code=404)
    with pytest.raises(KeyError):
        store.get(uuid4())
    assert store.get_teams_reference() is None
    container.read_item.side_effect = None
    container.read_item.return_value = {"reference": {"id": "ref"}}
    assert store.get_teams_reference() == {"id": "ref"}
    store.save_teams_reference({"id": "ref"})
    assert container.upsert_item.call_args.args[0]["run_id"] == "configuration"
    container.query_items.return_value = [{"record": r.model_dump(mode="json")}]
    assert store.list_runs(c.settings.approver_user_id) == [r]
    assert container.query_items.call_args.kwargs["parameters"][0]["value"] == (
        c.settings.approver_user_id
    )
    container.query_items.return_value = [{"event": memory.events(r.run.run_id)[0].model_dump()}]
    assert len(store.events(r.run.run_id)) == 1
    store.ping()
    container.read.assert_called_once()


def coverage_storage(handler: Any) -> Any:
    from innexq_api.adapters import CoverageBlobStorage

    settings = Settings(
        _env_file=None,
        renewal_blob_endpoint="https://stinnexq123.blob.core.windows.net",
        renewal_issued_container="issued-coverage",
    )
    credential = MagicMock()
    credential.get_token.return_value.token = "offline-placeholder"  # noqa: S105
    return CoverageBlobStorage(settings, credential, transport=httpx.MockTransport(handler))


BLOB = "coverage/11111111-1111-4111-8111-111111111111/DEMO-COV-001-COVERAGE-SYN-INV-2026-00001.pdf"


def test_coverage_blob_create_only_write_and_authenticated_read() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "PUT":
            return httpx.Response(201, headers={"etag": "w1"})
        return httpx.Response(200, content=b"%PDF-1.7 issued", headers={"etag": "w1"})

    storage = coverage_storage(handle)
    storage.write(BLOB, b"%PDF-1.7 issued")
    assert storage.read(BLOB) == b"%PDF-1.7 issued"
    put = seen[0]
    assert put.method == "PUT"
    assert put.headers["If-None-Match"] == "*"
    assert put.headers["x-ms-blob-type"] == "BlockBlob"
    assert put.headers["Authorization"] == "Bearer offline-placeholder"
    assert put.url.host == "stinnexq123.blob.core.windows.net"


def test_coverage_blob_conflict_is_idempotent_and_failures_denied() -> None:
    codes = iter([409, 500])

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(codes))

    storage = coverage_storage(handle)
    storage.write(BLOB, b"pdf")  # 409 create-only conflict is treated as idempotent success
    with pytest.raises(Denied):
        storage.write(BLOB, b"pdf")  # 500 is a hard failure


@pytest.mark.parametrize(
    "blob_name",
    [
        "coverage/not-a-uuid/doc.pdf",
        "coverage/11111111-1111-4111-8111-111111111111/../escape.pdf",
        "certificate/11111111-1111-4111-8111-111111111111/doc.pdf",
        "coverage/11111111-1111-4111-8111-111111111111/doc.exe",
    ],
)
def test_coverage_blob_rejects_unallowlisted_names(blob_name: str) -> None:
    storage = coverage_storage(lambda request: httpx.Response(201, headers={"etag": "w"}))
    with pytest.raises(Denied):
        storage.write(blob_name, b"pdf")
    with pytest.raises(Denied):
        storage.read(blob_name)


def test_coverage_blob_rejects_untrusted_endpoint() -> None:
    from innexq_api.adapters import CoverageBlobStorage

    with pytest.raises(Denied):
        CoverageBlobStorage(
            Settings(
                _env_file=None,
                renewal_blob_endpoint="https://evil.example.com",
                renewal_issued_container="issued-coverage",
            ),
            MagicMock(),
        )
