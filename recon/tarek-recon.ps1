#requires -Version 7
# tarek-recon.ps1 - READ-ONLY audit of a WORK/SCHOOL (Entra) Microsoft account.
# Nothing is written. Device-code sign-in: you log in yourself; no password reaches anyone else.
# Reveals licenses, roles, groups, tenant info, devices, and whether M365 Copilot is assigned.
#
# Usage:
#   pwsh -File .\tarek-recon.ps1                 # full Entra audit (1 sign-in)
#   pwsh -File .\tarek-recon.ps1 -IncludeAdo     # also list Azure DevOps orgs (2nd sign-in)
#   pwsh -File .\tarek-recon.ps1 -IncludeAzure   # also list Azure subscriptions (needs az cli)
[CmdletBinding()]
param(
  [string]$OutDir = (Join-Path $HOME 'tarek-recon'),
  [switch]$IncludeAdo,
  [switch]$IncludeAzure
)

$ErrorActionPreference = 'Stop'
$ClientId  = '14d82eec-204b-4c2f-b7e8-296a70dab67e'   # Microsoft Graph PowerShell (public client)
$Authority = 'https://login.microsoftonline.com/organizations'   # work/school only
$Scopes    = 'openid profile offline_access User.Read User.ReadBasic.All Organization.Read.All Directory.Read.All Group.Read.All Mail.Read Files.Read Calendars.Read MailboxSettings.Read'

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Invoke-DeviceCode {
  param([string]$Scope, [string]$Prompt, [string]$Auth = $Authority)
  $dc = Invoke-RestMethod -Method Post -Uri "$Auth/oauth2/v2.0/devicecode" -Body @{ client_id = $ClientId; scope = $Scope }
  Write-Host ''
  Write-Host "=== $Prompt ===" -ForegroundColor Cyan
  Write-Host $dc.message -ForegroundColor Yellow
  Write-Host ''
  $deadline = (Get-Date).AddSeconds([int]$dc.expires_in)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds ([int]$dc.interval)
    try {
      return Invoke-RestMethod -Method Post -Uri "$Auth/oauth2/v2.0/token" -Body @{
        grant_type  = 'urn:ietf:params:oauth:grant-type:device_code'
        client_id   = $ClientId
        device_code = $dc.device_code
      }
    } catch {
      $e = $null
      try { $e = ($_.ErrorDetails.Message | ConvertFrom-Json).error } catch { }
      if ($e -eq 'authorization_pending') { continue }
      if ($e -eq 'slow_down') { Start-Sleep -Seconds 5; continue }
      throw
    }
  }
  throw 'Timed out waiting for sign-in.'
}

function Decode-Jwt {
  param([string]$Jwt)
  if (-not $Jwt) { return $null }
  $p = $Jwt.Split('.')[1].Replace('-','+').Replace('_','/')
  $pad = $p.Length % 4
  if ($pad -eq 2) { $p += '==' } elseif ($pad -eq 3) { $p += '=' }
  [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($p)) | ConvertFrom-Json
}

# ---- 1) Sign in ----
$token = Invoke-DeviceCode -Scope $Scopes -Prompt "SIGN IN AS TAREK'S WORK/SCHOOL ACCOUNT"
$hdr   = @{ Authorization = "Bearer $($token.access_token)" }
$idc   = Decode-Jwt $token.id_token

function Get-Graph {
  param([string]$Path)
  try { Invoke-RestMethod -Headers $hdr -Uri "https://graph.microsoft.com/v1.0/$Path" }
  catch { [pscustomobject]@{ error = $_.Exception.Message } }
}

$report = [ordered]@{}
$report.capturedAtUtc = (Get-Date).ToUniversalTime().ToString('o')

# ---- 2) Identity + tenant claims ----
$report.identity = [ordered]@{
  name          = $idc.name
  upn           = $idc.preferred_username
  oid           = $idc.oid
  tenantId      = $idc.tid
  issuer        = $idc.iss
  grantedScopes = $token.scope
  accountType   = 'Entra work/school (organizational)'
}

# ---- 3) Profile ----
$report.profile = Get-Graph 'me?$select=displayName,givenName,surname,userPrincipalName,id,mail,jobTitle,department,companyName,officeLocation,mobilePhone,country,usageLocation,accountEnabled,createdDateTime,userType,onPremisesSyncEnabled'

# ---- 4) Tenant / organization ----
$org = Get-Graph 'organization?$select=id,displayName,verifiedDomains,assignedPlans,createdDateTime,countryLetterCode,tenantType'
$report.organization = $org.value

# ---- 5) LICENSES (the Copilot blocker check) ----
$lic = Get-Graph 'me/licenseDetails?$select=skuId,skuPartNumber,servicePlans'
$report.licenses = @($lic.value | ForEach-Object {
  [ordered]@{
    skuPartNumber = $_.skuPartNumber
    skuId         = $_.skuId
    servicePlans  = @($_.servicePlans | Select-Object servicePlanName, provisioningStatus)
  }
})
$planNames = @($lic.value.servicePlans.servicePlanName)
$report.copilotSignals = [ordered]@{
  hasM365CopilotChat = [bool]($planNames -match 'COPILOT_BUSINESS_CHAT|M365_COPILOT')
  matchedPlans       = @($planNames | Where-Object { $_ -match 'COPILOT' } | Select-Object -Unique)
  allServicePlans    = @($planNames | Sort-Object -Unique)
}

# ---- 6) Directory roles (admin?) ----
$roles = Get-Graph 'me/memberOf/microsoft.graph.directoryRole?$select=displayName,roleTemplateId'
$report.directoryRoles = @($roles.value | Select-Object displayName, roleTemplateId)

# ---- 7) Group memberships ----
$grp = Get-Graph 'me/memberOf/microsoft.graph.group?$select=displayName,mailEnabled,securityEnabled,groupTypes&$top=100'
$report.groups = @($grp.value | Select-Object displayName, mailEnabled, securityEnabled, groupTypes)

# ---- 8) Registered / owned devices ----
$dev = Get-Graph 'me/registeredDevices?$select=displayName,operatingSystem,operatingSystemVersion,trustType,isCompliant,isManaged'
$report.registeredDevices = @($dev.value | Select-Object displayName, operatingSystem, operatingSystemVersion, trustType, isCompliant, isManaged)

# ---- 9) Mailbox snapshot ----
$report.mailFolders = (Get-Graph 'me/mailFolders?$select=displayName,totalItemCount,unreadItemCount&$top=25').value
$report.oneDrive    = Get-Graph 'me/drive?$select=driveType,quota,owner,webUrl'

# ---- 10) Optional: Azure DevOps orgs ----
if ($IncludeAdo) {
  try {
    $adoTok = Invoke-DeviceCode -Scope '499b84ac-1321-427f-aa17-267ca6975798/.default offline_access' -Prompt 'SIGN IN AGAIN TO LIST AZURE DEVOPS ORGS'
    $ah = @{ Authorization = "Bearer $($adoTok.access_token)" }
    $me = Invoke-RestMethod -Headers $ah -Uri 'https://app.vssps.visualstudio.com/_apis/profile/profiles/me?api-version=6.0'
    $orgs = Invoke-RestMethod -Headers $ah -Uri "https://app.vssps.visualstudio.com/_apis/accounts?memberId=$($me.id)&api-version=6.0"
    $report.azureDevOps = [ordered]@{
      profileId = $me.id; emailAddress = $me.emailAddress; orgCount = $orgs.count
      orgs = @($orgs.value | Select-Object accountName, accountUri, accountId)
    }
  } catch { $report.azureDevOps = @{ error = $_.Exception.Message } }
}

# ---- 11) Optional: Azure subscriptions ----
if ($IncludeAzure) {
  try {
    az login --use-device-code --only-show-errors | Out-Null
    $report.azureSubscriptions = az account list --all --output json | ConvertFrom-Json |
      Select-Object name, id, state, tenantId, isDefault
  } catch { $report.azureSubscriptions = @{ error = $_.Exception.Message } }
}

# ---- 12) Save + print ----
$json = $report | ConvertTo-Json -Depth 12
$file = Join-Path $OutDir 'tarek-recon-report.json'
$json | Out-File -FilePath $file -Encoding utf8
Write-Host ''
Write-Host "=== REPORT SAVED: $file ===" -ForegroundColor Green
Write-Host '--- Copy everything below and paste it back to me ---' -ForegroundColor Green
Write-Host ''
Write-Host $json
