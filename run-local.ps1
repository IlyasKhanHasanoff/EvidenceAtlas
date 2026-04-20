$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvDir = Join-Path $root ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$stateDir = Join-Path $root ".run-state"
$pidFile = Join-Path $stateDir "server.pid"
$stdoutLog = Join-Path $stateDir "server.out.log"
$stderrLog = Join-Path $stateDir "server.err.log"
$requirementsFile = Join-Path $root "requirements.txt"
$requirementsStamp = Join-Path $stateDir "requirements.sha256"
$appUrl = "http://127.0.0.1:3000"

function Get-PythonLauncher {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    return @{
      Path = $py.Source
      Arguments = @("-3")
    }
  }

  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    return @{
      Path = $python.Source
      Arguments = @()
    }
  }

  $bundledPython = Join-Path $HOME ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path $bundledPython) {
    return @{
      Path = $bundledPython
      Arguments = @()
    }
  }

  throw "Python was not found. Install Python 3 and run this script again."
}

function Test-AppHealthy {
  try {
    $response = Invoke-WebRequest -UseBasicParsing "$appUrl/api/health" -TimeoutSec 2
    return $response.StatusCode -eq 200
  } catch {
    return $false
  }
}

New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

if (-not (Test-Path $venvPython)) {
  Write-Host "Creating local virtual environment..."
  $launcher = Get-PythonLauncher
  & $launcher.Path @($launcher.Arguments + @("-m", "venv", $venvDir))
}

$currentHash = (Get-FileHash $requirementsFile -Algorithm SHA256).Hash
$savedHash = if (Test-Path $requirementsStamp) { (Get-Content $requirementsStamp -Raw).Trim() } else { "" }

if ($currentHash -ne $savedHash) {
  Write-Host "Installing or refreshing Python dependencies..."
  & $venvPython -m pip install -r $requirementsFile
  Set-Content -Path $requirementsStamp -Value $currentHash -NoNewline
}

if (-not (Test-AppHealthy)) {
  Write-Host "Starting Evidence Atlas..."
  $process = Start-Process `
    -FilePath $venvPython `
    -ArgumentList "server.py" `
    -WorkingDirectory $root `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

  Set-Content -Path $pidFile -Value $process.Id -NoNewline

  $started = $false
  for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-AppHealthy) {
      $started = $true
      break
    }
  }

  if (-not $started) {
    throw "The server did not become ready. Check .run-state/server.err.log for details."
  }
} else {
  Write-Host "Evidence Atlas is already running."
}

Start-Process $appUrl
Write-Host "Evidence Atlas is ready at $appUrl"
