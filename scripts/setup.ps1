# scripts/setup.ps1
# Idempotent Windows setup for desktop-ai-agent.
#
# - root pollution is limited to Visual Studio Build Tools (Rust linker dep).
# - everything else is per-user or project-local under vendor/ and models/.
# - safe to re-run; existing assets are skipped.
#
# Usage:
#   .\scripts\setup.ps1                # full setup
#   .\scripts\setup.ps1 -SkipToolchain  # skip rustup/fnm/uv install
#   .\scripts\setup.ps1 -SkipModel      # skip GGUF model download (~5GB)
#   .\scripts\setup.ps1 -SkipVoicevox   # skip VOICEVOX engine

[CmdletBinding()]
param(
    [switch]$SkipToolchain,
    [switch]$SkipModel,
    [switch]$SkipVoicevox
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repo

# ---- versions (single source of truth) ----
$LLAMA_RELEASE  = 'b4000'
$LLAMA_ZIP      = "llama-$LLAMA_RELEASE-bin-win-avx2-x64.zip"
$LLAMA_URL      = "https://github.com/ggml-org/llama.cpp/releases/download/$LLAMA_RELEASE/$LLAMA_ZIP"

$MODEL_REPO     = 'Qwen/Qwen3-8B-Instruct-GGUF'
$MODEL_FILE     = 'Qwen3-8B-Instruct-Q4_K_M.gguf'
$MODEL_URL      = "https://huggingface.co/$MODEL_REPO/resolve/main/$MODEL_FILE"

$VOICEVOX_VER   = '0.24.1'
$VOICEVOX_DIR   = "voicevox_engine-windows-cpu-x64-$VOICEVOX_VER"
$VOICEVOX_7Z    = "$VOICEVOX_DIR.7z"
$VOICEVOX_URL   = "https://github.com/VOICEVOX/voicevox_engine/releases/download/$VOICEVOX_VER/$VOICEVOX_7Z"

# ---- helpers ----
function Write-Step { param([string]$msg) Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Skip { param([string]$msg) Write-Host "  [skip] $msg" -ForegroundColor DarkGray }
function Write-Ok   { param([string]$msg) Write-Host "  [ok] $msg"   -ForegroundColor Green }

function Test-Command {
    param([string]$name)
    $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Ensure-Dir { param([string]$path) New-Item -ItemType Directory -Force -Path $path | Out-Null }

function Download-File {
    param([string]$url, [string]$out)
    if (Test-Path $out) { Write-Skip "already downloaded: $out"; return }
    Write-Host "  downloading $url" -ForegroundColor DarkGray
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
}

# ---- 0. preflight ----
Write-Step '0. preflight'

if (-not (Test-Command git))  { throw 'git not found. Install Git for Windows first.' }
Write-Ok 'git'

# Warn about VS Build Tools (root-installed, cannot be auto-installed safely here).
$vsMsvc = Get-ChildItem 'C:\Program Files (x86)\Microsoft Visual Studio\*\BuildTools\VC\Tools\MSVC' -ErrorAction SilentlyContinue
if (-not $vsMsvc) {
    Write-Host '  [warn] Visual Studio Build Tools (C++ workload) not detected.' -ForegroundColor Yellow
    Write-Host '         Install manually: see docs/setup.md section 1.2' -ForegroundColor Yellow
} else {
    Write-Ok 'VS Build Tools detected'
}

# ---- 1. per-user toolchains ----
if (-not $SkipToolchain) {
    Write-Step '1a. rustup (per-user)'
    if (Test-Command rustc) {
        Write-Skip "rustc already available: $(rustc --version)"
    } else {
        $rustupInit = Join-Path $env:TEMP 'rustup-init.exe'
        Download-File 'https://win.rustup.rs/x86_64' $rustupInit
        & $rustupInit -y --default-toolchain stable --profile minimal
        Remove-Item $rustupInit -Force
        $env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"
        Write-Ok 'rustup installed'
    }

    Write-Step '1b. fnm (per-user Node manager)'
    if (Test-Command fnm) {
        Write-Skip 'fnm already installed'
    } else {
        winget install --id Schniz.fnm -e --accept-source-agreements --accept-package-agreements
        $env:Path = "$env:LOCALAPPDATA\fnm;$env:Path"
        Write-Ok 'fnm installed'
    }

    Write-Step '1c. uv (per-user Python manager)'
    if (Test-Command uv) {
        Write-Skip "uv already available: $(uv --version)"
    } else {
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
        Write-Ok 'uv installed'
    }
} else {
    Write-Step '1. per-user toolchains (skipped)'
}

# ---- 2. project dependencies ----
Write-Step '2a. Node via fnm'
if (Test-Path (Join-Path $repo '.node-version')) {
    Push-Location $repo
    fnm use --install-if-missing
    corepack enable | Out-Null
    Pop-Location
    Write-Ok 'node + pnpm ready'
} else {
    Write-Host '  [warn] .node-version not found — skipping fnm use' -ForegroundColor Yellow
}

Write-Step '2b. frontend (pnpm install)'
$frontendDir = Join-Path $repo 'frontend'
if (Test-Path (Join-Path $frontendDir 'package.json')) {
    Push-Location $frontendDir
    pnpm install
    Pop-Location
    Write-Ok 'frontend deps installed'
} else {
    Write-Skip 'frontend/package.json not yet present'
}

Write-Step '2c. agent (uv sync)'
$agentDir = Join-Path $repo 'agent'
if (Test-Path (Join-Path $agentDir 'pyproject.toml')) {
    Push-Location $agentDir
    uv sync
    Pop-Location
    Write-Ok 'agent deps installed'
} else {
    Write-Skip 'agent/pyproject.toml not yet present'
}

# ---- 3. project-local binaries ----
Ensure-Dir (Join-Path $repo 'vendor')
Ensure-Dir (Join-Path $repo 'models')

Write-Step '3a. llama.cpp (prebuilt)'
$llamaDir = Join-Path $repo 'vendor\llama.cpp'
$llamaExe = Join-Path $llamaDir 'llama-server.exe'
if (Test-Path $llamaExe) {
    Write-Skip "llama-server.exe already at $llamaExe"
} else {
    Ensure-Dir $llamaDir
    $zipOut = Join-Path $env:TEMP $LLAMA_ZIP
    Download-File $LLAMA_URL $zipOut
    Expand-Archive -Path $zipOut -DestinationPath $llamaDir -Force
    Remove-Item $zipOut -Force
    Write-Ok "llama.cpp $LLAMA_RELEASE extracted"
}

Write-Step '3b. Qwen3 GGUF model'
$modelPath = Join-Path $repo "models\$MODEL_FILE"
if ($SkipModel) {
    Write-Skip 'model download skipped (flag)'
} elseif (Test-Path $modelPath) {
    Write-Skip "$MODEL_FILE already at $modelPath"
} else {
    Write-Host '  downloading model (several GB, may take a while)' -ForegroundColor DarkGray
    if (Test-Command uv) {
        uv tool run --from huggingface_hub huggingface-cli download `
            $MODEL_REPO $MODEL_FILE `
            --local-dir (Join-Path $repo 'models') `
            --local-dir-use-symlinks False
    } else {
        Download-File $MODEL_URL $modelPath
    }
    Write-Ok 'model downloaded'
}

Write-Step '3c. Playwright Chromium (project-local cache)'
$playwrightDir = Join-Path $repo 'vendor\playwright-browsers'
$env:PLAYWRIGHT_BROWSERS_PATH = $playwrightDir
if ((Test-Path $playwrightDir) -and (Get-ChildItem $playwrightDir -ErrorAction SilentlyContinue)) {
    Write-Skip 'playwright browsers already present'
} elseif (Test-Path (Join-Path $agentDir 'pyproject.toml')) {
    Push-Location $agentDir
    uv run playwright install chromium
    Pop-Location
    Write-Ok 'chromium installed to vendor/'
} else {
    Write-Skip 'agent not yet scaffolded — run playwright install later'
}

Write-Step '3d. VOICEVOX engine (portable)'
$vvDir = Join-Path $repo 'vendor\voicevox'
$vvBin = Join-Path $vvDir 'run.exe'
if ($SkipVoicevox) {
    Write-Skip 'voicevox skipped (flag)'
} elseif (Test-Path $vvBin) {
    Write-Skip "voicevox already at $vvBin"
} elseif (-not (Test-Command 7z)) {
    Write-Host '  [warn] 7-Zip not found. Install with: winget install 7zip.7zip -e' -ForegroundColor Yellow
    Write-Host '         Then re-run this script (or pass -SkipVoicevox).' -ForegroundColor Yellow
} else {
    $archive = Join-Path $env:TEMP $VOICEVOX_7Z
    Download-File $VOICEVOX_URL $archive
    & 7z x $archive "-o$(Join-Path $repo 'vendor')" -y | Out-Null
    $extracted = Join-Path $repo "vendor\$VOICEVOX_DIR"
    if (Test-Path $vvDir) { Remove-Item -Recurse -Force $vvDir }
    Rename-Item $extracted $vvDir
    Remove-Item $archive -Force
    Write-Ok 'voicevox extracted'
}

# ---- 4. .env scaffold ----
Write-Step '4. .env scaffold'
$envFile = Join-Path $repo '.env'
$envExample = Join-Path $repo '.env.example'
if (-not (Test-Path $envFile) -and (Test-Path $envExample)) {
    Copy-Item $envExample $envFile
    Write-Ok '.env created from .env.example — fill in secrets'
} elseif (Test-Path $envFile) {
    Write-Skip '.env already exists'
} else {
    Write-Skip '.env.example missing'
}

# ---- done ----
Write-Host ''
Write-Host 'setup complete.' -ForegroundColor Green
Write-Host 'next steps:' -ForegroundColor Cyan
Write-Host '  1.  . .\scripts\activate.ps1'
Write-Host '  2.  cd frontend; pnpm tauri dev'
