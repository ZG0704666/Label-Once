param([string]$Conda = (Join-Path $env:USERPROFILE 'anaconda3\Scripts\conda.exe'))
$ErrorActionPreference='Stop'
$sourceRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$workspaceRoot=[IO.Path]::GetFullPath((Join-Path $sourceRoot '..\..'))
$pythonPath=Join-Path (Split-Path (Split-Path $Conda -Parent) -Parent) 'envs\labelonce\python.exe'
if (!(Test-Path $pythonPath)) { & $Conda create -n labelonce python=3.10 pip -y --override-channels -c https://repo.anaconda.com/pkgs/main; if ($LASTEXITCODE) { throw 'Conda 创建失败' } }
& $pythonPath -m pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE) { throw 'CUDA Torch 安装失败' }
& $pythonPath -m pip install -r (Join-Path $sourceRoot 'requirements.lock.txt') --index-url https://pypi.org/simple --extra-index-url https://pypi.nvidia.com --extra-index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE) { throw '依赖安装失败' }
& $pythonPath -m pip check
if ($LASTEXITCODE) { throw '依赖检查失败' }
$toolRoot=Join-Path $workspaceRoot '.tools';New-Item -ItemType Directory -Force $toolRoot | Out-Null
$installer=Join-Path $toolRoot 'dotnet-install.ps1'
if (!(Test-Path (Join-Path $toolRoot 'dotnet\dotnet.exe'))) { Invoke-WebRequest 'https://dot.net/v1/dotnet-install.ps1' -OutFile $installer; & $installer -Version 10.0.401 -InstallDir (Join-Path $toolRoot 'dotnet') -NoPath }
& (Join-Path $sourceRoot 'scripts\prepare_models.ps1')
