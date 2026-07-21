$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'

Start-Process -FilePath $python -ArgumentList '-m','uvicorn','app.main:app','--app-dir','backend','--host','127.0.0.1','--port','8765','--reload' -WorkingDirectory $repoRoot -WindowStyle Hidden
Push-Location (Join-Path $repoRoot 'frontend')
try {
    pnpm dev
} finally {
    Pop-Location
}

