# scripts/activate.ps1
# Repo-local environment activation. Process scope only — closing the shell
# restores the original environment. Usage:
#   . .\scripts\activate.ps1
#
# Sets PLAYWRIGHT_BROWSERS_PATH, LLAMA_SERVER_BIN, LLAMA_MODEL, VOICEVOX_BIN,
# AGENT_DATA_DIR and loads repo\.env (KEY=VALUE lines) into the current session.

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path "$PSScriptRoot\..").Path

$env:REPO_ROOT                = $repo
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $repo 'vendor\playwright-browsers'
$env:LLAMA_SERVER_BIN         = Join-Path $repo 'vendor\llama.cpp\llama-server.exe'
$env:LLAMA_MODEL              = Join-Path $repo 'models\Qwen3-8B-Instruct-Q4_K_M.gguf'
$env:VOICEVOX_BIN             = Join-Path $repo 'vendor\voicevox\run.exe'
$env:AGENT_DATA_DIR           = Join-Path $env:APPDATA 'desktop-ai-agent'

$envFile = Join-Path $repo '.env'
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line -match '^([^=]+)=(.*)$') {
            $name  = $Matches[1].Trim()
            $value = $Matches[2].Trim().Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }
    Write-Host "  .env loaded" -ForegroundColor DarkGray
} else {
    Write-Host "  .env not found (copy .env.example to .env)" -ForegroundColor Yellow
}

# Warn (don't fail) about missing project-local assets — setup.ps1 handles install.
$missing = @()
if (-not (Test-Path $env:LLAMA_SERVER_BIN)) { $missing += 'llama-server.exe' }
if (-not (Test-Path $env:LLAMA_MODEL))      { $missing += 'Qwen3 GGUF model' }
if (-not (Test-Path $env:VOICEVOX_BIN))     { $missing += 'voicevox run.exe' }
if ($missing.Count -gt 0) {
    Write-Host "  missing: $($missing -join ', ') — run scripts\setup.ps1" -ForegroundColor Yellow
}

Write-Host "desktop-ai-agent env activated" -ForegroundColor Green
Write-Host "  REPO_ROOT = $repo" -ForegroundColor DarkGray
