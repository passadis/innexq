"""Run the real Phase 1 API path; human Teams approval is never synthesized."""

import argparse
import json
import time
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from azure.identity import AzureCliCredential
from innexq_contracts.events import RunEvent, RunRecord
from innexq_contracts.hashing import approval_matches_current_version
from innexq_contracts.models import RunState


def verify_run(record: RunRecord, events: list[RunEvent]) -> None:
    """Verify persisted execution proof, without claiming mailbox delivery."""
    if record.run.state != RunState.EXECUTED or record.envelope is None or record.approval is None:
        raise ValueError("executed Run with a stored approved package required")
    if not approval_matches_current_version(record.approval, record.envelope):
        raise ValueError("approval is not bound to the executed package")
    keys = {a.idempotency_key for a in record.envelope.action_manifest.actions}
    if (
        len(keys) != 2
        or set(record.receipts) != keys
        or record.action_status != dict.fromkeys(keys, "completed")
    ):
        raise ValueError("exactly two completed action receipts required")
    if [e.sequence for e in events] != list(range(1, record.revision + 1)) or any(
        e.run_id != record.run.run_id or e.correlation_id != record.run.correlation_id
        for e in events
    ):
        raise ValueError("audit sequence or correlation mismatch")
    names = [e.event_type for e in events]
    expected = [
        "run.detected",
        "agent.started",
        "tool.pricing_completed",
        "evidence.validated",
        "policy.verified",
        "brief.versioned",
        "approval.requested",
        "approval.recorded",
        "execution.started",
        "action.started",
        "action.completed",
        "action.started",
        "action.completed",
        "execution.completed",
    ]
    # Card delivery bookkeeping and denied duplicate callbacks may interleave safely.
    relevant = [name for name in names if name in set(expected)]
    if relevant != expected or any(
        name in names for name in ("evidence.hold", "approval.delivery_failed", "execution.failed")
    ):
        raise ValueError("Run did not complete the expected uninterrupted approved sequence")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--audience", required=True, help="InnexQ API application client ID")
    parser.add_argument("--tenant", default="35de4c50-7dcd-4871-8685-61789c017da2")
    parser.add_argument("--runs", type=int, choices=(1, 3), default=1)
    parser.add_argument("--approval-timeout", type=int, default=900)
    args = parser.parse_args()
    endpoint = args.endpoint.rstrip("/")
    url = urlsplit(endpoint)
    if (
        url.scheme != "https"
        or not url.hostname
        or not url.hostname.endswith(".azurecontainerapps.io")
        or url.path
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        parser.error("endpoint must be the approved Container Apps HTTPS origin")
    credential = AzureCliCredential(tenant_id=args.tenant)
    try:
        with httpx.Client(base_url=endpoint, timeout=240, follow_redirects=False) as client:

            def call(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
                token = credential.get_token(f"api://{args.audience}/.default").token
                response = client.request(
                    method,
                    path,
                    headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())},
                    **kwargs,
                )
                response.raise_for_status()
                return cast(dict[str, Any], response.json())

            for number in range(1, args.runs + 1):
                reset = call("POST", "/api/demo/reset")
                token = credential.get_token(f"api://{args.audience}/.default").token
                response = client.post(
                    "/api/runs/detect",
                    json={},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Idempotency-Key": reset["attempt_key"],
                    },
                )
                response.raise_for_status()
                record = response.json()
                run_id = record["run"]["run_id"]
                record = call(
                    "POST", f"/api/runs/{run_id}/assemble", json={"revision": record["revision"]}
                )
                record = call(
                    "POST",
                    f"/api/runs/{run_id}/request-approval",
                    json={"revision": record["revision"]},
                )
                print(
                    f"Run {number}/{args.runs}: {run_id}. Review and approve in Teams.", flush=True
                )
                deadline = time.monotonic() + args.approval_timeout
                while record["run"]["state"] != "EXECUTED":
                    if record["run"]["state"] in (
                        "EVIDENCE_HOLD",
                        "EXECUTION_FAILED",
                        "CLOSED_REJECTED",
                    ):
                        raise RuntimeError(f"Run stopped safely: {record['run']['state']}")
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Run {run_id}: awaiting human approval/completion")
                    time.sleep(5)
                    record = call("GET", f"/api/runs/{run_id}")
                token = credential.get_token(f"api://{args.audience}/.default").token
                response = client.get(
                    f"/api/runs/{run_id}/events", headers={"Authorization": f"Bearer {token}"}
                )
                response.raise_for_status()
                events = [RunEvent.model_validate(event) for event in response.json()]
                verify_run(RunRecord.model_validate(record), events)
                print(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "state": "EXECUTED",
                            "brief_hash": record["run"]["current_brief_hash"],
                            "receipts": record["receipts"],
                            "ordered_events_verified": len(events),
                            "delivery": "recipient confirmation still required",
                        }
                    ),
                    flush=True,
                )
    finally:
        credential.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
