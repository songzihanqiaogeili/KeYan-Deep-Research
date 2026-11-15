param([int]$Port = 8765, [switch]$OpenBrowser, [switch]$Background)
$ErrorActionPreference = 'Stop'
$researchRoot = Split-Path -Parent $PSScriptRoot
$researchBackend = Join-Path $researchRoot 'backend'
$researchPython = Join-Path $researchBackend '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $researchPython)) {
    throw 'Missing backend/.venv. Create a Python 3.10+ environment and install backend/requirements-scientific.txt first.'
}
$env:PYTHONPATH = Join-Path $researchBackend 'app'
$env:PYTHONIOENCODING = 'utf-8'
function Get-ResearchHealth([string]$Url) {
    $request = [System.Net.WebRequest]::Create($Url)
    $request.Proxy = $null
    $request.Timeout = 2000
    $response = $request.GetResponse()
    try {
        $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
        try { return ($reader.ReadToEnd() | ConvertFrom-Json) }
        finally { $reader.Dispose() }
    } finally { $response.Dispose() }
}
$researchArgs = @('-B', '-m', 'scientific_research.serve', '--port', "$Port")
if ($OpenBrowser) { $researchArgs += '--open' }

    $serviceUrl = "http://127.0.0.1:$Port"
    try {
        $health = Get-ResearchHealth "$serviceUrl/healthz"
        if ($health.service -eq 'scientific-research-workbench') {
            if ($OpenBrowser) { & $researchPython -B -m scientific_research.serve --port $Port --open-existing }
            Write-Host "Research workbench is already running: $serviceUrl"
            exit 0
        }
    } catch {}
if ($Background) {
    $researchLogDir = Join-Path $researchRoot 'logs'
    New-Item -ItemType Directory -Path $researchLogDir -Force | Out-Null
    $researchProcess = Start-Process -FilePath $researchPython -ArgumentList $researchArgs -WorkingDirectory $researchBackend -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $researchLogDir 'scientific.out.log') -RedirectStandardError (Join-Path $researchLogDir 'scientific.err.log')
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $health = Get-ResearchHealth "$serviceUrl/healthz"
            if ($health.service -eq 'scientific-research-workbench') {
                Write-Host "Research workbench started in background: $serviceUrl"
                Write-Host "Logs: $researchLogDir"
                exit 0
            }
        } catch {}
        if ($researchProcess.HasExited) { break }
    }
    throw "Research service did not start. Check $researchLogDir/scientific.err.log"
}
& $researchPython @researchArgs
exit $LASTEXITCODE
