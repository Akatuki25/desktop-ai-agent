# scripts/activate.ps1
# Repo-local environment activation. Process scope only — closing the shell
# restores the original environment. Usage:
#   . .\scripts\activate.ps1
#
# Sets PLAYWRIGHT_BROWSERS_PATH, LLAMA_SERVER_BIN, LLAMA_MODEL, VOICEVOX_BIN,
# AGENT_DATA_DIR, surfaces fnm/node/pnpm/cargo/uv on PATH, and loads
# repo\.env (KEY=VALUE lines) into the current session.

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path "$PSScriptRoot\..").Path

$env:REPO_ROOT                = $repo
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $repo 'vendor\playwright-browsers'
$env:LLAMA_SERVER_BIN         = Join-Path $repo 'vendor\llama.cpp\llama-server.exe'
$env:VOICEVOX_BIN             = Join-Path $repo 'vendor\voicevox\run.exe'
$env:AGENT_DATA_DIR           = Join-Path $env:APPDATA 'desktop-ai-agent'

# ---- Load .env first so it can override LLAMA_MODEL / MODEL_SIZE below ----
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

# ---- LLAMA_MODEL resolution ----
# Priority:
#   1. LLAMA_MODEL already set (env var or .env, absolute path) — honored as-is
#      if the file exists.
#   2. MODEL_SIZE env var (9B / 4B) — pick the matching file in models/.
#      This is the easy way to switch after running setup.ps1 -Model 4B
#      while keeping a 9B GGUF on disk.
#   3. Auto-detect: prefer 9B, then 4B, then any Qwen3.5 GGUF.
#   4. Fail-soft fallback: point at the 9B path so the missing-asset
#      warning below makes sense.
$modelsDir = Join-Path $repo 'models'
$model9b   = Join-Path $modelsDir 'Qwen3.5-9B-Q4_K_M.gguf'
$model4b   = Join-Path $modelsDir 'Qwen3.5-4B-Q4_K_M.gguf'
$pre       = $env:LLAMA_MODEL
$sizeHint  = $env:MODEL_SIZE

if (-not [string]::IsNullOrWhiteSpace($pre) -and (Test-Path $pre)) {
    # Honor explicit override.
} elseif ($sizeHint -eq '4B' -and (Test-Path $model4b)) {
    $env:LLAMA_MODEL = $model4b
} elseif ($sizeHint -eq '9B' -and (Test-Path $model9b)) {
    $env:LLAMA_MODEL = $model9b
} elseif (Test-Path $model9b) {
    $env:LLAMA_MODEL = $model9b
} elseif (Test-Path $model4b) {
    $env:LLAMA_MODEL = $model4b
} else {
    $any = Get-ChildItem $modelsDir -Filter 'Qwen3.5-*.gguf' -ErrorAction SilentlyContinue `
        | Select-Object -First 1 -ExpandProperty FullName
    if ($any) { $env:LLAMA_MODEL = $any } else { $env:LLAMA_MODEL = $model9b }
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

# Warn (don't fail) about missing project-local assets — setup.ps1 handles install.
$missing = @()
if (-not (Test-Path $env:LLAMA_SERVER_BIN)) { $missing += 'llama-server.exe' }
if (-not (Test-Path $env:LLAMA_MODEL))      { $missing += 'Qwen3 GGUF model' }
if (-not (Test-Path $env:VOICEVOX_BIN))     { $missing += 'voicevox run.exe' }
if ($missing.Count -gt 0) {
    Write-Host "  missing: $($missing -join ', ') — run scripts\setup.ps1" -ForegroundColor Yellow
}

Write-Host "desktop-ai-agent env activated" -ForegroundColor Green
Write-Host "  REPO_ROOT   = $repo" -ForegroundColor DarkGray
$modelLabel = Split-Path $env:LLAMA_MODEL -Leaf
Write-Host "  LLAMA_MODEL = $modelLabel" -ForegroundColor DarkGray
