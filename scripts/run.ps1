param([switch]$Demo)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if ($Demo) {
    & "$projectRoot\.venv\Scripts\python.exe" -m repairshop --demo --data-dir "$projectRoot\demo-data"
} else {
    & "$projectRoot\.venv\Scripts\python.exe" -m repairshop
}
