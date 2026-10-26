param([switch]$Clean)
. "$PSScriptRoot\..\desktop\scripts\common.ps1"
Set-Location (Split-Path $PSScriptRoot -Parent)
# PyInstaller --clean refreshes its own cache without deleting other release builds.
& $pythonPath -m PyInstaller --noconfirm --clean YoloTrainStudio.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
foreach ($folder in @('models','sam')) {
    $source = Join-Path (Get-Location) $folder
    if (Test-Path $source) {
        $target = Join-Path 'dist\YoloTrainStudio' $folder
        New-Item -ItemType Directory -Force $target | Out-Null
        Copy-Item -Path (Join-Path $source '*.pt') -Destination $target
    }
}
Copy-Item README.md,requirements.lock.txt dist\YoloTrainStudio
Copy-Item docs dist\YoloTrainStudio -Recurse -Force
Write-Host "Built dist\YoloTrainStudio"
