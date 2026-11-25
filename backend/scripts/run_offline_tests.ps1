param(
  [string]$Python = "D:\document\rag\rag_examples\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$env:PYTHONPATH = $RepoRoot
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONUNBUFFERED = "1"

Write-Host "[offline-tests] offline guard enabled via backend.tests.__init__"
& $Python -m unittest discover -s (Join-Path $RepoRoot "backend\tests") -t $RepoRoot -p "test_*.py" -v
exit $LASTEXITCODE
