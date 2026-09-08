# Controller-owned state machine

The transition guard is deny-by-default. The hosted agent cannot call it as a mutation authority.

```text
DETECTED -> CONTEXT_ASSEMBLING -> CONTEXT_ASSEMBLED -> POLICY_VERIFIED
POLICY_VERIFIED -> AWAITING_APPROVAL -> APPROVED -> EXECUTING -> EXECUTED
AWAITING_APPROVAL -> ESCALATED -> AWAITING_APPROVAL
AWAITING_APPROVAL | ESCALATED -> CLOSED_REJECTED
EXECUTING -> EXECUTION_FAILED -> EXECUTING
EVIDENCE_HOLD -> CONTEXT_ASSEMBLING
```

Every state before `APPROVED` may move to `EVIDENCE_HOLD`. Resolution re-enters `CONTEXT_ASSEMBLING` so evidence is re-retrieved and all deterministic checks are repeated. Escalation re-enters `AWAITING_APPROVAL` only after ownership/required authority is updated; it does not authorize execution by itself.

Self-transitions and all unlisted transitions are rejected. Persistence and append-only Run Events arrive in Phase 1.
