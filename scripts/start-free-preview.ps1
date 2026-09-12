param(
    [int]$Port = 8000,
    [string]$Python = '',
    [string]$BasicUser = 'cliente',
    [string]$BasicPassword = ''
)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $project '.runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

function Stop-RecordedProcess([string]$PidFile, [string]$ExpectedName) {
    if (-not (Test-Path -LiteralPath $PidFile)) { return }
    $savedPid = 0
    if ([int]::TryParse((Get-Content -LiteralPath $PidFile -Raw).Trim(), [ref]$savedPid)) {
        $process = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
        if ($process -and $process.ProcessName -eq $ExpectedName) {
            Stop-Process -Id $savedPid -Force
        }
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

$appPidFile = Join-Path $runtime 'preview-app.pid'
$tunnelPidFile = Join-Path $runtime 'preview-tunnel.pid'
Stop-RecordedProcess $appPidFile 'python'
Stop-RecordedProcess $tunnelPidFile 'ssh'

if (-not $Python) {
    $venvPython = Join-Path $project '.venv\Scripts\python.exe'
    $Python = if (Test-Path -LiteralPath $venvPython) {
        $venvPython
    } else {
        (Get-Command python.exe -ErrorAction Stop).Source
    }
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python não encontrado: $Python"
}

$ssh = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
if (-not (Test-Path -LiteralPath $ssh)) {
    throw 'O cliente OpenSSH do Windows não foi encontrado.'
}

$tunnelOut = Join-Path $runtime 'preview-tunnel-output.log'
$tunnelErr = Join-Path $runtime 'preview-tunnel-error.log'
Remove-Item -LiteralPath $tunnelOut,$tunnelErr -Force -ErrorAction SilentlyContinue
$tunnelArgs = @(
    '-T',
    '-o', 'StrictHostKeyChecking=accept-new',
    '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ServerAliveInterval=60',
    '-R', "80:127.0.0.1:$Port",
    'nokey@localhost.run'
)
$tunnel = Start-Process -FilePath $ssh -ArgumentList $tunnelArgs -WindowStyle Hidden `
    -RedirectStandardOutput $tunnelOut -RedirectStandardError $tunnelErr -PassThru
Set-Content -LiteralPath $tunnelPidFile -Value $tunnel.Id

$deadline = [DateTime]::UtcNow.AddSeconds(45)
$publicUrl = $null
while ([DateTime]::UtcNow -lt $deadline -and -not $publicUrl) {
    if ($tunnel.HasExited) {
        $detail = if (Test-Path -LiteralPath $tunnelErr) { Get-Content -LiteralPath $tunnelErr -Raw } else { '' }
        throw "O túnel encerrou antes de publicar a URL. $detail"
    }
    $text = @($tunnelOut,$tunnelErr | Where-Object { Test-Path -LiteralPath $_ } |
        ForEach-Object { Get-Content -LiteralPath $_ -Raw }) -join "`n"
    $match = [regex]::Match($text, 'https://[a-z0-9.-]+\.lhr\.life')
    if ($match.Success) { $publicUrl = $match.Value; break }
    Start-Sleep -Milliseconds 500
}
if (-not $publicUrl) {
    Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
    throw 'O localhost.run não entregou uma URL em 45 segundos.'
}

$hostName = ([uri]$publicUrl).DnsSafeHost
if (-not $BasicPassword) {
    $randomBytes = New-Object byte[] 18
    [Security.Cryptography.RandomNumberGenerator]::Fill($randomBytes)
    $BasicPassword = [Convert]::ToBase64String($randomBytes).TrimEnd('=').Replace('+','-').Replace('/','_')
}
$env:CERTIFICA_BROWSER_MODE = 'local-edge'
$env:CERTIFICA_LOCAL_EDGE_PROFILE_DIR = Join-Path $runtime 'local-edge-profile'
$env:CERTIFICA_ALLOWED_HOSTS = $hostName
$env:CERTIFICA_BASIC_USER = $BasicUser
$env:CERTIFICA_BASIC_PASSWORD = $BasicPassword

$appOut = Join-Path $runtime 'preview-app-output.log'
$appErr = Join-Path $runtime 'preview-app-error.log'
$app = Start-Process -FilePath $Python -ArgumentList @('app.py','--host','127.0.0.1','--port',"$Port") `
    -WorkingDirectory $project -WindowStyle Hidden -RedirectStandardOutput $appOut `
    -RedirectStandardError $appErr -PassThru
Set-Content -LiteralPath $appPidFile -Value $app.Id

$deadline = [DateTime]::UtcNow.AddSeconds(30)
do {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/healthz" -TimeoutSec 3
        if ($health.status -eq 'ok') { break }
    } catch {
        Start-Sleep -Milliseconds 500
    }
} while ([DateTime]::UtcNow -lt $deadline)
if ($health.status -ne 'ok') {
    throw "A aplicação não iniciou. Consulte $appErr"
}

$publicHealth = Invoke-RestMethod -Uri "$publicUrl/healthz" -TimeoutSec 20
if ($publicHealth.status -ne 'ok') { throw 'A URL pública não passou na verificação de saúde.' }
Set-Content -LiteralPath (Join-Path $runtime 'preview-url.txt') -Value $publicUrl

Write-Host "Certifica publicado em: $publicUrl"
Write-Host "Usuário: $BasicUser"
Write-Host "Senha desta execução: $BasicPassword"
Write-Host 'Mantenha este computador ligado e conectado à internet.'
