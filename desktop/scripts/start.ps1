param([string]$Project)
. "$PSScriptRoot\common.ps1"
Push-Location (Join-Path $sourceRoot 'desktop')
try { & $dotnetPath build LabelOnce.sln -c Release --nologo; if ($LASTEXITCODE) { throw 'WPF 编译失败' }; $exe=Join-Path $sourceRoot 'desktop\LabelOnce.Desktop\bin\Release\net10.0-windows\LabelOnce.exe'; if ($Project) { & $exe $Project } else { & $exe } } finally { Pop-Location }
