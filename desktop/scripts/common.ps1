$ErrorActionPreference = 'Stop'
$sourceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $sourceRoot '..\..'))
$pythonPath = if ($env:LABELONCE_PYTHON) { $env:LABELONCE_PYTHON } else { Join-Path $env:USERPROFILE 'anaconda3\envs\labelonce\python.exe' }
$dotnetPath = Join-Path $workspaceRoot '.tools\dotnet\dotnet.exe'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:PYTHONUTF8 = '1'
$env:LABELONCE_SOURCE = $sourceRoot
$env:LABELONCE_PYTHON = $pythonPath
if (!(Test-Path -LiteralPath $pythonPath)) { throw '请先运行 desktop/scripts/setup.ps1 创建 labelonce 环境' }
if (!(Test-Path -LiteralPath $dotnetPath)) { throw '请先运行 desktop/scripts/setup.ps1 安装项目专用 SDK' }
