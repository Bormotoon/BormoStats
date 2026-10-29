$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose --project-name bormostats-dev --env-file .env -f infra/docker/docker-compose.yml -f compose.local.yaml stop
