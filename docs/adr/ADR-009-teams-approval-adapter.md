# ADR-009: Microsoft Teams SDK approval adapter

Status: Accepted in the owner-approved Phase 1 plan on 2026-09-07.

Use the Microsoft Teams SDK for Python, Azure Bot F0 and the API's new user-assigned
managed identity. The SDK is an ingress/egress adapter, never an authority engine.
An Adaptive Card Action.Execute carries Run ID, version and approval hash. Only
the workflow controller may authorize the verified tenant/user, match the stored
hash, record approval and transition state. Card data never supplies a trusted
role or new executable parameters. Duplicate callbacks cannot duplicate writes.

The owner installs the packaged custom app in the confirmed Team. Conversation
references are accepted only from authenticated Bot traffic for that tenant and
channel. Missing installation/reference is a readiness failure, not permission to
use anonymous webhooks or post through broad Graph channel permissions. Bot
placement is West Europe as explicitly approved; the API remains Sweden Central.

The official SDK is pinned in the dependency lock. No Bot client secret is
created. These capabilities must pass live token/card tests before release;
choosing the supported SDK does not itself prove callback authentication works.

Reference: [Microsoft Teams SDK](https://learn.microsoft.com/en-us/microsoftteams/platform/teams-ai-library/welcome).
