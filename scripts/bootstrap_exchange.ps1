#Requires -Modules ExchangeOnlineManagement
<#
.SYNOPSIS
Audits or creates one mailbox-scoped Exchange Application Mail.Send assignment.
.DESCRIPTION
Connect-ExchangeOnline must already be connected to the approved tenant. No login,
consent, mailbox edits, message sending, or global Graph roles occur here. Default
is read-only; -Apply uses ShouldProcess. Existing objects are never overwritten.
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)][guid]$ExecutorClientId,
    [Parameter(Mandatory)][guid]$ExecutorPrincipalId,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$expectedTenant = '35de4c50-7dcd-4871-8685-61789c017da2'
$sender = 'superuser@alfacloud.gr'
$scopeName = 'InnexQ-Phase1-Sender'
$assignmentName = 'InnexQ-Phase1-MailSend'
$connections = @(Get-ConnectionInformation | Where-Object {
    $_.State -eq 'Connected' -and $_.TenantID -eq $expectedTenant
})
if ($connections.Count -ne 1) { throw 'Connect one Exchange session to the approved tenant first.' }
$mailbox = Get-Mailbox -Identity $sender
if ($mailbox.PrimarySmtpAddress.ToString() -ne $sender) { throw 'Sender mailbox mismatch.' }
# Use the immutable directory ID, not a mutable custom attribute or a broad group.
$recipientFilter = "ExternalDirectoryObjectId -eq '$($mailbox.ExternalDirectoryObjectId)'"
$matching = @(Get-Recipient -Filter $recipientFilter -ResultSize Unlimited)
if ($matching.Count -ne 1 -or $matching[0].PrimarySmtpAddress.ToString() -ne $sender) {
    throw 'The proposed management scope must match exactly the approved sender.'
}
$principals = @(Get-ServicePrincipal | Where-Object {
    $_.AppId -eq $ExecutorClientId.ToString() -or $_.ObjectId -eq $ExecutorPrincipalId.ToString()
})
if ($principals.Count -gt 1 -or ($principals.Count -eq 1 -and
    ($principals[0].AppId -ne $ExecutorClientId.ToString() -or
     $principals[0].ObjectId -ne $ExecutorPrincipalId.ToString()))) {
    throw 'Exchange service-principal identifiers conflict; review manually.'
}
$scope = @(Get-ManagementScope | Where-Object { $_.Name -eq $scopeName })
if ($scope.Count -gt 1) { throw 'Management scope is ambiguous.' }
if ($scope.Count -eq 1) {
    $scopedRecipients = @(Get-Recipient -Filter $scope[0].RecipientFilter -ResultSize Unlimited)
    if ($scopedRecipients.Count -ne 1 -or
        $scopedRecipients[0].ExternalDirectoryObjectId -ne $mailbox.ExternalDirectoryObjectId) {
        throw 'Existing named scope is not restricted to the approved sender.'
    }
}
$assignments = @(Get-ManagementRoleAssignment | Where-Object { $_.Name -eq $assignmentName })
if ($assignments.Count -gt 1) { throw 'Role assignment is ambiguous.' }
if ($assignments.Count -eq 1 -and ($assignments[0].Role.ToString() -ne 'Application Mail.Send' -or
    $assignments[0].CustomResourceScope.ToString() -ne $scopeName -or
    $assignments[0].RoleAssignee.ToString() -ne $ExecutorPrincipalId.ToString())) {
    throw 'Existing named assignment differs; inspect manually and do not overwrite.'
}
$configurationApplied = $false
if ($Apply -and $PSCmdlet.ShouldProcess("$ExecutorPrincipalId -> $sender", 'Create missing mailbox-scoped InnexQ mail authorization')) {
    if ($principals.Count -eq 0) {
        New-ServicePrincipal -AppId $ExecutorClientId -ObjectId $ExecutorPrincipalId -DisplayName 'InnexQ guarded executor' | Out-Null
    }
    if ($scope.Count -eq 0) {
        New-ManagementScope -Name $scopeName -RecipientRestrictionFilter $recipientFilter | Out-Null
    }
    if ($assignments.Count -eq 0) {
        New-ManagementRoleAssignment -Name $assignmentName -App $ExecutorPrincipalId -Role 'Application Mail.Send' -CustomResourceScope $scopeName | Out-Null
    }
    $configurationApplied = $true
}
if ($principals.Count -eq 1 -or $configurationApplied) {
    Test-ServicePrincipalAuthorization -Identity $ExecutorPrincipalId -Resource $sender |
        Select-Object RoleName, GrantedPermissions, AllowedResourceScope, ScopeType, InScope
} else {
    Write-Output 'Not configured. Re-run with -Apply only after reviewing the approved principal and scope.'
}
Write-Output 'Also audit Entra app-role assignments: Exchange scope tests do not include separate Graph permissions.'
