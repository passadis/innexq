# InnexQ

InnexQ is a product-shaped MVP for governed enterprise workflows. Its first Workflow Pack, Contract Renewal, assembles authorized evidence and deterministic business facts into a Proof-Carrying Decision Brief. The agent may propose and explain; deterministic code validates; an authorized human approves a specific immutable version; only then may an isolated executor perform allowlisted actions.

Phase 1 is implemented locally and Azure provisioning has started. It includes
the authenticated workflow API, Cosmos adapter, deterministic pricing/authority,
one read-only Hosted Agent, synthetic Foundry IQ corpus, Teams approval adapter,
guarded Graph executor and tests. **It is not yet a proven live vertical slice.**
The three human-approved Azure/Microsoft 365 Runs remain the Phase 1 exit gate.

## Local setup

Install [uv](https://docs.astral.sh/uv/) and use Python 3.12:

```bash
uv sync --dev
uv run python scripts/export_schemas.py --check
uv run python scripts/tasks.py verify
```

Individual checks:

```bash
uv run python scripts/tasks.py format-check
uv run python scripts/tasks.py lint
uv run python scripts/tasks.py type-check
uv run python scripts/tasks.py test-unit
uv run python scripts/tasks.py security-check
```

The aggregate `verify` command performs all checks without Azure credentials,
including the independently locked Hosted Agent test environment. Test doubles
are injected only by tests; there is no fake/live fallback configuration.
See [deployment plan](.azure/deployment-plan.md) for current validation evidence
and [bootstrap gates](infra/README.md) for Microsoft 365 setup.

## Repository map

- `docs/scenario`: frozen product and delivery contracts.
- `docs/adr`: architecture decision records.
- `src/contracts`: framework-independent domain models, rules and JSON schemas.
- `src/api`: authenticated controller, Teams and guarded Graph adapters.
- `corpus/fixtures`: explicitly synthetic demo/test facts.
- `infra`: Phase 1 Terraform resources and least-privilege permissions.
- `tests/unit`: domain, controller, token, concurrency, adapter and safety tests.
- `src/agent`: separate Python 3.12 project, lock, Docker image and guard tests.

## Phase 1 operation

`/health/live` checks the process. `/health/ready` remains 503 until configuration,
Cosmos access and the authenticated Teams conversation reference are available.
The Container App transport probe is not evidence of end-to-end readiness.

The API requires Entra tokens for its configured audience: delegated
`user_impersonation` plus the configured human identity, or the actual agent
principal with `Pricing.Read` for the pricing route only. No HTTP execution route
is mounted. The Teams SDK authenticates `/api/messages`; the controller separately
checks the approved tenant, team, channel, actor, brief version and hash.

Reset allocates a fresh attempt namespace and preserves existing audit/artifacts.
Unknown external outcomes stop automatic retries. A Graph send acceptance receipt
does not prove recipient delivery. Only synthetic corpus/fixtures are supported;
the dated Fabrikam fixture expires on 2026-09-29 and detection deliberately stops
after that date. Do not change dates or corpus during a three-Run acceptance run.

Once deployment, site/mailbox grants and Teams installation are verified, sign in
as the configured approver and run `uv run python scripts/live_run.py --help` for
the live harness. Use `--runs 3` for acceptance. Each Run requires a real Teams
approval; the harness checks the ordered persisted events and both action
receipts, but does not synthesize approval or claim recipient delivery. Source
corpus data is seeded into the new Blob/Search resources, not the SharePoint
Output folder. SharePoint is the approved execution destination for this slice.

Assembly and approval-request POSTs require an `Idempotency-Key` and the current
revision. Repeating a claimed command returns the current Run without invoking
the agent or sending another card. Use a new key and current revision only for
an intentional recovery. Rebuilt briefs increment their immutable version;
previous envelopes and evidence remain stored with the Run audit history.

Phase 1 uses an extractive, cited summary. Work IQ, 12% exception routing, richer
generated explanations and the accessible web Control Room remain later phases.

See `SECURITY.md` before adding identity, retrieval or action integrations.
