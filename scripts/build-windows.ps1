$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pyinstaller = Join-Path $repoRoot '.venv\Scripts\pyinstaller.exe'
$appName = 'PairForge'
$templateName = 'PairForge' + ([string][char]0x9898) + [char]0x5E93 + [char]0x6A21 + [char]0x677F + '.docx'

Push-Location $repoRoot
try {
    pnpm --dir frontend build
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend build failed with exit code $LASTEXITCODE"
    }
    & $pyinstaller `
        --noconfirm `
        --clean `
        --onefile `
        --noconsole `
        --name $appName `
        --distpath release `
        --paths backend `
        --collect-all keyring `
        --hidden-import win32ctypes.pywin32 `
        --add-data 'frontend/dist;frontend/dist' `
        launcher/main.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
    Copy-Item -LiteralPath 'README.md' -Destination (Join-Path 'release' 'README.md') -Force
    Copy-Item -LiteralPath (Join-Path 'templates' $templateName) -Destination (Join-Path 'release' $templateName) -Force
    Write-Host "Build complete: $(Join-Path $repoRoot (Join-Path 'release' ($appName + '.exe')))"
} finally {
    Pop-Location
}
