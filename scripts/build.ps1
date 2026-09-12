$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
& "$projectRoot\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean RepairShopManager.spec
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
$applicationFile = Join-Path $projectRoot 'dist\RepairShopManager.exe'
if (-not (Test-Path -LiteralPath $applicationFile -PathType Leaf)) { throw 'Single-file executable was not produced.' }
Compress-Archive -LiteralPath $applicationFile -DestinationPath "$projectRoot\dist\RepairShopManager-Windows-x64.zip" -Force
Write-Output 'Single-file Windows package created. The portable ZIP contains only RepairShopManager.exe.'
