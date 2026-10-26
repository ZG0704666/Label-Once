param([switch]$SkipBackend)
. "$PSScriptRoot\common.ps1"
$releaseRoot=Join-Path $workspaceRoot 'Release\TrainStudio-WPF'
Push-Location $sourceRoot
try {
    if (!$SkipBackend) { & $pythonPath -m PyInstaller --noconfirm Backend.spec; if ($LASTEXITCODE) { throw '后端打包失败' } }
    Set-Location desktop
    & $dotnetPath publish LabelOnce.Desktop\LabelOnce.Desktop.csproj -c Release -r win-x64 --self-contained true -p:RestoreLockedMode=true -p:PublishSingleFile=false -o $releaseRoot
    if ($LASTEXITCODE) { throw 'WPF 发布失败' }
    $backendTarget=Join-Path $releaseRoot 'backend'
    New-Item -ItemType Directory -Force $backendTarget | Out-Null
    if (!$SkipBackend -or !(Test-Path (Join-Path $backendTarget 'backend.exe'))) { Copy-Item -Path (Join-Path $sourceRoot 'dist\backend\*') -Destination $backendTarget -Recurse -Force }
    foreach ($folder in @('models','sam')) { $target=Join-Path $releaseRoot $folder; New-Item -ItemType Directory -Force $target | Out-Null; Copy-Item -Path (Join-Path $sourceRoot "$folder\*.pt") -Destination $target -Force }
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'desktop\README.md') -Destination (Join-Path $releaseRoot 'README.md') -Force
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'requirements.lock.txt') -Destination $releaseRoot -Force
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'docs\WPF_ACCEPTANCE.md') -Destination $releaseRoot -Force
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'docs\PROGRESSIVE_WORKFLOWS.md') -Destination $releaseRoot -Force
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'docs\ANNOTATION_TO_TRAINING.md') -Destination $releaseRoot -Force
    Write-Host "本地成品：$releaseRoot\LabelOnce.exe"
} finally { Pop-Location }
