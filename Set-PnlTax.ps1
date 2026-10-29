param([Parameter(Mandatory = $true)][bool]$Enabled)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$envPath = Join-Path $PSScriptRoot '.env'
$taxText = [System.IO.File]::ReadAllText($envPath)
$taxValue = if ($Enabled) { 'true' } else { 'false' }
if ($taxText -match '(?m)^PNL_REALIZATION_TAX_ENABLED=') {
    $taxText = [regex]::Replace($taxText, '(?m)^PNL_REALIZATION_TAX_ENABLED=[^\r\n]*', "PNL_REALIZATION_TAX_ENABLED=$taxValue")
} else { $taxText += "`nPNL_REALIZATION_TAX_ENABLED=$taxValue`n" }
[System.IO.File]::WriteAllText($envPath, $taxText, [System.Text.UTF8Encoding]::new($false))
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose --project-name bormostats-dev --env-file .env -f infra/docker/docker-compose.yml -f compose.local.yaml up -d --no-deps backend worker beat
if ($LASTEXITCODE -ne 0) { throw 'Could not apply tax setting to the running services.' }
Write-Host "PNL_REALIZATION_TAX_ENABLED=$taxValue"
