$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$dockerExe = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
& $dockerExe info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop and wait until Docker Engine is ready.' }
& $dockerExe compose --project-name bormostats-dev --env-file .env -f infra/docker/docker-compose.yml -f compose.local.yaml up -d
if ($LASTEXITCODE -ne 0) { throw 'BormoStats startup failed. See Docker Compose output.' }
& $dockerExe compose --project-name bormostats-dev --env-file .env -f infra/docker/docker-compose.yml -f compose.local.yaml ps
