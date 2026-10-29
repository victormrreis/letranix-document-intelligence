$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Follow README setup first: create .venv and install dependencies.' }
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'dist\index.html'))) { throw 'Run npm ci and npm run build first.' }
& $python -m letranix demo
if ($LASTEXITCODE -ne 0) { throw 'Demo initialization failed.' }
Write-Host 'Open http://127.0.0.1:8795 after the service starts. Press Ctrl+C to stop.'
& $python -m letranix serve
