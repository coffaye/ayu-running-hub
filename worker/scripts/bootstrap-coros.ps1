param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^https://')]
  [string]$WorkerUrl,

  [Parameter(Mandatory = $true)]
  [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
  [string]$TokenCachePath,

  [ValidateSet('https://mcp.coros.com', 'https://mcpcn.coros.com', 'https://mcpeu.coros.com', 'https://mcpus.coros.com')]
  [string]$Issuer = 'https://mcpcn.coros.com',

  [switch]$Reauthorize
)

$ErrorActionPreference = 'Stop'
$bootstrapSecret = $env:COROS_BOOTSTRAP_SECRET
$secureSecret = $null
$secretPointer = $null

try {
  if ([string]::IsNullOrWhiteSpace($bootstrapSecret)) {
    $secureSecret = Read-Host 'Enter COROS_BOOTSTRAP_SECRET' -AsSecureString
    $secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSecret)
    $bootstrapSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer)
  }
  if ([string]::IsNullOrWhiteSpace($bootstrapSecret)) { throw 'COROS_BOOTSTRAP_SECRET is required' }

  # This reads the dedicated automation cache only. Token values never become
  # parameters, URLs, output, or files created by this script.
  $token = Get-Content -Raw -LiteralPath $TokenCachePath | ConvertFrom-Json
  foreach ($property in @('access_token', 'refresh_token', 'client_id', 'expires_at_epoch', 'scope')) {
    if ($null -eq $token.$property -or [string]::IsNullOrWhiteSpace([string]$token.$property)) {
      throw "token cache is missing $property"
    }
  }

  $body = [ordered]@{
    issuer = $Issuer.TrimEnd('/')
    mcpUrl = "$($Issuer.TrimEnd('/'))/mcp"
    clientId = [string]$token.client_id
    accessToken = [string]$token.access_token
    refreshToken = [string]$token.refresh_token
    accessExpiresAt = [int64]$token.expires_at_epoch
    scope = [string]$token.scope
  }
  if ($Reauthorize) { $body.reauthorize = $true }

  $response = Invoke-RestMethod -Method Post -Uri "$($WorkerUrl.TrimEnd('/'))/internal/coros/bootstrap" -Headers @{
    'x-coros-bootstrap-secret' = $bootstrapSecret
  } -ContentType 'application/json' -Body ($body | ConvertTo-Json -Compress)

  # Allowlist metadata only. Never print the response body wholesale.
  [pscustomobject]@{
    ok = $true
    credentialGeneration = $response.credentialGeneration
    authState = $response.authState
    accessExpiresAt = $response.accessExpiresAt
  } | ConvertTo-Json -Compress
}
finally {
  if ($secretPointer) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer) }
  Remove-Variable -Name token,body,response,bootstrapSecret,secureSecret -ErrorAction SilentlyContinue
}
