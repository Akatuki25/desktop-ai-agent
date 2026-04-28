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
$env:VOICEVOX_BIN             = Join-Path $repo 'vendor\voicevox\run.exe'
$env:AGENT_DATA_DIR           = Join-Path $env:APPDATA 'desktop-ai-agent'

# LLAMA_MODEL resolution:
#   1. Honor an existing LLAMA_MODEL env var (e.g. set in .env to override)
#   2. Otherwise auto-detect the GGUF in models/. Prefer 9B, fall back
#      to 4B, then any Qwen3.5 GGUF. Fail-soft: if nothing is there
#      yet, leave LLAMA_MODEL pointing at the 9B path so setup.ps1
#      messages still make sense.
$modelsDir = Join-Path $repo 'models'
$pre = $env:LLAMA_MODEL
if ([string]::IsNullOrWhiteSpace($pre) -or -not (Test-Path $pre)) {
    $candidates = @(
        (Join-Path $modelsDir 'Qwen3.5-9B-Q4_K_M.gguf')
        (Join-Path $modelsDir 'Qwen3.5-4B-Q4_K_M.gguf')
    )
    $picked = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $picked) {
        # Last resort: any Qwen3.5 GGUF in models/
        $picked = Get-ChildItem $modelsDir -Filter 'Qwen3.5-*.gguf' -ErrorAction SilentlyContinue `
            | Select-Object -First 1 -ExpandProperty FullName
    }
    if ($picked) {
        $env:LLAMA_MODEL = $picked
    } else {
        $env:LLAMA_MODEL = Join-Path $modelsDir 'Qwen3.5-9B-Q4_K_M.gguf'
    }
}

# Surface per-user toolchains on PATH so pnpm / cargo / uv work in this shell.
function Add-PathOnce {
    param([string]$p)
    if (-not (Test-Path $p)) { return }
    if (-not ($env:Path -split ';' | Where-Object { $_ -ieq $p })) {
        $env:Path = "$p;$env:Path"
    }
}
Add-PathOnce "$env:USERPROFILE\.cargo\bin"
Add-PathOnce "$env:USERPROFILE\.local\bin"
# fnm via winget lives under a versioned dir; pick whichever is there.
Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Directory -ErrorAction SilentlyContinue `
    | Where-Object { $_.Name -like 'Schniz.fnm*' } `
    | ForEach-Object { Add-PathOnce $_.FullName }
Add-PathOnce "$env:LOCALAPPDATA\fnm"

# Activate fnm so `node` and `pnpm` resolve to the project-pinned version.
if (Get-Command fnm -ErrorAction SilentlyContinue) {
    try {
        fnm env --use-on-cd | Out-String | Invoke-Expression
        if (Test-Path (Join-Path $repo '.node-version')) {
            Push-Location $repo
            fnm use --install-if-missing 2>&1 | Out-Null
            Pop-Location
        }
        $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
        if ($nodeCmd) {
            Add-PathOnce ([System.IO.Path]::GetDirectoryName($nodeCmd.Source))
        }
    } catch {
        Write-Host "  fnm activation failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

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
