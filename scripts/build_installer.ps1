param(
    [string]$InputExe = 'build\offline-payload\RepairShopManager.exe',
    [string]$OutputDirectory = 'dist',
    [string]$Version = '1.4.4',
    [string]$Compiler = 'build\installer-tools\inno-6.4.3\ISCC.exe'
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$payload = [IO.Path]::GetFullPath((Join-Path $repo $InputExe))
$outputRoot = [IO.Path]::GetFullPath((Join-Path $repo $OutputDirectory))
$compilerPath = [IO.Path]::GetFullPath((Join-Path $repo $Compiler))
if (-not $outputRoot.StartsWith($repo + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Output directory must be inside the repository.' }
if (-not (Test-Path -LiteralPath $payload -PathType Leaf)) { throw "Build the application first: $payload" }
if (-not (Test-Path -LiteralPath $compilerPath -PathType Leaf)) { throw 'Inno Setup compiler missing. See docs/INSTALLER.md for portable compiler setup.' }
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
& $compilerPath "/DAppVersion=$Version" "/DAppPayload=$payload" "/DSetupOutput=$outputRoot" (Join-Path $PSScriptRoot 'installer\RepairShopManager.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
$setupPath = Join-Path $outputRoot "RepairShopManager-Offline-Setup-$Version.exe"
Write-Output "Offline setup: $setupPath"
Write-Output "Bytes: $((Get-Item -LiteralPath $setupPath).Length)"
Write-Output "SHA256: $((Get-FileHash -LiteralPath $setupPath -Algorithm SHA256).Hash)"
