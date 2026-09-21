"""Opt-in real-model smoke; synthetic packets only, no workflow or external writes."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureDeveloperCliCredential

AGENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_ROOT))

from certificate_team import CustomerInterpretation, TeamProposal, certificate_team  # noqa: E402

CASES = [
    (["Provice Certificate for PT-002"], None, {("certificate_request", "DEMO-PT-002")}),
    (["Is the service for PT-001 updated?"], None, {("service_status", "DEMO-PT-001")}),
    (["Is the certificate for PT-001 valid?"], None, {("certificate_status", "DEMO-PT-001")}),
    (["Do not send the certificate for PT-001"], None, {("general", None), ("clarify", None)}),
    (["Send a certificate"], None, {("clarify", None)}),
    (["Send certificate for PT-002"], "DEMO-PT-001", {("clarify", None)}),
    (["Send certificate for PT-999"], None, {("clarify", None)}),
    (["Book service for PT-001"], None, {("service_request", "DEMO-PT-001")}),
    (["What is a certificate?"], None, {("general", None)}),
    (
        ["Send certificate for PT-001", "Cancel that request"],
        None,
        {("general", None), ("clarify", None)},
    ),
    (["Send certificates for PT-001 and PT-002"], None, {("clarify", None)}),
    (["Send certificate for PT-001 and book a service"], None, {("clarify", None)}),
]


async def smoke() -> None:
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] = "false"
    os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "false"
    failures = 0
    with AzureDeveloperCliCredential() as credential:
        client = FoundryChatClient(
            project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
            model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
            credential=credential,
        )
        agent = certificate_team(client)
        for number, (messages, selected, expected) in enumerate(CASES, start=1):
            request_id = str(uuid4())
            packet = {
                "mode": "customer_message",
                "request_id": request_id,
                "tenant_id": "35de4c50-7dcd-4871-8685-61789c017da2",
                "customer_id": "DEMO-FAB",
                "equipment_ids": ["DEMO-PT-001", "DEMO-PT-002", "DEMO-PT-003"],
                "selected_equipment_id": selected,
                "messages": messages,
            }
            response = await asyncio.wait_for(agent.run(json.dumps(packet)), timeout=90)
            result = CustomerInterpretation.model_validate_json(response.text)
            passed = (result.intent, result.equipment_id) in expected
            passed = passed and str(result.request_id) == request_id
            failures += not passed
            print(
                json.dumps(
                    {
                        "case": number,
                        "passed": passed,
                        "intent": result.intent,
                        "equipment_id": result.equipment_id,
                    }
                ),
                flush=True,
            )
        packet = json.loads((AGENT_ROOT / "tests/certificate-smoke-request.json").read_text())
        for intent in ("certificate_request", "service_status", "certificate_status"):
            packet["request_id"] = str(uuid4())
            if intent != "certificate_request":
                packet["intent"] = intent
            response = await asyncio.wait_for(agent.run(json.dumps(packet)), timeout=180)
            result = TeamProposal.model_validate_json(response.text)
            passed = result.intent == intent and len(result.specialists) == 2
            failures += not passed
            print(
                json.dumps(
                    {
                        "investigation": intent,
                        "passed": passed,
                        "specialists": len(result.specialists),
                    }
                ),
                flush=True,
            )
    print(json.dumps({"failed": failures, "live_customer_acceptance": False}), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-model", action="store_true", required=True)
    parser.parse_args()
    asyncio.run(smoke())
