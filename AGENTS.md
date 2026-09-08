# InnexQ repository instructions

## Authority and scope

- `docs/scenario/INNEXQ-SCENARIO-V0.2.md` is the product and business contract.
- `docs/scenario/INNEXQ-IMPLEMENTATION-BLUEPRINT-V0.1.md` is the technical and delivery contract.
- Contract Renewal is the first Workflow Pack in the InnexQ product; do not model InnexQ as a one-off renewal script.
- Do not add agents, workflows, Azure services or external frameworks outside the frozen scope without an ADR and explicit owner approval.

## Non-negotiable boundaries

- The agent proposes; deterministic code validates; an authorized human approves; an isolated executor performs allowlisted writes.
- The workflow controller alone owns state transitions and executable authorization.
- Never perform financial arithmetic, authority checks or state mutation in model output.
- Any material evidence gap, conflict, staleness or access denial must stop safely.
- Retrieval and mutation identities/capabilities remain separate.
- Never commit secrets. Prefer managed identity, Entra ID, RBAC and least privilege.

## Development

This project was built with the microsoft-foundry skill. Before working on or answering questions about foundry agents, read the microsoft-foundry skill first.

- Python 3.12 is the baseline.
- Domain packages remain framework-independent; FastAPI adapters depend on them, not vice versa.
- Schemas in `src/contracts/schemas/v1` must stay synchronized with Pydantic models.
- Run `uv run python scripts/tasks.py verify` before handing off changes.
- Phase 0 must not run `azd provision`, `azd deploy`, `azd up`, `terraform apply`, or Azure/Microsoft 365 mutations.
