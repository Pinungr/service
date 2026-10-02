param([string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$outputRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
$workRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'build\pyinstaller'))
foreach ($path in @($outputRoot, $workRoot)) {
    if (-not $path.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Build output and work paths must stay inside the repository.'
    }
}
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
Push-Location (Join-Path $projectRoot 'frontend')
try {
    if (-not (Test-Path -LiteralPath 'node_modules' -PathType Container)) {
        & $npm ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies could not be installed.' }
    }
    & $npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally {
    Pop-Location
}
& "$projectRoot\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --workpath $workRoot --distpath $outputRoot RepairShopManager.spec
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
$applicationFile = Join-Path $outputRoot 'RepairShopManager.exe'
if (-not (Test-Path -LiteralPath $applicationFile -PathType Leaf)) { throw 'Single-file executable was not produced.' }
Compress-Archive -LiteralPath $applicationFile -DestinationPath (Join-Path $outputRoot 'RepairShopManager-Windows-x64.zip') -Force
Write-Output 'Single-file Windows package created. The portable ZIP contains only RepairShopManager.exe.'
