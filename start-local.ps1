param([int]$Port = 8765, [string]$Config = (Join-Path $PSScriptRoot 'config.local.json'))
$ErrorActionPreference = 'Stop'
$configPath = (Resolve-Path -LiteralPath $Config).Path
$settings = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$dataPath = if ([System.IO.Path]::IsPathRooted($settings.data_dir)) { $settings.data_dir } else { Join-Path (Split-Path -Parent $configPath) $settings.data_dir }
$runtimePath = Join-Path $dataPath 'runtime'
$markerPath = Join-Path $runtimePath 'server.json'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
if (Test-Path -LiteralPath $markerPath) {
    $marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
    try { $existing = Invoke-RestMethod -Uri "http://127.0.0.1:$($marker.port)/api/state" -TimeoutSec 2 } catch { $existing = $null }
    if ($existing -and $existing.library_id -eq $marker.library_id) { Write-Output "Running: http://127.0.0.1:$($marker.port)"; exit 0 }
}
$arguments = '-X utf8 -B -m bird_index serve --config "{0}" --port {1}' -f $configPath, $Port
$process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimePath 'server.stdout.log') -RedirectStandardError (Join-Path $runtimePath 'server.stderr.log') -PassThru
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 500
    if ($process.HasExited) { throw "Startup failed: $runtimePath\server.stderr.log" }
    if (Test-Path -LiteralPath $markerPath) {
        $marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
        try { $ready = Invoke-RestMethod -Uri "http://127.0.0.1:$($marker.port)/api/state" -TimeoutSec 2 } catch { $ready = $null }
        if ($ready -and $ready.library_id -eq $marker.library_id) { Write-Output "Started: http://127.0.0.1:$($marker.port)"; exit 0 }
    }
}
Write-Output "Starting; see $runtimePath\server.stderr.log"
