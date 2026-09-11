$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $project '.runtime'

foreach ($item in @(
    @{ File = 'preview-app.pid'; Name = 'python' },
    @{ File = 'preview-tunnel.pid'; Name = 'ssh' }
)) {
    $pidFile = Join-Path $runtime $item.File
    if (-not (Test-Path -LiteralPath $pidFile)) { continue }
    $savedPid = 0
    if ([int]::TryParse((Get-Content -LiteralPath $pidFile -Raw).Trim(), [ref]$savedPid)) {
        $process = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
        if ($process -and $process.ProcessName -eq $item.Name) {
            Stop-Process -Id $savedPid -Force
        }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath (Join-Path $runtime 'preview-url.txt') -Force -ErrorAction SilentlyContinue
Write-Host 'Prévia gratuita encerrada.'
