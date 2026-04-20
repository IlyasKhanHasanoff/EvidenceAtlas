$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $root ".run-state\server.pid"

if (-not (Test-Path $pidFile)) {
  Write-Host "No saved server PID was found."
  exit 0
}

$pid = (Get-Content $pidFile -Raw).Trim()

if (-not $pid) {
  Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
  Write-Host "PID file was empty."
  exit 0
}

$process = Get-Process -Id $pid -ErrorAction SilentlyContinue

if ($process) {
  Stop-Process -Id $pid
  Write-Host "Stopped Evidence Atlas server process $pid."
} else {
  Write-Host "No running server process was found for PID $pid."
}

Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
