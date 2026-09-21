#Requires -Modules Microsoft.Graph.Authentication
<#
.SYNOPSIS
Resolves only the approved InnexQ targets; optionally applies its site-selected grant.
.DESCRIPTION
Connect-MgGraph must already be connected to the approved tenant. This script never
requests consent, creates an app, uploads files, or creates folders. The default is
read-only. -GrantSite requires an administrative delegated Sites.FullControl.All
session and ShouldProcess confirmation. Do not grant that scope to the API identity.
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)][guid]$ExecutorClientId,
    [switch]$GrantSite
)
$ErrorActionPreference = 'Stop'
$expectedTenant = '35de4c50-7dcd-4871-8685-61789c017da2'
$siteUrl = 'https://passadisoutlook498.sharepoint.com/sites/InnexQ'
$context = Get-MgContext
if (-not $context -or $context.TenantId -ne $expectedTenant) {
    throw 'Connect Microsoft Graph to the approved tenant first; no changes made.'
}
if ($GrantSite -and ($context.AuthType -ne 'Delegated' -or
    $context.Scopes -notcontains 'Sites.FullControl.All')) {
    throw 'Site bootstrap needs an explicitly consented administrative delegated Sites.FullControl.All session.'
}
function Get-GraphCollection([string]$Uri) {
    $items = @()
    while ($Uri) {
        if (-not $Uri.StartsWith('https://graph.microsoft.com/v1.0/', [StringComparison]::Ordinal)) {
            throw 'Unexpected Graph pagination host or API version.'
        }
        $page = Invoke-MgGraphRequest -Method GET -Uri $Uri
        $items += @($page.value)
        $Uri = $page.'@odata.nextLink'
    }
    return $items
}
$site = Invoke-MgGraphRequest -Method GET -Uri 'https://graph.microsoft.com/v1.0/sites/passadisoutlook498.sharepoint.com:/sites/InnexQ?$select=id,webUrl'
if ($site.webUrl.TrimEnd('/') -ne $siteUrl) { throw 'Resolved site does not match the approved URL.' }
$siteId = [Uri]::EscapeDataString($site.id)
$drives = @(Get-GraphCollection "https://graph.microsoft.com/v1.0/sites/$siteId/drives" |
    Where-Object { $_.name -ceq 'InnexQDocs' -and $_.driveType -eq 'documentLibrary' })
if ($drives.Count -ne 1) { throw 'Expected exactly one InnexQDocs document library; nothing was created.' }
$driveId = [Uri]::EscapeDataString($drives[0].id)
$folder = Invoke-MgGraphRequest -Method GET -Uri "https://graph.microsoft.com/v1.0/drives/$driveId/root:/Output"
if (-not $folder.Contains('folder') -or $folder.name -cne 'Output' -or
    $folder.parentReference.driveId -ne $drives[0].id) {
    throw 'Output must be an existing folder in the approved library.'
}
$permissionId = $null
if ($GrantSite) {
    $permissions = @(Get-GraphCollection "https://graph.microsoft.com/v1.0/sites/$siteId/permissions")
    $existing = @($permissions | Where-Object {
        $identities = @($_.grantedToIdentitiesV2) + @($_.grantedToIdentities)
        @($identities | Where-Object { $_.application.id -eq $ExecutorClientId.ToString() }).Count -gt 0
    })
    if ($existing.Count -gt 1) { throw 'Multiple grants found; review manually without automatic modification.' }
    if ($existing.Count -eq 1) {
        if (@($existing[0].roles).Count -ne 1 -or $existing[0].roles[0] -ne 'write') {
            throw 'Existing site grant differs from the approved read/write role; review manually.'
        }
        $permissionId = $existing[0].id
    } elseif ($PSCmdlet.ShouldProcess("$siteUrl -> $ExecutorClientId", 'Grant Sites.Selected write access on this site only')) {
        $body = @{
            roles = @('write')
            grantedToIdentities = @(@{ application = @{
                id = $ExecutorClientId.ToString(); displayName = 'InnexQ guarded executor'
            } })
        } | ConvertTo-Json -Depth 6
        $permission = Invoke-MgGraphRequest -Method POST -Uri "https://graph.microsoft.com/v1.0/sites/$siteId/permissions" -Body $body -ContentType 'application/json'
        $permissionId = $permission.id
    }
}
# Non-secret identifiers only. No token, source document or mailbox content is printed.
[ordered]@{
    tenant_id = $expectedTenant
    graph_site_id = $site.id
    graph_drive_id = $drives[0].id
    graph_folder_id = $folder.id
    executor_client_id = $ExecutorClientId.ToString()
    site_permission_id = $permissionId
    grant_requested = [bool]$GrantSite
} | ConvertTo-Json
