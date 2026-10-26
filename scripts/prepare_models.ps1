param([string]$ModelSource)
$ErrorActionPreference='Stop'
$sourceRoot = Split-Path $PSScriptRoot -Parent
if (!$ModelSource) { $ModelSource = Join-Path (Split-Path (Split-Path $sourceRoot -Parent) -Parent) 'Release\TrainStudio' }
foreach ($folder in @('models','sam')) {
    $weightSource = Join-Path $ModelSource $folder
    if (!(Test-Path -LiteralPath $weightSource)) { throw "Missing model directory: $weightSource" }
    $weightTarget = Join-Path $sourceRoot $folder
    New-Item -ItemType Directory -Force -Path $weightTarget | Out-Null
    Get-ChildItem -LiteralPath $weightSource -Filter '*.pt' -File | Copy-Item -Destination $weightTarget
}
Write-Host 'External weights ready; excluded by .gitignore.'
