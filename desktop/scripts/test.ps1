. "$PSScriptRoot\common.ps1"
Push-Location $sourceRoot
try { & $pythonPath -m pytest -q; if ($LASTEXITCODE) { throw 'Python 测试失败' }; Set-Location desktop; & $dotnetPath run --project LabelOnce.Core.Tests -c Release; if ($LASTEXITCODE) { throw '几何测试失败' } } finally { Pop-Location }
