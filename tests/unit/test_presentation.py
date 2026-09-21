"""Presentation never changes approved bytes, authority or destination access."""

import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from innexq_api.config import Settings
from innexq_api.controller import Denied, digest
from innexq_api.presentation import decision_url, renewal_email
from innexq_api.teams import approval_card, status_card
from innexq_contracts.hashing import compute_brief_hash
from innexq_contracts.models import ActionType
from innexq_gateway import calculate_pricing

from tests.unit.factories import RUN_ID
from tests.unit.test_adapters import action, graph  # noqa: F401
from tests.unit.test_controller import awaiting

ORIGIN = "https://web.example.test"
OUTPUT = "https://passadisoutlook498.sharepoint.com/sites/InnexQ/InnexQDocs/Output"


def test_compact_card_has_bound_link_no_raw_html_or_evidence_dump(system):
    c, _, _, _, _ = system
    current = awaiting(c)
    payload = approval_card(current, ORIGIN).model_dump(by_alias=True, exclude_none=True)
    text = json.dumps(payload)
    assert len(text.encode()) < 6000
    assert "<!doctype html>" not in text and "corpus_hash" not in text
    link = next(a for a in payload["actions"] if a["type"] == "Action.OpenUrl")
    params = parse_qs(urlsplit(link["url"]).query)
    assert params == {
        "run": [str(current.run.run_id)],
        "version": ["1"],
        "hash": [current.envelope.brief_hash],
    }
    for a in payload["actions"]:
        if a["type"] == "Action.Execute":
            assert a["data"]["brief_hash"] == current.envelope.brief_hash
    assert current.envelope.brief_hash in text
    assert c.settings.test_recipient in text
    result = status_card(current, ORIGIN).model_dump(by_alias=True, exclude_none=True)
    assert {a["type"] for a in result["actions"]} == {"Action.OpenUrl"}


def test_html_email_is_escaped_branded_and_uses_only_protected_document_link():
    facts = {
        "contract_id": "CON-1",
        "customer_name": '<img src="https://evil.test">',
        "service_level": "Gold & Plus",
        "term_months": "12",
    }
    content = renewal_email(
        facts, calculate_pricing("100000.00", "8"), RUN_ID, 1, "innexq-test.txt", OUTPUT
    )
    assert "&lt;img src=&quot;" in content and "<img" not in content
    assert "Gold &amp; Plus" in content
    assert "EUR 92000.00" in content and "SYNTHETIC DEMO" in content
    assert f'href="{OUTPUT}/innexq-test.txt"' in content
    assert "Open renewal document" in content
    assert "<script" not in content and "tracking" not in content
    with pytest.raises(ValueError):
        Settings(graph_output_folder_url="https://evil.test")


def test_controller_hash_binds_email_content_and_format(system):
    c, _, _, _, _ = system
    current = awaiting(c)
    envelope = current.envelope
    mail = envelope.action_manifest.actions[1]
    assert mail.parameters["content_type"] == "HTML"
    assert digest(mail.parameters["content"]) == mail.artifact_hash
    changed = mail.model_copy(update={"parameters": {**mail.parameters, "content_type": "Text"}})
    manifest = envelope.action_manifest.model_copy(
        update={"actions": [envelope.action_manifest.actions[0], changed]}
    )
    assert compute_brief_hash(envelope.brief, manifest) != envelope.brief_hash


@pytest.mark.parametrize("content_type", ["Text", "HTML"])
def test_graph_sends_the_exact_stored_content_type(graph, content_type):  # noqa: F811
    executor, requests = graph
    asyncio.run(executor.execute(action(ActionType.GRAPH_SEND_MAIL, content_type=content_type)))
    assert json.loads(requests[0].content)["message"]["body"] == {
        "contentType": content_type,
        "content": "approved text",
    }


def test_unsupported_email_format_has_no_external_write(graph):  # noqa: F811
    executor, requests = graph
    with pytest.raises(Denied):
        asyncio.run(executor.execute(action(ActionType.GRAPH_SEND_MAIL, content_type="MIME")))
    assert not requests


@pytest.mark.parametrize(
    "origin", ["http://web.test", "https://web.test/path", "https://web.test?x=y"]
)
def test_decision_link_rejects_unsafe_origin(origin):
    with pytest.raises(ValueError):
        decision_url(origin, RUN_ID, 1, "a" * 64)
