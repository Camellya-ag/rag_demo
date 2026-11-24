param(
  [int]$Port = 8010,
  [switch]$Reload
)
$python = "D:\document\rag\rag_examples\.venv\Scripts\python.exe"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
Set-Location $root
$argsList = @('-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', "$Port")
if ($Reload) { $argsList += '--reload' }
& $python @argsList
