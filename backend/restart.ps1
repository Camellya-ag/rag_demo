param(
  [int]$Port = 8010,
  [string]$BindHost = "127.0.0.1",
  [int]$WaitSeconds = 12
)

$ErrorActionPreference = "Stop"
$python = "D:\document\rag\rag_examples\.venv\Scripts\python.exe"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$healthUrl = "http://${BindHost}:$Port/api/health"

if (-not (Test-Path $python)) {
  throw "未找到虚拟环境 Python: $python"
}

function Get-UvicornListeners {
  param([int]$ListenPort)
  $pids = @(Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique)
  foreach ($procId in $pids) {
    if (-not $procId) { continue }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    if (-not $proc) { continue }
    $cmd = [string]$proc.CommandLine
    if ($cmd -match 'uvicorn' -and $cmd -match 'backend\.app\.main:app') {
      [PSCustomObject]@{ ProcessId = $procId; CommandLine = $cmd }
    }
  }
}

$listeners = @(Get-UvicornListeners -ListenPort $Port)
foreach ($item in $listeners) {
  Write-Host "停止旧后端 PID $($item.ProcessId)"
  Stop-Process -Id $item.ProcessId -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 1

$still = @(Get-UvicornListeners -ListenPort $Port)
if ($still.Count -gt 0) {
  throw "端口 $Port 仍被占用，请手动结束: $($still.ProcessId -join ', ')"
}

Write-Host "启动 uvicorn ${BindHost}:$Port ..."
Start-Process `
  -FilePath $python `
  -ArgumentList @('-m', 'uvicorn', 'backend.app.main:app', '--host', $BindHost, '--port', "$Port") `
  -WorkingDirectory $repoRoot `
  -WindowStyle Hidden

$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Milliseconds 500
  try {
    $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 3
    if ($resp.StatusCode -eq 200) {
      Write-Host "健康检查通过: $healthUrl"
      $resp.Content
      exit 0
    }
  } catch {
  }
}

throw "后端在 ${WaitSeconds}s 内未就绪: $healthUrl"
