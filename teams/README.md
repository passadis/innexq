# InnexQ private Teams app

Generate the package after deployment with the Azure Bot's user-assigned managed
identity client ID (not the API app registration ID):

```powershell
uv run python scripts/package_teams.py --bot-client-id <bot-uami-client-id> --api-base-url https://<api-host>
```

The ZIP contains only a manifest and original geometric PNG icons; no credentials.
Custom app upload must be permitted by the tenant's Teams policy. Install in the
approved team and, as the configured `superuser@alfacloud.gr` approver, @mention
InnexQ in the exact InneQ channel with `connect`. This authenticated message stores
the channel conversation reference durably. No inbound Graph delegated token or
permission such as ChannelMessage.Send is substituted for bot authentication.

The official Teams SDK authenticates Bot Connector JWTs at `/api/messages`; the
adapter then checks the activity's tenant, Azure AD user object ID, team's
`aadGroupId`, and exact channel ID. A missing claim fails closed. The callback is
the blueprint's approval callback responsibility, mounted at the Azure Bot's
standard messaging endpoint rather than adding a second public bypass route.

Cards expose the stored brief, complete exact action parameters and approval
version/hash. Oversized cards are rejected rather than truncated. Only
Action.Execute approve/reject callbacks are supported. Approval and execution
remain controller methods, not SDK state. The callback awaits execution; slow
downstream operations can exceed Teams' invoke response window. A client timeout
is not evidence of execution failure: inspect durable Run Events. Callback retries
cannot grant a second approval or resend an action with an unknown outcome.

Phase 1 uses Bot Connector authenticated activity identity, not delegated Work IQ
SSO. It does not implement the later Control Room or Teams app-store distribution.

Sources: [official SDK card actions](https://learn.microsoft.com/en-us/microsoftteams/platform/teams-sdk/in-depth-guides/adaptive-cards/executing-actions),
[app manifest schema](https://learn.microsoft.com/en-us/microsoft-365/extensibility/schema/?view=m365-app-1.23),
[Bot Connector authentication](https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-authentication).
