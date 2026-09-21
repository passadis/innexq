"""Opt-in local model/Search probe; pricing transport is a LOCAL fixture only.

This is not live acceptance or proof of hosted identity/API authorization. The
production Dockerfile excludes scripts. No live Runs or Microsoft 365 writes
are created. Run from src/agent with --fixture-pricing and explicit Azure env.
"""

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import httpx
from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.core.credentials import AccessToken
from azure.identity import AzureDeveloperCliCredential

AGENT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AGENT_ROOT.parents[1]
sys.path.insert(0, str(AGENT_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src" / "gateway"))
sys.path.insert(0, str(REPO_ROOT / "src" / "contracts"))

from innexq_gateway import calculate_pricing  # noqa: E402

import main as runtime  # noqa: E402
from contracts import Proposal, RunRequest  # noqa: E402


class LocalPricingCredential:
    """Never request a developer token for the agent-only production API."""

    def __init__(self, actual, api_scope):
        self.actual = actual
        self.api_scope = api_scope

    def get_token(self, *scopes, **kwargs):
        print(json.dumps({"local_guard_token_scopes": scopes}), flush=True)
        if scopes == (self.api_scope,):
            return AccessToken("local-fixture-not-an-access-token", int(time.time()) + 300)
        return self.actual.get_token(*scopes, **kwargs)


class LocalDiagnosticGuard(runtime.ProposalGuard):
    """Observe only configuration metadata while retaining the complete real guard."""

    async def process(self, context, call_next):
        async def observed_next():
            print(
                json.dumps(
                    {
                        "guard_tool_names": [tool.__name__ for tool in context.tools],
                        "stream": context.stream,
                        "option_keys": sorted(context.options),
                        "parallel_tool_calls": context.options.get("allow_multiple_tool_calls"),
                    }
                ),
                flush=True,
            )
            await call_next()

        await super().process(context, observed_next)


async def smoke(serve=False, stream=False):
    # azd injects deployment telemetry configuration locally. This fixture probe
    # must not export to production telemetry or use its managed-identity config.
    os.environ.pop("APPLICATIONINSIGHTS_CONNECTION_STRING", None)
    os.environ.pop("APPLICATIONINSIGHTS_AUTHENTICATION_STRING", None)
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] = "false"
    os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "false"
    request = RunRequest(run_id=uuid4(), correlation_id=uuid4(), contract_id="CON-FAB-2025-001")
    if serve:
        request = RunRequest.model_validate_json(
            (AGENT_ROOT / "tests/local-smoke-request.json").read_text("utf-8")
        )
    contract = json.loads(
        (REPO_ROOT / "corpus/fixtures/fabrikam-contract.json").read_text(encoding="utf-8")
    )
    policy = json.loads(
        (REPO_ROOT / "corpus/fixtures/phase1-policy.json").read_text(encoding="utf-8")
    )
    if contract["synthetic"] is not True or policy["synthetic"] is not True:
        raise ValueError("Only synthetic fixture pricing is permitted")
    api_endpoint = runtime.endpoint("INNEXQ_API_ENDPOINT", ".azurecontainerapps.io")
    api_scope = runtime.required("INNEXQ_API_AUDIENCE").removesuffix("/.default") + "/.default"
    stats = {"pricing_fixture_calls": 0, "real_retrieval_calls": 0}
    real_retrieve = runtime.retrieve

    async def observed_retrieve(*args, **kwargs):
        print(json.dumps({"synthetic_evidence_query": args[-1]}), flush=True)
        result = await real_retrieve(*args, **kwargs)
        stats["real_retrieval_calls"] += 1
        print(json.dumps({"retrieved_source_ids": sorted(x.source_id for x in result)}), flush=True)
        return result

    def fixture_pricing(http_request):
        if (
            http_request.method != "POST"
            or str(http_request.url) != f"{api_endpoint}/api/tools/pricing"
            or json.loads(http_request.content) != request.model_dump(mode="json")
        ):
            raise ValueError("Unexpected local fixture transport request")
        stats["pricing_fixture_calls"] += 1
        if stats["pricing_fixture_calls"] != 1:
            raise ValueError("Local pricing must be called exactly once")
        result = calculate_pricing(
            contract["annual_value"]["amount"],
            policy["discount_percent"],
            currency=contract["annual_value"]["currency"],
        )
        print(json.dumps({"local_pricing_tool": result.as_dict()}), flush=True)
        return httpx.Response(200, json=result.as_dict())

    def pricing_client(**kwargs):
        return httpx.AsyncClient(
            **kwargs, mounts={api_endpoint: httpx.MockTransport(fixture_pricing)}
        )

    print(
        "LOCAL FIXTURE MODE: real model/Search; local deterministic pricing; no live Run.",
        flush=True,
    )
    # azd retains the developer identity while az may be the human approver.
    # Production continues to use DefaultAzureCredential; this is test-only.
    with AzureDeveloperCliCredential() as credential:
        token_payload = credential.get_token("https://ai.azure.com/.default").token.split(".")[1]
        claims = json.loads(
            base64.urlsafe_b64decode(token_payload + "=" * (-len(token_payload) % 4))
        )
        print(
            json.dumps(
                {
                    "local_model_identity": {key: claims.get(key) for key in ("oid", "tid", "aud")},
                    "azure_config_dir": os.environ.get("AZURE_CONFIG_DIR", "CLI default"),
                }
            ),
            flush=True,
        )
        guard = LocalDiagnosticGuard(LocalPricingCredential(credential, api_scope))
        client = FoundryChatClient(
            project_endpoint=runtime.required("FOUNDRY_PROJECT_ENDPOINT"),
            model=runtime.required("AZURE_AI_MODEL_DEPLOYMENT_NAME"),
            credential=credential,
        )
        agent = Agent(
            client=client,
            name="innexq-agent",
            instructions=runtime.INSTRUCTIONS,
            middleware=[guard],
            default_options={
                "store": False,
                "response_format": Proposal,
                "max_output_tokens": 16000,
            },
        )
        # Replace only main's module reference; Search and model retain real httpx.
        with patch.object(runtime, "httpx", SimpleNamespace(AsyncClient=pricing_client)):
            with patch.object(runtime, "retrieve", observed_retrieve):
                if serve:
                    await ResponsesHostServer(agent).run_async(host="127.0.0.1")
                    return
                if stream:
                    updates = agent.run(request.model_dump_json(), stream=True)
                    async for _ in updates:
                        pass
                    response = await updates.get_final_response()
                else:
                    response = await agent.run(request.model_dump_json())
        proposal = Proposal.model_validate_json(response.text)
        print(
            json.dumps(
                {
                    "status": "local_fixture_smoke_passed",
                    "source_ids": sorted(c.source_id for c in proposal.citations),
                    "summary_is_exact_cited_excerpt": proposal.summary
                    in {c.excerpt for c in proposal.citations},
                    **stats,
                    "hosted_identity_verified": False,
                    "live_acceptance_runs": 0,
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-pricing",
        action="store_true",
        required=True,
        help="Explicitly acknowledge pricing uses a local fixture, not live API",
    )
    parser.add_argument("--serve", action="store_true", help="Serve one fixture Run on loopback")
    parser.add_argument("--stream", action="store_true", help="Probe direct streaming runtime")
    args = parser.parse_args()
    asyncio.run(smoke(serve=args.serve, stream=args.stream))
