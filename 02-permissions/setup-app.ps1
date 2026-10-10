<#
.SYNOPSIS
  Creates (or reuses) the Universal Data Lake app registration, grants its permissions and stores its secret in Key Vault.

.DESCRIPTION
  Does steps 2.1-2.4 with hand-reviewable az CLI calls. Every call is printed before it runs. The client secret goes straight from Entra into Key Vault and is never written to the console or a file.

  Needs: Azure CLI 2.60+, signed in (az login --tenant <tenant>) as someone who can create app registrations and
  grant admin consent (Cloud Application Administrator + Privileged Role Administrator, or Global Administrator),
  and who can set secrets in the Key Vault. With -AzureSubscriptionIds, also Owner, User Access Administrator or
  Role Based Access Control Administrator on each subscription.

.EXAMPLE
  ./setup-app.ps1 -KeyVaultName kv-universal-lake -Modules copilotInteractions,orgData,m365Activity
  ./setup-app.ps1 -KeyVaultName kv-universal-lake -Modules copilotInteractions,orgData,consumption -AzureSubscriptionIds <sub-guid>
  ./setup-app.ps1 -KeyVaultName kv-universal-lake -WhatIf      # print the plan only
#>
[CmdletBinding(SupportsShouldProcess)]
param(
  [Parameter(Mandatory)] [string] $KeyVaultName,
  [string]   $AppName = 'Universal Data Lake',
  [string]   $SecretName = 'universal-lake-client-secret',
  [string[]] $Modules = @('copilotInteractions', 'orgData', 'm365Activity'),
  [int]      $SecretYears = 1,
  [string[]] $AzureSubscriptionIds = @(),
  [switch]   $SkipConsent,
  [switch]   $RotateSecret
)
$ErrorActionPreference = 'Stop'
$GRAPH = '00000003-0000-0000-c000-000000000000'

# Same map as scripts/build/catalog.js (module -> Graph application permissions).
$PERMS = @{
  copilotInteractions = @('AuditLogsQuery.Read.All', 'Reports.Read.All')
  orgData         = @('User.Read.All')
  m365Activity    = @('Reports.Read.All')
  agent365        = @('CopilotPackages.Read.All', 'Application.Read.All', 'User.Read.All')
  productFeedback = @()
  consumption     = @()
  agentEvaluator  = @()
}
$Modules = @('copilotInteractions') + ($Modules | ForEach-Object { if ($_ -eq 'core') { 'copilotInteractions' } else { $_ } }) | Select-Object -Unique
foreach ($m in $Modules) { if (-not $PERMS.ContainsKey($m)) { throw "Unknown module '$m'. Known: $($PERMS.Keys -join ', ')" } }
$needed = $Modules | ForEach-Object { $PERMS[$_] } | Select-Object -Unique

function Az([string[]] $AzArgs, [switch] $Quiet) {
  $shown = ($AzArgs | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }) -join ' '
  if (-not $Quiet) { Write-Host "  > az $shown" -ForegroundColor DarkGray }
  $out = & az @AzArgs
  if ($LASTEXITCODE -ne 0) { throw "az $($AzArgs[0..1] -join ' ') failed (exit $LASTEXITCODE)" }
  return $out
}

Write-Host "`n== 1. Signed-in account" -ForegroundColor Cyan
$acct = Az @('account', 'show', '-o', 'json') | ConvertFrom-Json
Write-Host "  tenant $($acct.tenantId)  user $($acct.user.name)"

Write-Host "`n== 2. App registration '$AppName'" -ForegroundColor Cyan
$app = Az @('ad', 'app', 'list', '--display-name', $AppName, '-o', 'json') | ConvertFrom-Json | Select-Object -First 1
if ($app) {
  Write-Host "  reusing appId $($app.appId)"
} elseif ($PSCmdlet.ShouldProcess($AppName, 'create app registration')) {
  $app = Az @('ad', 'app', 'create', '--display-name', $AppName, '--sign-in-audience', 'AzureADMyOrg', '-o', 'json') | ConvertFrom-Json
  Write-Host "  created appId $($app.appId)"
}
$appId = $app.appId
$sp = Az @('ad', 'sp', 'list', '--filter', "appId eq '$appId'", '-o', 'json') | ConvertFrom-Json | Select-Object -First 1
if (-not $sp -and $PSCmdlet.ShouldProcess($appId, 'create service principal')) {
  $sp = Az @('ad', 'sp', 'create', '--id', $appId, '-o', 'json') | ConvertFrom-Json
}
Write-Host "  service principal $($sp.id)"

Write-Host "`n== 3. Graph application permissions: $($needed -join ', ')" -ForegroundColor Cyan
$graphRoles = (Az @('ad', 'sp', 'show', '--id', $GRAPH, '--query', 'appRoles', '-o', 'json') -Quiet | ConvertFrom-Json)
$have = @((Az @('ad', 'app', 'permission', 'list', '--id', $appId, '-o', 'json') -Quiet | ConvertFrom-Json) |
  Where-Object resourceAppId -eq $GRAPH | ForEach-Object { $_.resourceAccess.id })
foreach ($p in $needed) {
  $role = $graphRoles | Where-Object value -eq $p
  if (-not $role) { Write-Warning "Graph has no application permission '$p' in this tenant (preview API?). Add it in the portal."; continue }
  if ($have -contains $role.id) { Write-Host "  already requested: $p"; continue }
  if ($PSCmdlet.ShouldProcess($p, 'add Graph application permission')) {
    Az @('ad', 'app', 'permission', 'add', '--id', $appId, '--api', $GRAPH, '--api-permissions', "$($role.id)=Role") | Out-Null
    Write-Host "  added $p"
  }
}
if ($SkipConsent) {
  Write-Host "  admin consent skipped: Entra > App registrations > $AppName > API permissions > Grant admin consent" -ForegroundColor Yellow
} elseif ($PSCmdlet.ShouldProcess($appId, 'grant tenant-wide admin consent')) {
  Start-Sleep -Seconds 10   # new permissions take a moment to be visible to the consent call
  Az @('ad', 'app', 'permission', 'admin-consent', '--id', $appId) | Out-Null
  Write-Host '  admin consent granted (new tokens can take a few minutes to carry the roles)'
}

Write-Host "`n== 4. Client secret -> Key Vault '$KeyVaultName' / '$SecretName'" -ForegroundColor Cyan
$existing = Az @('keyvault', 'secret', 'list', '--vault-name', $KeyVaultName, '--query', "[?name=='$SecretName'].id", '-o', 'tsv') -Quiet
if ($existing -and -not $RotateSecret) {
  Write-Host "  secret already in Key Vault; pass -RotateSecret to replace it"
} elseif ($PSCmdlet.ShouldProcess($SecretName, "create $SecretYears-year client secret and store it in Key Vault")) {
  Write-Host "  > az ad app credential reset --id $appId --append --years $SecretYears --display-name universal-lake  (output hidden)" -ForegroundColor DarkGray
  $secret = & az ad app credential reset --id $appId --append --years $SecretYears --display-name 'universal-lake' --query password -o tsv
  if ($LASTEXITCODE -ne 0 -or -not $secret) { throw 'creating the client secret failed' }
  $tmp = New-TemporaryFile
  try {
    [IO.File]::WriteAllText($tmp, $secret)
    Az @('keyvault', 'secret', 'set', '--vault-name', $KeyVaultName, '--name', $SecretName, '--file', $tmp.FullName,
         '--expires', (Get-Date).AddYears($SecretYears).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'), '-o', 'none') | Out-Null
  } finally { Remove-Item $tmp -Force; $secret = $null }
  Write-Host "  stored. Expires in $SecretYears year(s): put a reminder in your calendar."
}

if ($Modules -contains 'consumption' -and $AzureSubscriptionIds) {
  Write-Host "`n== 5. Azure roles for Azure AI spend (consumption)" -ForegroundColor Cyan
  foreach ($sub in $AzureSubscriptionIds) {
    foreach ($r in 'Reader', 'Cost Management Reader', 'Monitoring Reader') {
      if ($PSCmdlet.ShouldProcess("/subscriptions/$sub", "assign $r")) {
        Az @('role', 'assignment', 'create', '--assignee-object-id', $sp.id, '--assignee-principal-type', 'ServicePrincipal',
             '--role', $r, '--scope', "/subscriptions/$sub", '-o', 'none') | Out-Null
        Write-Host "  $r on $sub"
      }
    }
  }
}

$vault = Az @('keyvault', 'show', '--name', $KeyVaultName, '-o', 'json') -Quiet | ConvertFrom-Json
Write-Host "`n== Done. Put these in config.json:" -ForegroundColor Green
Write-Host "  tenantId      $($acct.tenantId)"
Write-Host "  appId         $appId"
Write-Host "  keyVault.uri  $($vault.properties.vaultUri)"
Write-Host "  secretName    $SecretName"
Write-Host "`nStill to do by hand (see README.md):"
Write-Host "  - Everyone who runs the notebooks needs 'Key Vault Secrets User' on $KeyVaultName (or a get/list access policy)."
if ($Modules -contains 'agentEvaluator') { Write-Host "  - Agent Evaluator: add $appId as an application user in each Dataverse environment with the 'Bot Transcript Viewer' role." }
if ($Modules -contains 'm365Activity' -or $Modules -contains 'copilotInteractions') { Write-Host "  - M365 admin center > Settings > Org settings > Reports: turn OFF 'Display concealed user names' or usage reports are anonymised." }
