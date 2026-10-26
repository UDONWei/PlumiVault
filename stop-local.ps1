param([string]$Config = (Join-Path $PSScriptRoot 'config.local.json'))
$ErrorActionPreference = 'Stop'
$configPath = (Resolve-Path -LiteralPath $Config).Path
$settings = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$dataPath = if ([System.IO.Path]::IsPathRooted($settings.data_dir)) { $settings.data_dir } else { Join-Path (Split-Path -Parent $configPath) $settings.data_dir }
$markerPath = Join-Path $dataPath 'runtime\server.json'
if (-not (Test-Path -LiteralPath $markerPath)) { Write-Output 'Not running.'; exit 0 }
$marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
$url = "http://127.0.0.1:$($marker.port)"
$state = Invoke-RestMethod -Uri "$url/api/state" -TimeoutSec 5
if ($state.library_id -ne $marker.library_id) { throw 'Library identity mismatch; no process was stopped.' }
Invoke-RestMethod -Uri "$url/api/shutdown" -Method Post -ContentType 'application/json' -Headers @{ 'X-Bird-Token' = $state.token } -Body '{}' -TimeoutSec 5 | Out-Null
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if (-not (Test-Path -LiteralPath $markerPath)) { Write-Output 'Stopped; completed records are saved.'; exit 0 }
    Start-Sleep -Milliseconds 500
}
Write-Output 'Stop requested. Check app-data/runtime/server.stderr.log.'
