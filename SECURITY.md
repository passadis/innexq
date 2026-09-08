# Security policy

InnexQ treats approval and external mutation as security boundaries, not prompt instructions.

## Reporting

Do not open a public issue containing credentials, tenant data, retrieved content, customer communications or exploitable authorization details. Report suspected vulnerabilities privately to the repository owner.

## Repository rules

- Commit no secrets, tokens, certificates, connection strings or tenant-specific values.
- Use Entra ID, managed identities and RBAC. Key Vault is reserved for unavoidable secrets, never as a substitute for keyless authentication.
- Grant retrieval identities read-only access. The hosted agent must never receive Graph mail-send or SharePoint-write permissions.
- Verify actor identity and scenario role server-side; never trust browser-supplied roles.
- Bind approval to the canonical Decision Brief plus Action Manifest hash. Edits invalidate prior approval.
- Check state, hash, deterministic authority, allowlist and idempotency before every action.
- Redact prompts, evidence excerpts and email bodies from default telemetry.

Phase 0 contains synthetic fixtures only and makes no network or Azure calls.
