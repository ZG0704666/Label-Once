param(
    [Parameter(Mandatory=$true)][string]$Project,
    [Parameter(Mandatory=$true)][string]$Fixtures,
    [string]$Output = "$PSScriptRoot\..\..\acceptance\wpf\frozen\screenshots",
    [switch]$SkipBuild
)
. "$PSScriptRoot\common.ps1"
$harness = Join-Path $workspaceRoot '.tools\desktop-harness'
if (!$SkipBuild) {
    & $dotnetPath publish "$PSScriptRoot\..\LabelOnce.Desktop.Tests" -c Release -r win-x64 --self-contained true -p:RestoreLockedMode=true -o $harness
    if ($LASTEXITCODE) { throw '窗口测试程序构建失败' }
}
$outputPath = [IO.Path]::GetFullPath($Output)
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$psi = [Diagnostics.ProcessStartInfo]::new()
$psi.FileName = Join-Path $harness 'LabelOnce.Desktop.Tests.exe'
$psi.WorkingDirectory = $env:TEMP
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.StandardOutputEncoding = [Text.Encoding]::UTF8
$psi.StandardErrorEncoding = [Text.Encoding]::UTF8
foreach ($key in @($psi.Environment.Keys)) { if ($key -match '^(CONDA|PYTHON|DOTNET|LABELONCE)') { $psi.Environment.Remove($key) | Out-Null } }
$psi.Environment['PATH'] = "$env:SystemRoot\System32;$env:SystemRoot"
$psi.Environment['LABELONCE_BACKEND'] = Join-Path $workspaceRoot 'Release\TrainStudio-WPF\backend\backend.exe'
$psi.Environment['APPDATA'] = Join-Path $outputPath 'appdata'
$psi.Arguments = '"{0}" "{1}" "{2}"' -f $outputPath, [IO.Path]::GetFullPath($Project), [IO.Path]::GetFullPath($Fixtures)
$p = [Diagnostics.Process]::Start($psi)
$stdout = $p.StandardOutput.ReadToEndAsync()
$stderr = $p.StandardError.ReadToEndAsync()
$p.WaitForExit()
$log = $stdout.Result + $stderr.Result
[IO.File]::WriteAllText((Join-Path $outputPath 'desktop-tests.log'), $log)
Write-Host $log
if ($p.ExitCode) { throw "窗口测试失败，退出码 $($p.ExitCode)" }
$staleError = Join-Path $outputPath 'desktop-error.txt'
if (Test-Path -LiteralPath $staleError) { Remove-Item -LiteralPath $staleError }
