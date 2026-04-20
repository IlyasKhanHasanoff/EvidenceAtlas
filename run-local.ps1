$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvDir = Join-Path $root ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$stateDir = Join-Path $root ".run-state"
$pidFile = Join-Path $stateDir "server.pid"
$requirementsFile = Join-Path $root "requirements.txt"
$requirementsStamp = Join-Path $stateDir "requirements.sha256"
$tempDir = Join-Path $stateDir "tmp"
$appUrl = "http://127.0.0.1:3000"

function Get-PythonCandidates {
  $candidates = @()

  $bundledPython = Join-Path $HOME ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path $bundledPython) {
    $candidates += @{
      Label = "bundled runtime"
      Path = $bundledPython
      Arguments = @()
      ManagesDependencies = $false
    }
  }

  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    $candidates += @{
      Label = "py launcher"
      Path = $py.Source
      Arguments = @("-3")
      ManagesDependencies = $false
    }
  }

  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    $candidates += @{
      Label = "python on PATH"
      Path = $python.Source
      Arguments = @()
      ManagesDependencies = $false
    }
  }

  return $candidates
}

function Test-PythonImport {
  param(
    [hashtable]$Candidate,
    [string]$ModuleName
  )

  try {
    & $Candidate.Path @($Candidate.Arguments + @("-c", "import $ModuleName")) 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  }
}

function Get-ManagedVenvCandidate {
  if (-not (Test-Path $venvPython)) {
    Write-Host "Creating local virtual environment..."
    $seed = Get-PythonCandidates | Select-Object -First 1
    if (-not $seed) {
      throw "Python was not found. Install Python 3 and run this script again."
    }
    & $seed.Path @($seed.Arguments + @("-m", "venv", $venvDir))
  }

  $candidate = @{
    Label = "local virtual environment"
    Path = $venvPython
    Arguments = @()
    ManagesDependencies = $true
  }

  $pipReady = $true
  try {
    & $candidate.Path -m pip --version 2>$null | Out-Null
  } catch {
    $pipReady = $false
  }

  if (-not $pipReady -or $LASTEXITCODE -ne 0) {
    Write-Host "Bootstrapping pip inside the local virtual environment..."
    & $candidate.Path -m ensurepip --upgrade
  }

  $currentHash = (Get-FileHash $requirementsFile -Algorithm SHA256).Hash
  $savedHash = if (Test-Path $requirementsStamp) { (Get-Content $requirementsStamp -Raw).Trim() } else { "" }
  $dependenciesReady = Test-PythonImport -Candidate $candidate -ModuleName "pypdf"

  if ($currentHash -ne $savedHash -or -not $dependenciesReady) {
    Write-Host "Installing or refreshing Python dependencies..."
    & $candidate.Path -m pip install -r $requirementsFile
    Set-Content -Path $requirementsStamp -Value $currentHash -NoNewline
  }

  return $candidate
}

function Get-PythonRuntime {
  foreach ($candidate in Get-PythonCandidates) {
    if (Test-PythonImport -Candidate $candidate -ModuleName "pypdf") {
      return $candidate
    }
  }

  return Get-ManagedVenvCandidate
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
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

$env:TMP = $tempDir
$env:TEMP = $tempDir

$pythonRuntime = Get-PythonRuntime
Write-Host "Using $($pythonRuntime.Label)."

if (-not (Test-AppHealthy)) {
  Write-Host "Starting Evidence Atlas..."
  $pythonArgs = @($pythonRuntime.Arguments + @("server.py")) | ForEach-Object { "'$_'" }
  $backgroundCommand = @(
    "Set-Location -LiteralPath '$root'"
    "`$env:TMP = '$tempDir'"
    "`$env:TEMP = '$tempDir'"
    "& '$($pythonRuntime.Path)' $($pythonArgs -join ' ')"
  ) -join "; "
  $encodedCommand = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($backgroundCommand))
  $process = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-WindowStyle", "Hidden", "-EncodedCommand", $encodedCommand) `
    -WindowStyle Hidden `
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
    throw "The server did not become ready. Stop it with stop-local.ps1 and try run-local again."
  }
} else {
  Write-Host "Evidence Atlas is already running."
}

Start-Process $appUrl
Write-Host "Evidence Atlas app is ready at $appUrl"
